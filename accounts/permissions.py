from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdmin(BasePermission):
    """Admin role only."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin_role)


class IsStaffOrAdmin(BasePermission):
    """Staff and Admin roles. Used on product/order/ticket management endpoints."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff_role)


class IsOwnerOrStaff(BasePermission):
    """
    Object-level permission: the request.user must own the object (via `.user`
    attribute) or be staff/admin. Used for orders, addresses, tickets, reviews,
    wishlist - anywhere a customer must never see another customer's data.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff_role:
            return True
        owner = getattr(obj, "user", None)
        return owner == request.user


class ReadOnlyOrStaff(BasePermission):
    """Anyone authenticated can read (list/retrieve); only staff/admin can write."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_authenticated and request.user.is_staff_role)


class AllowAnyReadOnlyOrStaffWrite(BasePermission):
    """Public catalog browsing (no auth needed) but writes require staff/admin."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_staff_role)
