import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Review(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("accounts.User", related_name="reviews", on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", related_name="reviews", on_delete=models.CASCADE)
    order_item = models.ForeignKey(
        "orders.OrderItem", null=True, blank=True, related_name="review",
        on_delete=models.SET_NULL, help_text="The delivered order line this review is based on (verified purchase).",
    )
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("user", "product")

    def __str__(self):
        return f"{self.user.email} rated {self.product.sku}: {self.rating}/5"
