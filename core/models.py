import uuid
from django.db import models


class Wishlist(models.Model):
    """Simple saved-items table - one row per (user, product)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("accounts.User", related_name="wishlist_items", on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", related_name="wishlisted_by", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("user", "product")

    def __str__(self):
        return f"{self.user.email} wants {self.product.sku}"
