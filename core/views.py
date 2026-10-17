from decimal import Decimal

from django.db.models import Sum, Count
from django.db.models.functions import ExtractMonth, ExtractYear
from django.shortcuts import get_object_or_404
from django.utils import timezone
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

# Orders that count towards revenue. Shared by the headline metrics and the
# revenue analytics so the two can never disagree with each other.
REVENUE_STATUSES = [
    Order.Status.CONFIRMED,
    Order.Status.PROCESSING,
    Order.Status.IN_TRANSIT,
    Order.Status.DELIVERED,
]

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _money(value):
    """Decimal/None -> float rounded to 2dp, so charts get real JSON numbers."""
    return float(Decimal(value or 0).quantize(Decimal("0.01")))


def _pct_change(current, previous):
    """Percentage change vs a previous period; None when there is no baseline."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


class AdminMetricsView(views.APIView):
    permission_classes = [IsStaffOrAdmin]

    def get(self, request):
        orders_by_status = dict(
            Order.objects.values_list("status").annotate(count=Count("id")).order_by()
        )
        revenue = Order.objects.filter(status__in=REVENUE_STATUSES).aggregate(total=Sum("total"))["total"] or 0

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


class RevenueAnalyticsView(views.APIView):
    permission_classes = [IsStaffOrAdmin]

    def get(self, request):
        now = timezone.localtime()
        current_year, current_month = now.year, now.month

        raw_year = request.query_params.get("year")
        if raw_year in (None, ""):
            year = current_year
        else:
            try:
                year = int(raw_year)
            except (TypeError, ValueError):
                return Response({"detail": "year must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
            if not 2000 <= year <= 2100:
                return Response({"detail": "year is out of range."}, status=status.HTTP_400_BAD_REQUEST)

        # One grouped query feeds every number below.
        rows = (
            Order.objects.filter(status__in=REVENUE_STATUSES)
            .annotate(y=ExtractYear("created_at"), m=ExtractMonth("created_at"))
            .values("y", "m")
            .annotate(revenue=Sum("total"), orders=Count("id"))
            .order_by("y", "m")
        )
        by_month = {(r["y"], r["m"]): (r["revenue"] or Decimal("0"), r["orders"]) for r in rows}

        def month_totals(y, m):
            return by_month.get((y, m), (Decimal("0"), 0))

        def year_totals(y):
            revenue = sum((v[0] for (yy, _), v in by_month.items() if yy == y), Decimal("0"))
            orders = sum(v[1] for (yy, _), v in by_month.items() if yy == y)
            return revenue, orders

        # Monthly series for the selected year
        monthly = []
        for m in range(1, 13):
            revenue, orders = month_totals(year, m)
            monthly.append({
                "month": m,
                "label": MONTH_LABELS[m - 1],
                "revenue": _money(revenue),
                "orders": orders,
                "is_future": (year, m) > (current_year, current_month),
            })

        # Yearly series: first year with orders -> latest of (last order year, this year), gaps zero-filled
        years_with_data = sorted({y for (y, _) in by_month})
        first_year = years_with_data[0] if years_with_data else current_year
        last_year = max(years_with_data[-1] if years_with_data else current_year, current_year)
        yearly = []
        for y in range(first_year, last_year + 1):
            revenue, orders = year_totals(y)
            yearly.append({"year": y, "revenue": _money(revenue), "orders": orders})

        available_years = sorted(set(years_with_data) | {current_year, year}, reverse=True)

        # Headline comparisons
        year_revenue, year_orders = year_totals(year)
        prev_year_revenue, _ = year_totals(year - 1)

        prev_month_year, prev_month = (current_year, current_month - 1) if current_month > 1 else (current_year - 1, 12)
        this_month_revenue, this_month_orders = month_totals(current_year, current_month)
        last_month_revenue, _ = month_totals(prev_month_year, prev_month)

        best = max(monthly, key=lambda item: item["revenue"])
        best_month = {"label": best["label"], "revenue": best["revenue"]} if best["revenue"] > 0 else None

        return Response({
            "year": year,
            "current_year": current_year,
            "available_years": available_years,
            "monthly": monthly,
            "yearly": yearly,
            "summary": {
                "year_revenue": _money(year_revenue),
                "year_orders": year_orders,
                "previous_year_revenue": _money(prev_year_revenue),
                "yoy_change_pct": _pct_change(year_revenue, prev_year_revenue),
                "avg_order_value": _money(year_revenue / year_orders) if year_orders else 0.0,
                "best_month": best_month,
                "this_month_revenue": _money(this_month_revenue),
                "this_month_orders": this_month_orders,
                "last_month_revenue": _money(last_month_revenue),
                "mom_change_pct": _pct_change(this_month_revenue, last_month_revenue),
            },
        })