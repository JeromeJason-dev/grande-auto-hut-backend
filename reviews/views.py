import uuid

from django.db.models import Avg, Count, Q
from rest_framework import generics, permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.permissions import IsStaffOrAdmin
from .models import Review
from .serializers import ReviewSerializer, ReviewWriteSerializer, StaffReviewSerializer


class ProductReviewListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return Review.objects.filter(product_id=self.kwargs["product_id"]).select_related("user")

    def get_serializer_class(self):
        return ReviewWriteSerializer if self.request.method == "POST" else ReviewSerializer

    def get_serializer_context(self):
        return {"request": self.request}

    def perform_create(self, serializer):
        serializer.save(product_id=self.kwargs["product_id"])


class MyReviewDeleteView(generics.DestroyAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        if self.request.user.is_staff_role:
            return Review.objects.all()
        return Review.objects.filter(user=self.request.user)


class StaffReviewPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        # Headline numbers for the whole filtered set, not just this page.
        response.data["summary"] = self.summary
        return response


class StaffReviewListView(generics.ListAPIView):
    """
    GET /api/reviews/  (staff/admin only) - every customer review, newest first.
    Query params: rating (1-5), product (id), verified (true|false), q (product / customer / comment).
    """
    permission_classes = [IsStaffOrAdmin]
    serializer_class = StaffReviewSerializer
    pagination_class = StaffReviewPagination

    def get_queryset(self):
        qs = Review.objects.select_related("user", "product", "order_item__order")
        p = self.request.query_params

        rating = p.get("rating")
        if rating and rating.isdigit() and 1 <= int(rating) <= 5:
            qs = qs.filter(rating=int(rating))
        if p.get("product"):
            try:
                qs = qs.filter(product_id=uuid.UUID(p["product"]))
            except ValueError:
                return qs.none()
        verified = (p.get("verified") or "").lower()
        if verified in ("true", "1"):
            qs = qs.filter(order_item__isnull=False)
        elif verified in ("false", "0"):
            qs = qs.filter(order_item__isnull=True)

        term = (p.get("q") or "").strip()
        if term:
            qs = qs.filter(
                Q(product__name__icontains=term) | Q(product__sku__icontains=term)
                | Q(user__email__icontains=term) | Q(user__first_name__icontains=term)
                | Q(user__last_name__icontains=term) | Q(comment__icontains=term)
            )
        return qs.order_by("-created_at")

    def paginate_queryset(self, queryset):
        agg = queryset.aggregate(total=Count("id"), average=Avg("rating"))
        breakdown = {str(i): 0 for i in range(1, 6)}
        for row in queryset.order_by().values("rating").annotate(n=Count("id")):
            breakdown[str(row["rating"])] = row["n"]
        self.paginator.summary = {
            "total": agg["total"],
            "average_rating": round(agg["average"], 2) if agg["average"] is not None else None,
            "breakdown": breakdown,
        }
        return super().paginate_queryset(queryset)