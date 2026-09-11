from django.contrib import admin
from .models import VehicleMake, VehicleModel, VehicleYear, Fitment


class VehicleModelInline(admin.TabularInline):
    model = VehicleModel
    extra = 1
    prepopulated_fields = {"slug": ("name",)}


@admin.register(VehicleMake)
class VehicleMakeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [VehicleModelInline]


class VehicleYearInline(admin.TabularInline):
    model = VehicleYear
    extra = 1


@admin.register(VehicleModel)
class VehicleModelAdmin(admin.ModelAdmin):
    list_display = ("name", "make", "slug", "is_active")
    list_filter = ("make",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [VehicleYearInline]


@admin.register(VehicleYear)
class VehicleYearAdmin(admin.ModelAdmin):
    list_display = ("model", "year")
    list_filter = ("model__make",)
    search_fields = ("model__name", "model__make__name")


@admin.register(Fitment)
class FitmentAdmin(admin.ModelAdmin):
    list_display = ("product", "vehicle_year", "notes")
    search_fields = ("product__name", "product__sku")
    autocomplete_fields = ["product", "vehicle_year"]
