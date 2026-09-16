from decimal import Decimal
from django.db import transaction
from inventory.services import adjust_stock, InsufficientStockError
from inventory.models import InventoryTransaction
from .models import Cart, CartItem, Order, OrderItem, OrderStatusHistory


class CheckoutError(Exception):
    """Raised for any checkout-time validation failure (empty cart, out of stock, etc.)."""


class InvalidTransitionError(Exception):
    """Raised when a status change isn't legal from the order's current status."""


def get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def merge_guest_cart_into_user_cart(session_key, user):
    if not session_key:
        return
    guest_cart = Cart.objects.filter(session_key=session_key, user__isnull=True).first()
    if not guest_cart:
        return
    user_cart = get_or_create_cart(user)
    with transaction.atomic():
        for item in guest_cart.items.select_related("product"):
            existing = user_cart.items.filter(product=item.product).first()
            if existing:
                existing.quantity += item.quantity
                existing.save(update_fields=["quantity"])
            else:
                item.cart = user_cart
                item.save(update_fields=["cart"])
        guest_cart.delete()


def _record_history(order, status, user=None, note=""):
    OrderStatusHistory.objects.create(order=order, status=status, changed_by=user, note=note)


@transaction.atomic
def checkout(cart: Cart, user, address_data: dict, payment_method: str) -> Order:
    items = list(cart.items.select_related("product").select_for_update(of=("self",)))
    if not items:
        raise CheckoutError("Cart is empty.")

    for item in items:
        if not item.product.is_active:
            raise CheckoutError(f"'{item.product.name}' is no longer available.")
        if item.product.stock_quantity < item.quantity:
            raise CheckoutError(
                f"Only {item.product.stock_quantity} of '{item.product.name}' left in stock."
            )

    subtotal = sum((item.product.price * item.quantity for item in items), Decimal("0.00"))
    shipping_fee = Decimal("0.00")  # flat/free for now - hook a rate table in here later
    total = subtotal + shipping_fee

    order = Order.objects.create(
        user=user,
        payment_method=payment_method,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=total,
        **address_data,
    )
    OrderItem.objects.bulk_create([
        OrderItem(
            order=order,
            product=item.product,
            product_name=item.product.name,
            product_sku=item.product.sku,
            unit_price=item.product.price,
            quantity=item.quantity,
        )
        for item in items
    ])
    _record_history(order, Order.Status.PENDING, user=user, note="Order placed.")

    cart.items.all().delete()

    if payment_method == Order.PaymentMethod.COD:
        confirm_order(order, user=user, note="Auto-confirmed: Pay on Delivery.")

    return order


def assert_valid_transition(order: Order, new_status: str):
    allowed = Order.TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot move order from '{order.status}' to '{new_status}'."
        )


@transaction.atomic
def confirm_order(order: Order, user=None, note="Order confirmed.") -> Order:
    assert_valid_transition(order, Order.Status.CONFIRMED)
    for item in order.items.select_related("product"):
        try:
            adjust_stock(
                product_id=item.product_id,
                delta=-item.quantity,
                transaction_type=InventoryTransaction.TransactionType.ORDER_CONFIRM,
                order=order,
                note=f"Order {order.order_number}",
                user=user,
            )
        except InsufficientStockError as exc:
            raise CheckoutError(str(exc)) from exc

    order.status = Order.Status.CONFIRMED
    order.save(update_fields=["status", "updated_at"])
    _record_history(order, Order.Status.CONFIRMED, user=user, note=note)

    from notifications.services import notify
    notify(
        order.user, "order_update", f"Order {order.order_number} confirmed",
        f"Your order {order.order_number} has been confirmed and is being prepared.",
    )
    return order


@transaction.atomic
def cancel_order(order: Order, user=None, note="Order cancelled.") -> Order:
    assert_valid_transition(order, Order.Status.CANCELLED)
    was_stock_reserved = order.status in (
        Order.Status.CONFIRMED, 
        Order.Status.PROCESSING, 
        Order.Status.SHIPPED, 
        Order.Status.DELIVERED,
        Order.Status.IN_TRANSIT
    )

    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    _record_history(order, Order.Status.CANCELLED, user=user, note=note)

    from notifications.services import notify
    notify(
        order.user, "order_update", f"Order {order.order_number} cancelled",
        note or f"Your order {order.order_number} has been cancelled.",
    )

    if was_stock_reserved:
        for item in order.items.select_related("product"):
            adjust_stock(
                product_id=item.product_id,
                delta=item.quantity,
                transaction_type=InventoryTransaction.TransactionType.ORDER_CANCELLED_RESTOCK,
                order=order,
                note=f"Order {order.order_number} cancelled",
                user=user,
            )
    return order


@transaction.atomic
def update_status(order: Order, new_status: str, user=None, note="") -> Order:
    # 1. Handle specialized target states that require separate business flows or custom logic
    if new_status == Order.Status.CONFIRMED:
        return confirm_order(order, user=user, note=note or "Order confirmed.")
    
    if new_status == Order.Status.CANCELLED:
        return cancel_order(order, user=user, note=note or "Order cancelled.")

    # 2. Enforce structural state machine validation first (prevents illegal jumps)
    assert_valid_transition(order, new_status)

    # 3. Handle intermediate stock deduction if moving out of pending directly into processing 
    if order.status == Order.Status.PENDING and new_status == Order.Status.PROCESSING:
        for item in order.items.select_related("product"):
            try:
                adjust_stock(
                    product_id=item.product_id,
                    delta=-item.quantity,
                    transaction_type=InventoryTransaction.TransactionType.ORDER_CONFIRM,
                    order=order,
                    note=f"Order {order.order_number}",
                    user=user,
                )
            except InsufficientStockError as exc:
                raise CheckoutError(str(exc)) from exc

    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    _record_history(order, new_status, user=user, note=note)

    from notifications.services import notify
    status_label = dict(Order.Status.choices).get(new_status, new_status)
    notify(
        order.user, "order_update", f"Order {order.order_number}: {status_label}",
        note or f"Your order {order.order_number} is now '{status_label}'.",
    )
    return order