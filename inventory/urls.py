from django.urls import path
from .views import InventoryTransactionListView, RestockView

urlpatterns = [
    path("inventory/transactions/", InventoryTransactionListView.as_view(), name="inventory-transactions"),
    path("inventory/restock/", RestockView.as_view(), name="inventory-restock"),
]
