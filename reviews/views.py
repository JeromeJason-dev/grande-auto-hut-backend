from rest_framework import generics, permissions
from .models import Review
from .serializers import ReviewSerializer, ReviewWriteSerializer


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
