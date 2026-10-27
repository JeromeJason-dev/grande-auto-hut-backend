import logging
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from inventory.services import adjust_stock, InsufficientStockError
from inventory.models import InventoryTransaction
from .models import Cart, CartItem, Order, OrderItem, OrderStatusHistory

logger = logging.getLogger(__name__)


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


def _reservation_deadline(minutes=None):
    return timezone.now() + timedelta(minutes=minutes or settings.STOCK_RESERVATION_MINUTES)


def checkout(cart: Cart, user, address_data: dict, payment_method: str) -> Order:
    # Free expired holds first, outside the checkout transaction (no gateway calls here).
    expire_stale_reservations(check_gateway=False)
    return _checkout(cart, user, address_data, payment_method)


@transaction.atomic
def _checkout(cart: Cart, user, address_data: dict, payment_method: str) -> Order:
    from catalog.models import Product

    items = list(cart.items.select_related("product").select_for_update(of=("self",)))
    if not items:
        raise CheckoutError("Cart is empty.")

    # Lock every product row we're about to touch, lowest id first.
    product_ids = sorted({item.product_id for item in items})
    locked = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk")}

    wanted = {}
    for item in items:
        wanted[item.product_id] = wanted.get(item.product_id, 0) + item.quantity
    for item in items:
        product = locked[item.product_id]
        if not product.is_active:
            raise CheckoutError(f"'{product.name}' is no longer available.")
        if product.stock_quantity < wanted[item.product_id]:
            raise CheckoutError(
                f"Only {product.stock_quantity} of '{product.name}' left in stock."
            )

    subtotal = sum((locked[item.product_id].price * item.quantity for item in items), Decimal("0.00"))
    shipping_fee = Decimal("0.00")  # flat/free for now - hook a rate table in here later
    total = subtotal + shipping_fee

    is_cod = payment_method == Order.PaymentMethod.COD
    order = Order.objects.create(
        user=user,
        payment_method=payment_method,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=total,
        reservation_expires_at=None if is_cod else _reservation_deadline(),
        **address_data,
    )
    OrderItem.objects.bulk_create([
        OrderItem(
            order=order,
            product=locked[item.product_id],
            product_name=locked[item.product_id].name,
            product_sku=locked[item.product_id].sku,
            unit_price=locked[item.product_id].price,
            quantity=item.quantity,
        )
        for item in items
    ])
    _reserve_stock(order, user=user)
    _record_history(order, Order.Status.PENDING, user=user, note="Order placed.")

    cart.items.all().delete()

    if is_cod:
        confirm_order(order, user=user, note="Auto-confirmed: Pay on Delivery.")

    return order


def _reserve_stock(order: Order, user=None):
    """Deducts every line of the order from stock (caller holds the transaction)."""
    for item in order.items.order_by("product_id"):
        try:
            adjust_stock(
                product_id=item.product_id,
                delta=-item.quantity,
                transaction_type=InventoryTransaction.TransactionType.ORDER_RESERVE,
                order=order,
                note=f"Order {order.order_number} (reserved)",
                user=user,
            )
        except InsufficientStockError as exc:
            raise CheckoutError(str(exc)) from exc
    order.stock_reserved = True
    order.save(update_fields=["stock_reserved", "updated_at"])


def _release_stock(order: Order, user=None, note=""):
    """Gives a reserved order's stock back (caller holds the transaction)."""
    if not order.stock_reserved:
        return
    for item in order.items.order_by("product_id"):
        adjust_stock(
            product_id=item.product_id,
            delta=item.quantity,
            transaction_type=InventoryTransaction.TransactionType.ORDER_CANCELLED_RESTOCK,
            order=order,
            note=note or f"Order {order.order_number} cancelled",
            user=user,
        )
    order.stock_reserved = False
    order.save(update_fields=["stock_reserved", "updated_at"])


def extend_reservation(order: Order, minutes=None):
    if not order.stock_reserved or order.status != Order.Status.PENDING or order.reservation_expires_at is None:
        return order
    minutes = minutes or settings.STOCK_RESERVATION_PAYMENT_GRACE_MINUTES
    new_deadline = _reservation_deadline(minutes)
    if new_deadline > order.reservation_expires_at:
        order.reservation_expires_at = new_deadline
        order.save(update_fields=["reservation_expires_at", "updated_at"])
    return order


EXPIRY_NOTE = "Cancelled automatically: payment was not completed in time, stock released."


def expire_stale_reservations(now=None, check_gateway=True) -> int:
    from payments.services import settle_gateway_payments

    now = now or timezone.now()
    candidates = list(
        Order.objects.filter(
            status=Order.Status.PENDING, stock_reserved=True, reservation_expires_at__lt=now,
        ).exclude(payment_method=Order.PaymentMethod.COD).values_list("pk", flat=True)[:200]
    )
    cancelled = 0
    for pk in candidates:
        order = Order.objects.get(pk=pk)
        if check_gateway:
            try:
                settle_gateway_payments(order)  # may confirm the order if it was actually paid
            except Exception:  # a gateway outage must never block the sweep
                logger.exception("Gateway check failed while expiring order %s", order.order_number)
        elif order.payments.filter(status="pending").exists():
            continue
        with transaction.atomic():
            locked = _lock_order(order)
            if locked.status != Order.Status.PENDING or not locked.stock_reserved:
                continue  # confirmed/cancelled in the meantime
            if locked.payments.filter(status="success").exists():
                continue  # paid; confirmation is in flight
            if locked.reservation_expires_at and locked.reservation_expires_at >= timezone.now():
                continue  # extended by a new payment attempt
            locked.cancelled_by_expiry = True
            locked.save(update_fields=["cancelled_by_expiry", "updated_at"])
            cancel_order(locked, note=EXPIRY_NOTE)
            cancelled += 1
    return cancelled


class StockUnavailableError(CheckoutError):
    """A paid order can no longer be fulfilled because its stock is gone."""


@transaction.atomic
def reinstate_expired_order(order: Order) -> Order:
    order = _lock_order(order)
    if order.status != Order.Status.CANCELLED or not order.cancelled_by_expiry:
        raise InvalidTransitionError("Only orders cancelled by expiry can be reinstated.")
    sid = transaction.savepoint()
    try:
        _reserve_stock(order)
    except CheckoutError as exc:
        transaction.savepoint_rollback(sid)
        raise StockUnavailableError(str(exc)) from exc
    order.status = Order.Status.PENDING
    order.cancelled_by_expiry = False
    order.reservation_expires_at = None
    order.save(update_fields=["status", "cancelled_by_expiry", "reservation_expires_at", "updated_at"])
    _record_history(order, Order.Status.PENDING, note="Reinstated: payment arrived just after the hold expired.")
    return order


def flag_paid_order_needs_attention(order: Order, reason: str):
    note = (reason or "Paid but could not be confirmed.")[:255]
    Order.objects.filter(pk=order.pk).update(attention_note=note)
    logger.error("ATTENTION order %s: %s", order.order_number, note)

    from accounts.models import User
    from django.core.mail import send_mail
    from notifications.services import notify

    title = f"Paid order needs attention: {order.order_number}"
    message = (
        f"Order {order.order_number} has been paid but could not be confirmed automatically: {note} "
        f"Please contact the customer and either restock and confirm it, or refund the payment."
    )
    for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
        try:
            notify(admin, "order_update", title, message, send_email=False, link=f"/admin/orders")
        except Exception:
            logger.exception("Could not create admin alert for order %s", order.order_number)

    recipients = list(settings.ADMIN_ALERT_EMAILS) or list(
        User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(email="").values_list("email", flat=True)
    )
    if recipients:
        try:
            send_mail(title, message, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
        except Exception:
            logger.exception("Could not email admin alert for order %s", order.order_number)


DEFAULT_CANCEL_NOTE = "Order cancelled."


def _lock_order(order: Order) -> Order:
    return Order.objects.select_for_update(of=("self",)).get(pk=order.pk)


def assert_valid_transition(order: Order, new_status: str):
    allowed = Order.TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot move order from '{order.status}' to '{new_status}'."
        )


@transaction.atomic
def confirm_order(order: Order, user=None, note="Order confirmed.") -> Order:
    order = _lock_order(order)
    assert_valid_transition(order, Order.Status.CONFIRMED)
    # Orders placed through checkout already hold their stock. Only legacy orders
    # (placed before reservations existed) still need it deducted here.
    if not order.stock_reserved:
        _reserve_stock(order, user=user)

    order.status = Order.Status.CONFIRMED
    order.reservation_expires_at = None
    order.attention_note = ""
    order.save(update_fields=["status", "reservation_expires_at", "attention_note", "updated_at"])
    _record_history(order, Order.Status.CONFIRMED, user=user, note=note)

    from notifications.services import notify
    notify(
        order.user, "order_update", f"Order {order.order_number} confirmed",
        f"Your order {order.order_number} has been confirmed and is being prepared.",
    )
    return order


@transaction.atomic
def cancel_order(order: Order, user=None, note=DEFAULT_CANCEL_NOTE) -> Order:
    from payments.models import Payment

    order = _lock_order(order)
    assert_valid_transition(order, Order.Status.CANCELLED)

    order.status = Order.Status.CANCELLED
    order.reservation_expires_at = None
    order.save(update_fields=["status", "reservation_expires_at", "updated_at"])
    _record_history(order, Order.Status.CANCELLED, user=user, note=note)

    # A cancelled order can't still be awaiting payment. Without this a pending
    # M-Pesa attempt would sit in the dashboard's "Pending M-Pesa" count forever.
    order.payments.filter(status=Payment.Status.PENDING).update(
        status=Payment.Status.FAILED, updated_at=timezone.now()
    )

    # Gives the stock back only if this order is actually holding it.
    _release_stock(order, user=user)

    # The default note is just the history label; only a real reason goes to the customer.
    message = f"Your order {order.order_number} has been cancelled."
    if note and note != DEFAULT_CANCEL_NOTE:
        message += f" Reason: {note}"

    from notifications.services import notify
    notify(order.user, "order_update", f"Order {order.order_number} cancelled", message)
    return order


@transaction.atomic
def update_status(order: Order, new_status: str, user=None, note="") -> Order:
    order = _lock_order(order)

    # 1. Handle specialized target states that require separate business flows or custom logic
    if new_status == Order.Status.CONFIRMED:
        return confirm_order(order, user=user, note=note or "Order confirmed.")

    if new_status == Order.Status.CANCELLED:
        return cancel_order(order, user=user, note=note or DEFAULT_CANCEL_NOTE)

    # 2. Enforce structural state machine validation first (prevents illegal jumps)
    assert_valid_transition(order, new_status)

    # 3. Safety net: anything leaving PENDING must be holding its stock.
    if order.status == Order.Status.PENDING and not order.stock_reserved:
        _reserve_stock(order, user=user)

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