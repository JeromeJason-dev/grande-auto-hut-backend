import uuid
from django.db import models


class VehicleMake(models.Model):
    """e.g. Toyota, Nissan, Subaru, Mazda"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class VehicleModel(models.Model):
    """e.g. Hilux, X-Trail, Forester - scoped to a make."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    make = models.ForeignKey(VehicleMake, related_name="models", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("make", "slug")

    def __str__(self):
        return f"{self.make.name} {self.name}"


class VehicleYear(models.Model):
    """A single model-year, scoped to a model. This is the leaf node the
    Fitment Finder resolves down to before it looks up compatible products."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model = models.ForeignKey(VehicleModel, related_name="years", on_delete=models.CASCADE)
    year = models.PositiveIntegerField()

    class Meta:
        ordering = ["-year"]
        unique_together = ("model", "year")

    def __str__(self):
        return f"{self.model} {self.year}"


class Fitment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey("catalog.Product", related_name="fitments", on_delete=models.CASCADE)
    vehicle_year = models.ForeignKey(VehicleYear, related_name="fitments", on_delete=models.CASCADE)
    notes = models.CharField(max_length=255, blank=True, help_text="e.g. 'Front only', 'Requires bracket kit'")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("product", "vehicle_year")

    def __str__(self):
        return f"{self.product.sku} fits {self.vehicle_year}"
