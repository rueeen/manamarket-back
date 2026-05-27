from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import is_admin_user, is_worker_user
from cart.models import Cart, get_product_sale_price_clp
from products.inventory_services import (
    consume_fifo_stock,
    create_stock_movement,
    return_fifo_stock,
)
from products.models import KardexMovement, Product
from .models import Order, OrderItem


def _validation_error_message(exc):
    if hasattr(exc, "message"):
        return exc.message

    if hasattr(exc, "messages"):
        return exc.messages

    return str(exc)


@transaction.atomic
def create_order_from_cart(user, **shipping_data):
    """
    Crea una orden desde el carrito.

    Importante:
    - Congela precios.
    - No descuenta stock.
    - No crea Kardex.
    - Mantiene el carrito hasta pago aprobado.
    """
    cart, _ = Cart.objects.select_for_update().get_or_create(user=user)

    items = list(
        cart.items.select_related("product")
    )

    if not items:
        raise ValidationError("Carrito vacío.")

    order = Order.objects.create(
        user=user,
        status=Order.Status.PENDING_PAYMENT,
        recipient_name=shipping_data.get("recipient_name", ""),
        recipient_phone=shipping_data.get("recipient_phone", ""),
        shipping_street=shipping_data.get("shipping_street", ""),
        shipping_number=shipping_data.get("shipping_number", ""),
        shipping_commune=shipping_data.get("shipping_commune", ""),
        shipping_region=shipping_data.get("shipping_region", ""),
        shipping_notes=shipping_data.get("shipping_notes", ""),
        shipping_clp=shipping_data.get("shipping_clp", 0),
    )

    subtotal = 0

    for item in items:
        product = Product.objects.select_for_update().get(pk=item.product_id)

        if not product.is_active:
            raise ValidationError(f"Producto inactivo: {product.name}")

        if product.product_type == Product.ProductType.BUNDLE:
            bundle_items = product.bundle_items.select_related("item").all()
            if bundle_items.exists():
                for bundle_item in bundle_items:
                    stock_needed = bundle_item.quantity * item.quantity
                    if bundle_item.item.available_stock < stock_needed:
                        raise ValidationError(
                            f"Stock insuficiente para '{bundle_item.item.name}' "
                            f"(componente de '{product.name}'). "
                            f"Disponible: {bundle_item.item.available_stock}, requerido: {stock_needed}."
                        )
            elif product.available_stock < item.quantity:
                raise ValidationError(f"Stock insuficiente para bundle {product.name}.")
        else:
            if product.available_stock < item.quantity:
                raise ValidationError(f"Stock insuficiente. Disponible actualmente: {product.available_stock}.")

        unit_price = int(get_product_sale_price_clp(product))

        if unit_price <= 0:
            raise ValidationError(
                f"Producto sin precio válido: {product.name}")

        line_subtotal = unit_price * item.quantity

        OrderItem.objects.create(
            order=order,
            product=product,
            product_name_snapshot=product.name,
            product_type_snapshot=product.product_type,
            quantity=item.quantity,
            unit_price_clp=unit_price,
            subtotal_clp=line_subtotal,
            unit_cost_clp=0,
            total_cost_clp=0,
            gross_profit_clp=0,
        )

        subtotal += line_subtotal

    order.subtotal_clp = subtotal
    order.total_clp = max(
        subtotal + order.shipping_clp - order.discount_clp,
        0,
    )
    order.save(update_fields=["subtotal_clp", "total_clp", "updated_at"])

    return order


@transaction.atomic
def confirm_order_payment(order: Order, user=None, allow_awaiting_payment=False):
    """
    Confirma una orden pagada.

    Aquí recién:
    - Se consume stock FIFO.
    - Se crea movimiento Kardex SALE_OUT.
    - Se calculan costos y utilidad.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)

    valid_statuses = {Order.Status.PENDING_PAYMENT, Order.Status.PAYMENT_FAILED}
    if allow_awaiting_payment:
        valid_statuses.add(Order.Status.PAYMENT_STARTED)

    if order.status not in valid_statuses:
        raise ValidationError("La orden no está en un estado válido para confirmar este pago.")

    if order.stock_consumed:
        raise ValidationError("El stock de esta orden ya fue consumido.")

    for item in order.items.select_related("product"):
        product = Product.objects.select_for_update().get(pk=item.product_id)

        if not product.is_active:
            raise ValidationError(f"Producto inactivo: {product.name}")

        if product.product_type == Product.ProductType.BUNDLE:
            bundle_items = list(
                product.bundle_items.select_related("item").all()
            )
            if not bundle_items:
                fifo_cost = consume_fifo_stock(product, item.quantity)
                total_cost_clp = int(fifo_cost["total_cost_clp"])
                unit_cost_clp = int(fifo_cost["unit_cost_clp"])
                gross_profit_clp = item.subtotal_clp - total_cost_clp

                create_stock_movement(
                    product=product,
                    movement_type=KardexMovement.MovementType.SALE_OUT,
                    quantity=item.quantity,
                    created_by=user,
                    unit_cost_clp=unit_cost_clp,
                    unit_price_clp=item.unit_price_clp,
                    reference_type="ORDER",
                    reference_id=order.id,
                    reference_label=f"Orden #{order.id}",
                    notes="Salida por venta confirmada (bundle sin componentes)",
                )
            else:
                total_bundle_cost = 0

                for bundle_item in bundle_items:
                    component = Product.objects.select_for_update().get(
                        pk=bundle_item.item_id
                    )
                    component_qty = bundle_item.quantity * item.quantity
    
                    fifo_cost = consume_fifo_stock(component, component_qty)
                    total_bundle_cost += int(fifo_cost["total_cost_clp"])
    
                    create_stock_movement(
                        product=component,
                        movement_type=KardexMovement.MovementType.SALE_OUT,
                        quantity=component_qty,
                        created_by=user,
                        unit_cost_clp=int(fifo_cost["unit_cost_clp"]),
                        unit_price_clp=0,
                        reference_type="ORDER",
                        reference_id=order.id,
                        reference_label=f"Orden #{order.id} (bundle: {product.name})",
                        notes=f"Salida por bundle '{product.name}' - venta confirmada",
                    )

                unit_cost_clp = int(round(total_bundle_cost / item.quantity)) if item.quantity else 0
                total_cost_clp = total_bundle_cost
                gross_profit_clp = item.subtotal_clp - total_cost_clp
        else:
            fifo_cost = consume_fifo_stock(product, item.quantity)
            total_cost_clp = int(fifo_cost["total_cost_clp"])
            unit_cost_clp = int(fifo_cost["unit_cost_clp"])
            gross_profit_clp = item.subtotal_clp - total_cost_clp

            create_stock_movement(
                product=product,
                movement_type=KardexMovement.MovementType.SALE_OUT,
                quantity=item.quantity,
                created_by=user,
                unit_cost_clp=unit_cost_clp,
                unit_price_clp=item.unit_price_clp,
                reference_type="ORDER",
                reference_id=order.id,
                reference_label=f"Orden #{order.id}",
                notes="Salida por venta confirmada",
            )

        item.unit_cost_clp = unit_cost_clp
        item.total_cost_clp = total_cost_clp
        item.gross_profit_clp = gross_profit_clp
        item.save(
            update_fields=[
                "unit_cost_clp",
                "total_cost_clp",
                "gross_profit_clp",
            ]
        )

    order.status = Order.Status.PAID
    order.stock_consumed = True
    order.paid_at = timezone.now()
    order.save(
        update_fields=[
            "status",
            "stock_consumed",
            "paid_at",
            "updated_at",
        ]
    )

    return order


@transaction.atomic
def cancel_order(order: Order, user=None, requesting_user=None):
    """
    Cancela una orden.

    Si la orden ya consumió stock, se genera RETURN_IN.
    Si estaba pendiente y nunca consumió stock, solo cambia estado.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)

    if order.stock_reservation_status == Order.StockReservationStatus.RESERVED:
        from payments.services import release_order_stock_reservation
        release_order_stock_reservation(order)

    if requesting_user is not None:
        is_owner = order.user_id == requesting_user.id
        is_staff_role = is_admin_user(requesting_user) or is_worker_user(requesting_user)

        if not is_owner and not is_staff_role:
            raise ValidationError("No autorizado para cancelar esta orden.")

    if order.status == Order.Status.CANCELED:
        return order

    if not order.can_be_canceled:
        raise ValidationError("Esta orden no puede ser cancelada.")

    if order.stock_consumed:
        for item in order.items.select_related("product"):
            product = Product.objects.select_for_update().get(pk=item.product_id)
            if product.product_type == Product.ProductType.BUNDLE:
                bundle_items = list(
                    product.bundle_items.select_related("item").all()
                )
                if not bundle_items:
                    return_fifo_stock(
                        product,
                        item.quantity,
                        unit_cost_clp=item.unit_cost_clp,
                    )
                    create_stock_movement(
                        product=product,
                        movement_type=KardexMovement.MovementType.RETURN_IN,
                        quantity=item.quantity,
                        created_by=user,
                        unit_cost_clp=item.unit_cost_clp,
                        unit_price_clp=item.unit_price_clp,
                        reference_type="ORDER",
                        reference_id=order.id,
                        reference_label=f"Orden #{order.id}",
                        notes="Reposición por cancelación de bundle sin componentes",
                    )
                    continue

                total_component_qty = sum(bundle_item.quantity for bundle_item in bundle_items) * item.quantity

                for bundle_item in bundle_items:
                    component = Product.objects.select_for_update().get(
                        pk=bundle_item.item_id
                    )
                    component_qty = bundle_item.quantity * item.quantity
                    proportional_total_cost = int(round((item.total_cost_clp * component_qty) / total_component_qty)) if total_component_qty else 0
                    component_unit_cost_clp = int(round(proportional_total_cost / component_qty)) if component_qty else 0
                    return_fifo_stock(
                        component,
                        component_qty,
                        unit_cost_clp=component_unit_cost_clp,
                    )
                    create_stock_movement(
                        product=component,
                        movement_type=KardexMovement.MovementType.RETURN_IN,
                        quantity=component_qty,
                        created_by=user,
                        unit_cost_clp=component_unit_cost_clp,
                        unit_price_clp=0,
                        reference_type="ORDER",
                        reference_id=order.id,
                        reference_label=f"Orden #{order.id} (bundle: {product.name})",
                        notes=f"Reposición por cancelación de bundle '{product.name}'",
                    )
            else:
                return_fifo_stock(
                    product,
                    item.quantity,
                    unit_cost_clp=item.unit_cost_clp,
                )
                create_stock_movement(
                    product=product,
                    movement_type=KardexMovement.MovementType.RETURN_IN,
                    quantity=item.quantity,
                    created_by=user,
                    unit_cost_clp=item.unit_cost_clp,
                    unit_price_clp=item.unit_price_clp,
                    reference_type="ORDER",
                    reference_id=order.id,
                    reference_label=f"Orden #{order.id}",
                    notes="Reposición por cancelación de orden",
                )

    order.status = Order.Status.CANCELED
    order.cancelled_at = timezone.now()
    order.save(
        update_fields=[
            "status",
            "cancelled_at",
            "updated_at",
        ]
    )

    return order
