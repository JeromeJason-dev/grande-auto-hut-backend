from rest_framework import generics, views, permissions, status
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from accounts.permissions import IsStaffOrAdmin
from .models import InventoryTransaction
from .serializers import InventoryTransactionSerializer, RestockSerializer
from .services import adjust_stock


class InventoryTransactionListView(generics.ListAPIView):
    queryset = InventoryTransaction.objects.select_related("product", "order", "created_by")
    serializer_class = InventoryTransactionSerializer
    permission_classes = [IsStaffOrAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["product", "transaction_type"]


class RestockView(views.APIView):
    permission_classes = [IsStaffOrAdmin]

    def post(self, request):
        serializer = RestockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product = adjust_stock(
            product_id=data["product"],
            delta=data["quantity"],
            transaction_type=InventoryTransaction.TransactionType.RESTOCK,
            note=data["note"],
            user=request.user,
        )
        return Response(
            {"product": str(product.id), "new_stock_quantity": product.stock_quantity},
            status=status.HTTP_200_OK,
        )
