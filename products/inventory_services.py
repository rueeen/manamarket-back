import logging

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    InventoryLot,
    KardexMovement,
    Product,
)

logger = logging.getLogger(__name__)


PURCHASE_IN_TYPES = {
    KardexMovement.MovementType.PURCHASE_IN,
    KardexMovement.MovementType.MANUAL_IN,
    KardexMovement.MovementType.RETURN_IN,
}

OUT_TYPES = {
    KardexMovement.MovementType.SALE_OUT,
    KardexMovement.MovementType.MANUAL_OUT,
}


def _recalculate_average_cost(product, incoming_qty, incoming_cost):
    previous_stock = int(product.stock or 0)
    previous_avg = int(product.average_cost_clp or 0)
    incoming_qty = int(incoming_qty or 0)
    incoming_cost = int(incoming_cost or 0)

    denominator = previous_stock + incoming_qty

    if denominator <= 0:
        return 0

    return int(
        round(
            (
                (previous_stock * previous_avg)
                + (incoming_qty * incoming_cost)
            )
            / denominator
        )
    )


def _round_to(value, rounding_to):
    base = int(rounding_to or 1)

    if base <= 1:
        return int(round(value))

    return int(round(float(value) / base) * base)


@transaction.atomic
def consume_fifo_stock(product, quantity):
    """
    Consume lotes FIFO para una venta y retorna el costo ponderado.

    Importante:
    - Esta función descuenta InventoryLot.quantity_remaining.
    - Esta función NO modifica Product.stock.
    - Product.stock se modifica en create_stock_movement().
    """
    qty_to_consume = int(quantity or 0)

    if qty_to_consume <= 0:
        raise ValidationError("La cantidad debe ser mayor a 0.")

    product = Product.objects.select_for_update().get(pk=product.pk)

    lots = list(
        InventoryLot.objects.select_for_update()
        .filter(
            product=product,
            quantity_remaining__gt=0,
        )
        .order_by("received_at", "id")
    )

    available = sum(lot.quantity_remaining for lot in lots)

    if available < qty_to_consume:
        raise ValidationError(f"Stock FIFO insuficiente para {product.name}.")

    total_cost_clp = 0
    remaining = qty_to_consume

    for lot in lots:
        if remaining == 0:
            break

        consumed = min(lot.quantity_remaining, remaining)

        lot.quantity_remaining -= consumed
        lot.save(update_fields=["quantity_remaining"])

        total_cost_clp += consumed * int(lot.unit_cost_clp or 0)
        remaining -= consumed

    unit_cost_clp = int(round(total_cost_clp / qty_to_consume))

    return {
        "total_cost_clp": total_cost_clp,
        "unit_cost_clp": unit_cost_clp,
    }


@transaction.atomic
def create_stock_movement(
    *,
    product,
    movement_type,
    quantity,
    created_by=None,
    unit_cost_clp=0,
    unit_price_clp=0,
    reference_type="",
    reference_id="",
    reference_label="",
    notes="",
):
    """
    Crea un movimiento Kardex y actualiza Product.stock.

    Reglas:
    - PURCHASE_IN, MANUAL_IN y RETURN_IN suman stock.
    - SALE_OUT y MANUAL_OUT restan stock.
    - ADJUSTMENT y CORRECTION fijan el stock final.
    """
    qty = int(quantity or 0)

    if qty <= 0:
        raise ValidationError("La cantidad debe ser mayor a 0.")

    product = Product.objects.select_for_update().get(pk=product.pk)

    previous_stock = int(product.stock or 0)

    if movement_type in PURCHASE_IN_TYPES:
        new_stock = previous_stock + qty

    elif movement_type in OUT_TYPES:
        if previous_stock < qty:
            raise ValidationError(
                "No hay stock suficiente para este movimiento.")

        new_stock = previous_stock - qty

    elif movement_type in {
        KardexMovement.MovementType.ADJUSTMENT,
        KardexMovement.MovementType.CORRECTION,
    }:
        new_stock = qty
        qty = abs(new_stock - previous_stock)

    else:
        raise ValidationError("Tipo de movimiento inválido.")

    update_fields = ["stock"]

    if movement_type == KardexMovement.MovementType.PURCHASE_IN:
        product.average_cost_clp = _recalculate_average_cost(
            product=product,
            incoming_qty=quantity,
            incoming_cost=unit_cost_clp,
        )
        product.last_purchase_cost_clp = int(unit_cost_clp or 0)

        update_fields.extend(
            [
                "average_cost_clp",
                "last_purchase_cost_clp",
            ]
        )

    product.stock = new_stock
    product.save(update_fields=update_fields)

    movement = KardexMovement.objects.create(
        product=product,
        movement_type=movement_type,
        quantity=qty,
        previous_stock=previous_stock,
        new_stock=new_stock,
        unit_cost_clp=int(unit_cost_clp or 0),
        unit_price_clp=int(unit_price_clp or 0),
        reference_type=reference_type or "",
        reference_id=str(reference_id or ""),
        reference_label=reference_label or "",
        notes=notes or "",
        created_by=created_by,
    )

    logger.info(
        "Kardex movement created product_id=%s type=%s qty=%s previous_stock=%s new_stock=%s",
        product.pk,
        movement_type,
        qty,
        previous_stock,
        new_stock,
    )

    return movement


def return_fifo_stock(product, quantity, unit_cost_clp=0, received_at=None):
    """
    Reingresa stock a FIFO mediante un nuevo lote.

    Útil para cancelaciones o devoluciones cuando ya se había consumido FIFO.

    Importante:
    - Esta función NO modifica Product.stock.
    - Product.stock debe actualizarse mediante create_stock_movement(... RETURN_IN ...).
    """
    from django.utils import timezone

    qty = int(quantity or 0)

    if qty <= 0:
        raise ValidationError("La cantidad debe ser mayor a 0.")

    product = Product.objects.select_for_update().get(pk=product.pk)

    lot = InventoryLot.objects.create(
        product=product,
        purchase_order_item=None,
        quantity_initial=qty,
        quantity_remaining=qty,
        unit_cost_clp=int(unit_cost_clp if unit_cost_clp is not None else (product.cost_real_clp or 0)),
        received_at=received_at or timezone.now(),
    )

    return lot


def receive_purchase_order(*args, **kwargs):
    raise ValidationError(
        "Función obsoleta: use products.purchase_order_services.receive_purchase_order"
    )
