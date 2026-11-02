import logging
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import generics, status, viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from .emails import read_verification_token, send_password_reset_email, send_verification_email
from .models import Address
from .permissions import IsOwnerOrStaff
from .throttles import (
    EmailVerifyThrottle, LoginEmailThrottle, LoginIPThrottle, PasswordResetEmailThrottle,
    PasswordResetIPThrottle, RegisterThrottle,
)
from .serializers import (
    RegisterSerializer, MeSerializer, ProfileUpdateSerializer, ChangePasswordSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer, AddressSerializer,
    AdminCustomerSerializer, GoogleAuthSerializer, VerifyEmailSerializer, EmailLoginSerializer,
)

User = get_user_model()
logger = logging.getLogger(__name__)


def _set_refresh_cookie(response, refresh_token: str):
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=str(refresh_token),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        path="/api/auth/",
    )


def _delete_refresh_cookie(response):
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME,
        path="/api/auth/",
        domain=settings.REFRESH_COOKIE_DOMAIN,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def _blacklist_all_refresh_tokens(user):
    """Sign the user out everywhere (used after a password reset)."""
    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RegisterThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        send_verification_email(user)

        from notifications.services import notify  # local import: avoids a hard app-load-order dependency
        notify(
            user, "account", "Welcome to Grande Auto Hut!",
            "Thanks for creating an account. Start with our Fitment Finder to find parts for your vehicle.",
        )

        return Response(
            {
                "message": "Account created successfully. Check your email to confirm your address.",
                "user": MeSerializer(user).data
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    serializer_class = EmailLoginSerializer
    # Per-IP and per-email limits: slows password guessing without locking real users out.
    throttle_classes = [LoginIPThrottle, LoginEmailThrottle]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        access = serializer.validated_data["access"]
        refresh = serializer.validated_data["refresh"]

        # The refresh token travels ONLY in the httpOnly cookie, so page JavaScript
        # (and therefore any XSS bug) can never read it.
        response = Response({"access": str(access)}, status=status.HTTP_200_OK)
        _set_refresh_cookie(response, refresh)
        return response


def _unique_username(email: str) -> str:
    base = (email.split("@")[0] or "user")[:130]
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate


class GoogleLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not settings.FIREBASE_PROJECT_ID:
            return Response({"detail": "Google sign-in is not configured."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            claims = google_id_token.verify_firebase_token(
                serializer.validated_data["id_token"],
                google_requests.Request(),
                audience=settings.FIREBASE_PROJECT_ID,
                clock_skew_in_seconds=10,  
            )
        except Exception as exc:
            logger.warning("Firebase ID token verification failed: %s", exc)
            claims = None

        if not claims:
            return Response({"detail": "Invalid or expired Google sign-in."},
                            status=status.HTTP_401_UNAUTHORIZED)

        email = (claims.get("email") or "").lower()
        provider = (claims.get("firebase") or {}).get("sign_in_provider")
        if provider != "google.com" or not email or not claims.get("email_verified"):
            return Response({"detail": "Your Google account must have a verified email."},
                            status=status.HTTP_400_BAD_REQUEST)

        created = False
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            full_name = (claims.get("name") or "").strip()
            first, _, last = full_name.partition(" ")
            try:
                with transaction.atomic():
                    user = User(
                        email=email,
                        username=_unique_username(email),
                        first_name=first[:150],
                        last_name=last[:150],
                        role=User.Role.CUSTOMER,
                        is_email_verified=True,
                    )
                    user.set_unusable_password()
                    user.save()
                created = True
            except IntegrityError:
                # Lost a race with a concurrent sign-in for the same email.
                user = User.objects.filter(email__iexact=email).first()
                if user is None:
                    raise

        if not user.is_active:
            return Response({"detail": "This account is disabled."},
                            status=status.HTTP_403_FORBIDDEN)

        if not user.is_email_verified:
            # Google has verified ownership of this address.
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])

        if created:
            from notifications.services import notify
            notify(
                user, "account", "Welcome to Grande Auto Hut!",
                "Thanks for creating an account. Start with our Fitment Finder to find parts for your vehicle.",
            )

        refresh = RefreshToken.for_user(user)
        response = Response(
            {
                "access": str(refresh.access_token),
                "created": created,
                "user": MeSerializer(user).data,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
        _set_refresh_cookie(response, refresh)
        return response


class RefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        # Support reading refresh token from cookie or fallback to request body payload
        refresh_token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME) or request.data.get("refresh")
        if not refresh_token:
            return Response({"detail": "Refresh token missing."}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = self.get_serializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return Response({"detail": "Refresh token invalid or expired."}, status=status.HTTP_401_UNAUTHORIZED)

        access = serializer.validated_data["access"]
        response = Response({"access": str(access)}, status=status.HTTP_200_OK)

        new_refresh = serializer.validated_data.get("refresh")
        if new_refresh:
            _set_refresh_cookie(response, new_refresh)

        return response


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME) or request.data.get("refresh")
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _delete_refresh_cookie(response)
        return response


class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        return ProfileUpdateSerializer if self.request.method in ("PATCH", "PUT") else MeSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(MeSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        return Response({"detail": "Password updated."})


class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetIPThrottle, PasswordResetEmailThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            send_password_reset_email(user)
        # Same answer whether or not the account exists, so this can't be used to find registered emails.
        return Response({"detail": "If that email exists, a reset link has been sent."})


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetIPThrottle]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            uid = force_str(urlsafe_base64_decode(data["uid"]))
            user = User.objects.get(pk=uid, is_active=True)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError, DjangoValidationError):
            return Response({"detail": "Invalid reset link."}, status=status.HTTP_400_BAD_REQUEST)

        if not default_token_generator.check_token(user, data["token"]):
            return Response({"detail": "Invalid or expired reset link."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(data["new_password"])
        # Following the emailed link proves the person controls this address.
        user.is_email_verified = True
        user.save()
        # Anyone holding an old session (including a thief who knew the old password) is signed out.
        _blacklist_all_refresh_tokens(user)
        return Response({"detail": "Password has been reset. You can now log in."})


class VerifyEmailView(APIView):
    """POST /api/auth/verify-email/  Body: {"token": "..."} - from the link in the verification email."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [EmailVerifyThrottle]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = read_verification_token(serializer.validated_data["token"])
        if not payload:
            return Response({"detail": "This verification link is invalid or has expired."},
                            status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(pk=payload.get("uid"), is_active=True).first()
        if user is None or user.email.lower() != payload.get("email"):
            return Response({"detail": "This verification link is invalid or has expired."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not user.is_email_verified:
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified", "updated_at"])
        return Response({"detail": "Email confirmed. Thank you!"})


class ResendVerificationView(APIView):
    """POST /api/auth/resend-verification/ - for the logged-in user."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [EmailVerifyThrottle]

    def post(self, request):
        user = request.user
        if user.is_email_verified:
            return Response({"detail": "Your email is already confirmed."})
        send_verification_email(user)
        return Response({"detail": "Verification email sent. Check your inbox (and spam folder)."})


class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class IsStaffRole(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(
            user.is_staff
            or user.is_superuser
            or getattr(user, "role", User.Role.CUSTOMER) != User.Role.CUSTOMER
        )


class AdminCustomerListView(generics.ListAPIView):
    serializer_class = AdminCustomerSerializer
    permission_classes = [IsStaffRole]
    pagination_class = None  # full list; the admin page searches it client-side

    def get_queryset(self):
        return User.objects.filter(role=User.Role.CUSTOMER).order_by("-created_at")