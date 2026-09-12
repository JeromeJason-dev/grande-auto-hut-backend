from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status, views
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend
from accounts.permissions import IsStaffOrAdmin
from .models import Cart, CartItem, Order
from .serializers import (
    CartSerializer, AddCartItemSerializer, UpdateCartItemSerializer,
    CheckoutSerializer, OrderListSerializer, OrderDetailSerializer, OrderStatusUpdateSerializer,
)
from .services import (
    get_or_create_cart, checkout, update_status,
    CheckoutError, InvalidTransitionError,
)


# Cart

class CartView(generics.RetrieveAPIView):
    serializer_class = CartSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return get_or_create_cart(self.request.user)


class CartItemCreateView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = AddCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.validated_data["product"]
        quantity = serializer.validated_data["quantity"]

        cart = get_or_create_cart(request.user)
        item, created = CartItem.objects.get_or_create(cart=cart, product=product, defaults={"quantity": quantity})
        if not created:
            item.quantity += quantity
            item.save(update_fields=["quantity"])

        return Response(CartSerializer(cart).data, status=status.HTTP_201_CREATED)


class CartItemDetailView(views.APIView):
    """PATCH/DELETE /api/cart/items/{id}/"""
    permission_classes = [permissions.IsAuthenticated]

    def _get_item(self, request, pk):
        return get_object_or_404(CartItem, pk=pk, cart__user=request.user)

    def patch(self, request, pk):
        item = self._get_item(request, pk)
        serializer = UpdateCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item.quantity = serializer.validated_data["quantity"]
        item.save(update_fields=["quantity"])
        return Response(CartSerializer(item.cart).data)

    def delete(self, request, pk):
        item = self._get_item(request, pk)
        cart = item.cart
        item.delete()
        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)


# Checkout / Orders

class CheckoutView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        cart = get_or_create_cart(request.user)

        try:
            order = checkout(cart, request.user, data["_resolved_address"], data["payment_method"])
        except CheckoutError as exc:
            raise ValidationError(str(exc))

        return Response(OrderDetailSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderListView(generics.ListAPIView):
    serializer_class = OrderListSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status"]

    def get_queryset(self):
        if self.request.user.is_staff_role:
            return Order.objects.all()
        return Order.objects.filter(user=self.request.user)


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        if self.request.user.is_staff_role:
            return Order.objects.all()
        return Order.objects.filter(user=self.request.user)


class OrderStatusUpdateView(views.APIView):
    permission_classes = [IsStaffOrAdmin]

    def patch(self, request, id):
        order = get_object_or_404(Order, id=id)
        serializer = OrderStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = update_status(
                order,
                serializer.validated_data["status"],
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except InvalidTransitionError as exc:
            raise ValidationError(str(exc))
        except CheckoutError as exc:
            # e.g. confirming an order but stock vanished in the meantime
            raise ValidationError(str(exc))
        return Response(OrderDetailSerializer(order).data)
