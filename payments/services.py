import json
import urllib.error
import urllib.request
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from cart.models import Cart
from orders.models import Order
from orders.services import confirm_order_payment
from products.models import KardexMovement

from .models import PaymentTransaction, SalesReceipt


def _reservation_minutes():
    return int(getattr(settings, "STOCK_RESERVATION_MINUTES", 15))


def release_order_stock_reservation(order, payment=None):
    if order.stock_reservation_status != Order.StockReservationStatus.RESERVED:
        return order
    for item in order.items.select_related("product"):
        product = item.product

        if product.product_type == product.ProductType.BUNDLE and product.bundle_items.exists():
            for bundle_item in product.bundle_items.select_related("item"):
                component = bundle_item.item
                component_qty = bundle_item.quantity * item.quantity
                component.stock_reserved = max((component.stock_reserved or 0) - component_qty, 0)
                component.save(update_fields=["stock_reserved", "updated_at"])
        else:
            product.stock_reserved = max((product.stock_reserved or 0) - item.quantity, 0)
            product.save(update_fields=["stock_reserved", "updated_at"])
    now = timezone.now()
    order.stock_reservation_status = Order.StockReservationStatus.RELEASED
    order.stock_released_at = now
    order.stock_reservation_expires_at = None
    order.save(update_fields=["stock_reservation_status", "stock_released_at", "stock_reservation_expires_at", "updated_at"])
    if payment:
        payment.stock_released_at = now
        payment.save(update_fields=["stock_released_at", "updated_at"])
    return order


def _webpay_base_url():
    return 'https://webpay3gint.transbank.cl' if settings.WEBPAY_ENVIRONMENT == 'integration' else 'https://webpay3g.transbank.cl'


def _headers():
    return {
        'Tbk-Api-Key-Id': settings.WEBPAY_COMMERCE_CODE,
        'Tbk-Api-Key-Secret': settings.WEBPAY_API_KEY_SECRET,
        'Content-Type': 'application/json',
    }


def _request(path, payload=None, method='POST'):
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f"{_webpay_base_url()}{path}",
        data=body,
        headers=_headers(),
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore') if hasattr(exc, 'read') else ''
        details = body or str(exc)
        if exc.code == 401:
            message = (
                f'Webpay rechazó la solicitud (401). Posible problema de credenciales para el ambiente '
                f'"{settings.WEBPAY_ENVIRONMENT}".'
            )
        elif exc.code == 405:
            message = 'Webpay rechazó la solicitud (405). Método HTTP o endpoint de commit incorrecto.'
        elif exc.code in (404, 422):
            message = 'Webpay rechazó la solicitud. El token es inválido, expiró o ya fue confirmado.'
        else:
            message = f'Webpay rechazó la solicitud ({exc.code}).'
        raise ValidationError(f'{message} Detalle técnico: {details}') from exc
    except urllib.error.URLError as exc:
        raise ValidationError(f'No fue posible conectar con Webpay: {exc.reason}') from exc


def validate_order_for_webpay_start(order):
    payable_statuses = {Order.Status.PENDING_PAYMENT, Order.Status.PAYMENT_FAILED}
    if order.status not in payable_statuses:
        raise ValidationError('Solo se pueden pagar órdenes pendientes o con pago fallido.')


def validate_order_for_webpay_commit(order):
    confirmable_statuses = {Order.Status.PAYMENT_STARTED, Order.Status.PENDING_PAYMENT, Order.Status.PAYMENT_FAILED}
    if order.status not in confirmable_statuses:
        raise ValidationError('La orden no está en un estado válido para confirmar este pago.')


def create_webpay_transaction(order, user):
    if order.user_id != user.id:
        raise ValidationError('No autorizado para pagar esta orden.')
    validate_order_for_webpay_start(order)
    if order.total_clp <= 0:
        raise ValidationError('La orden no tiene monto válido.')

    buy_order = f'ORDER-{order.id}-{timezone.now().strftime("%Y%m%d%H%M%S")}'
    session_id = f'user-{user.id}-order-{order.id}'
    payload = {
        'buy_order': buy_order,
        'session_id': session_id,
        'amount': int(order.total_clp),
        'return_url': settings.WEBPAY_RETURN_URL,
    }
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        expires_at = timezone.now() + timedelta(minutes=_reservation_minutes())
        if not order.stock_reservation_is_active:
            for item in order.items.select_related('product'):
                product = item.product
                if product.product_type == product.ProductType.BUNDLE:
                    bundle_items = list(
                        product.bundle_items.select_related('item')
                    )
                    if bundle_items:
                        for bundle_item in bundle_items:
                            component = type(product).objects.select_for_update().get(pk=bundle_item.item_id)
                            component_qty = bundle_item.quantity * item.quantity
                            if component.available_stock < component_qty:
                                raise ValidationError(
                                    f"Stock insuficiente para '{component.name}' "
                                    f"(componente de '{product.name}'). "
                                    f'Disponible: {component.available_stock}, requerido: {component_qty}.'
                                )
                            component.stock_reserved = F('stock_reserved') + component_qty
                            component.save(update_fields=['stock_reserved', 'updated_at'])
                    else:
                        locked_product = type(product).objects.select_for_update().get(pk=product.pk)
                        if locked_product.available_stock < item.quantity:
                            raise ValidationError(
                                f'Stock insuficiente. Disponible actualmente: {locked_product.available_stock}.'
                            )
                        locked_product.stock_reserved = F('stock_reserved') + item.quantity
                        locked_product.save(update_fields=['stock_reserved', 'updated_at'])
                else:
                    locked_product = type(product).objects.select_for_update().get(pk=product.pk)
                    if locked_product.available_stock < item.quantity:
                        raise ValidationError(f'Stock insuficiente. Disponible actualmente: {locked_product.available_stock}.')
                    locked_product.stock_reserved = F('stock_reserved') + item.quantity
                    locked_product.save(update_fields=['stock_reserved', 'updated_at'])
            order.stock_reserved_at = timezone.now()
            order.stock_reservation_expires_at = expires_at
            order.stock_reservation_status = Order.StockReservationStatus.RESERVED
            order.status = Order.Status.PAYMENT_STARTED
            order.save(update_fields=['status', 'stock_reserved_at', 'stock_reservation_expires_at', 'stock_reservation_status', 'updated_at'])

        response = _request('/rswebpaytransaction/api/webpay/v1.2/transactions', payload, method='POST')

        payment = PaymentTransaction.objects.create(
        order=order,
        user=user,
        status=PaymentTransaction.Status.PENDING,
        amount_clp=order.total_clp,
        buy_order=buy_order,
        session_id=session_id,
        token=response['token'],
        raw_request=payload,
        raw_response=response,
        stock_reserved_at=order.stock_reserved_at,
        stock_reservation_expires_at=order.stock_reservation_expires_at,
    )
    return payment, response


def commit_webpay_transaction(token):
    return _request(
        f'/rswebpaytransaction/api/webpay/v1.2/transactions/{token}',
        payload=None,
        method='PUT',
    )


@transaction.atomic
def finalize_paid_order(order, payment):
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status == Order.Status.PAID:
        return locked
    if payment.status != PaymentTransaction.Status.AUTHORIZED:
        raise ValidationError('Transacción no autorizada.')
    if KardexMovement.objects.filter(reference_type='ORDER', reference_id=locked.id, movement_type=KardexMovement.MovementType.SALE_OUT).exists():
        locked.status = Order.Status.PAID
        locked.stock_consumed = True
        locked.stock_reservation_status = Order.StockReservationStatus.CONSUMED
        locked.save(update_fields=['status', 'stock_consumed', 'stock_reservation_status', 'updated_at'])
        return locked

    release_order_stock_reservation(locked)

    confirm_order_payment(locked, user=payment.user, allow_awaiting_payment=True)
    locked.stock_reservation_status = Order.StockReservationStatus.CONSUMED
    locked.stock_released_at = timezone.now()
    locked.stock_reservation_expires_at = None
    locked.save(update_fields=["stock_reservation_status", "stock_released_at", "stock_reservation_expires_at", "updated_at"])
    payment.stock_released_at = timezone.now()
    payment.save(update_fields=["stock_released_at", "updated_at"])

    total = locked.total_clp
    tax_rate = Decimal(str(settings.TAX_RATE))
    net = int((Decimal(total) / (1 + tax_rate)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    tax = total - net
    SalesReceipt.objects.get_or_create(
        order=locked,
        payment_transaction=payment,
        defaults={
            'document_number': f'INT-{locked.id}-{payment.id}',
            'net_amount_clp': net,
            'tax_amount_clp': tax,
            'total_amount_clp': total,
            'raw_data': {'tax_rate': float(tax_rate)},
        }
    )
    payment.accounting_status = PaymentTransaction.AccountingStatus.REGISTERED
    payment.save(update_fields=['accounting_status', 'updated_at'])
    try:
        cart = Cart.objects.get(user=locked.user)
        cart.items.all().delete()
    except Cart.DoesNotExist:
        pass
    return locked
