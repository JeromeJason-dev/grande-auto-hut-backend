from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Address


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "username", "role", "is_email_verified", "is_active", "created_at")
    list_filter = ("role", "is_active", "is_email_verified")
    search_fields = ("email", "username", "first_name", "last_name", "phone_number")
    ordering = ("-created_at",)
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Grande Auto Hut", {"fields": ("role", "phone_number", "is_email_verified")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Grande Auto Hut", {"fields": ("email", "role", "phone_number")}),
    )


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("recipient_name", "user", "town", "county", "is_default")
    list_filter = ("county", "is_default")
    search_fields = ("recipient_name", "user__email", "phone_number")
