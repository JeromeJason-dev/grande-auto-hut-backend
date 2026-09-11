from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, views, status
from rest_framework.response import Response

from accounts.permissions import IsStaffOrAdmin
from accounts.models import User
from catalog.models import Product
from orders.models import Order
from support.models import Ticket
from payments.models import Payment
from .models import Wishlist
from .serializers import WishlistItemSerializer, WishlistAddSerializer


# Wishlist
class WishlistListView(generics.ListAPIView):
    """GET /api/wishlist/"""
    serializer_class = WishlistItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Wishlist.objects.filter(user=self.request.user).select_related("product")


class WishlistAddView(views.APIView):
    """POST /api/wishlist/items/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = WishlistAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, _ = Wishlist.objects.get_or_create(user=request.user, product=serializer.validated_data["product"])
        return Response(WishlistItemSerializer(item).data, status=status.HTTP_201_CREATED)


class WishlistRemoveView(views.APIView):
    """DELETE /api/wishlist/items/{product_id}/"""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, product_id):
        item = get_object_or_404(Wishlist, user=request.user, product_id=product_id)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# Admin dashboard metrics
class AdminMetricsView(views.APIView):
    """
    GET /api/admin/metrics/ - staff/admin only. A single-call summary for the
    admin dashboard landing page: order pipeline, revenue, stock health,
    open support load, and pending M-Pesa payments needing attention.
    """
    permission_classes = [IsStaffOrAdmin]

    def get(self, request):
        orders_by_status = dict(
            Order.objects.values_list("status").annotate(count=Count("id")).order_by()
        )
        revenue = Order.objects.filter(
            status__in=[Order.Status.CONFIRMED, Order.Status.PROCESSING, Order.Status.IN_TRANSIT, Order.Status.DELIVERED]
        ).aggregate(total=Sum("total"))["total"] or 0

        low_stock_qs = [
            p for p in Product.objects.filter(is_active=True).only("id", "name", "sku", "stock_quantity", "low_stock_threshold")
            if p.is_low_stock
        ]

        data = {
            "orders_by_status": orders_by_status,
            "total_orders": Order.objects.count(),
            "revenue_confirmed_and_beyond": revenue,
            "total_customers": User.objects.filter(role=User.Role.CUSTOMER).count(),
            "low_stock_count": len(low_stock_qs),
            "low_stock_products": [
                {"id": str(p.id), "name": p.name, "sku": p.sku, "stock_quantity": p.stock_quantity}
                for p in low_stock_qs[:20]
            ],
            "open_tickets": Ticket.objects.filter(status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS]).count(),
            "pending_mpesa_payments": Payment.objects.filter(method="mpesa", status=Payment.Status.PENDING).count(),
        }
        return Response(data)
