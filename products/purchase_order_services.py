from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import warnings

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .inventory_services import create_stock_movement
from .models import (
    ExchangeRateConfig,
    InventoryLot,
    KardexMovement,
    PricingSettings,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
)


D = Decimal


def _d(value):
    return D(str(value or 0))


def _q2(value):
    return _d(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def _clp(value):
    return int(_d(value).quantize(D("1"), rounding=ROUND_HALF_UP))


def get_active_pricing_settings():
    return (
        PricingSettings.objects.filter(is_active=True)
        .order_by("-updated_at")
        .first()
    )


def get_active_exchange_rate():
    pricing_settings = get_active_pricing_settings()

    if pricing_settings and pricing_settings.usd_to_clp:
        return _q2(pricing_settings.usd_to_clp)

    exchange_config = (
        ExchangeRateConfig.objects.filter(is_active=True)
        .order_by("-updated_at", "-id")
        .first()
    )

    if exchange_config and exchange_config.usd_to_clp:
        warnings.warn(
            (
                "Using ExchangeRateConfig as fallback in get_active_exchange_rate() "
                "is deprecated and will be removed in a future sprint. "
                "Populate an active PricingSettings.usd_to_clp instead."
            ),
            DeprecationWarning,
            stacklevel=2,
        )
        return _q2(exchange_config.usd_to_clp)

    raise ValidationError("No existe un tipo de cambio activo.")


def convert_money_to_clp(amount, currency, exchange_rate):
    currency = str(currency or "CLP").upper()

    if currency == "CLP":
        return _clp(amount)

    if currency != "USD":
        raise ValidationError("Moneda no soportada.")

    if _d(exchange_rate) <= 0:
        raise ValidationError("Tipo de cambio inválido.")

    return _clp(_d(amount) * _d(exchange_rate))


def calculate_suggested_price_from_real_cost(real_unit_cost_clp, pricing_settings=None):
    """
    Calcula precio sugerido usando PricingSettings activo.

    Fórmula:
    suggested = real_unit_cost_clp * margin_factor
    redondeado hacia arriba al múltiplo de rounding_to.
    """
    pricing_settings = pricing_settings or get_active_pricing_settings()
    margin_factor = _d(getattr(pricing_settings, "margin_factor", D("1.25")))
    rounding_to = max(int(getattr(pricing_settings, "rounding_to", 100) or 100), 1)

    raw = _d(real_unit_cost_clp) * margin_factor
    rounded = (raw / D(rounding_to)).quantize(D("1"), rounding=ROUND_CEILING)
    return int(rounded * D(rounding_to))


def calculate_purchase_order_totals(order):
    """
    Calcula totales de una orden de compra en CLP.

    No guarda la orden, pero sí actualiza líneas item.line_total_clp
    e item.unit_price_clp.
    """
    currency = str(order.original_currency or "CLP").upper()
    rate = _d(order.exchange_rate_snapshot_clp or 1)

    if currency == "USD" and rate <= D("1"):
        raise ValidationError(
            "La orden está en USD, pero el tipo de cambio snapshot es inválido."
        )

    subtotal_clp = 0

    for item in order.items.all():
        quantity = int(item.quantity_ordered or 1)

        if currency == "USD" and _d(item.unit_price_original or 0) > D("1000"):
            raise ValidationError(
                f"El item {item.id} parece tener costo CLP enviado como USD: "
                f"{item.unit_price_original}. Cambia la moneda a CLP o ingresa costo USD."
            )

        line_clp = convert_money_to_clp(
            item.line_total_original,
            currency,
            rate,
        )

        item.line_total_clp = line_clp
        item.unit_price_clp = _clp(_d(line_clp) / _d(quantity))
        item.save(
            update_fields=[
                "line_total_clp",
                "unit_price_clp",
            ]
        )

        subtotal_clp += line_clp

    shipping_clp = convert_money_to_clp(
        order.shipping_original,
        currency,
        rate,
    )
    sales_tax_clp = convert_money_to_clp(
        order.sales_tax_original,
        currency,
        rate,
    )

    total_origin_clp = subtotal_clp + shipping_clp + sales_tax_clp

    total_extra = (
        shipping_clp
        + sales_tax_clp
        + int(order.import_duties_clp or 0)
        + int(order.customs_fee_clp or 0)
        + int(order.handling_fee_clp or 0)
        + int(order.paypal_variation_clp or 0)
        + int(order.other_costs_clp or 0)
    )

    real_total = subtotal_clp + total_extra

    return {
        "subtotal_clp": subtotal_clp,
        "shipping_clp": shipping_clp,
        "sales_tax_clp": sales_tax_clp,
        "total_origin_clp": total_origin_clp,
        "total_extra_costs_clp": total_extra,
        "grand_total_clp": real_total,
    }


def allocate_extra_costs(order):
    """
    Distribuye costos extra proporcionalmente al valor de cada línea.

    Los costos extra incluyen shipping, taxes, aduana, handling, PayPal
    y otros costos definidos en PurchaseOrder.
    """
    items = list(order.items.all().order_by("id"))
    subtotal = int(order.subtotal_clp or 0)
    total_extra = int(order.total_extra_costs_clp or 0)

    if subtotal <= 0 or not items:
        return

    # Se obtiene una sola vez para evitar N+1 queries de PricingSettings.
    pricing_settings = get_active_pricing_settings()
    allocated = 0

    for index, item in enumerate(items):
        is_last = index == len(items) - 1

        if is_last:
            share = total_extra - allocated
        else:
            share = _clp(
                _d(total_extra)
                * (_d(item.line_total_clp) / _d(subtotal))
            )

        allocated += share

        item.allocated_extra_cost_clp = max(0, share)
        item.allocated_tax_clp = 0

        qty = int(item.quantity_ordered or 0)

        if qty <= 0:
            item.real_unit_cost_clp = 0
            item.suggested_sale_price_clp = 0
        else:
            item.real_unit_cost_clp = _clp(
                (
                    _d(item.line_total_clp)
                    + _d(item.allocated_extra_cost_clp)
                )
                / _d(qty)
            )
            item.suggested_sale_price_clp = calculate_suggested_price_from_real_cost(
                item.real_unit_cost_clp,
                pricing_settings=pricing_settings,
            )

    # Persistencia en lote para evitar N saves individuales.
    PurchaseOrderItem.objects.bulk_update(
        items,
        [
            "allocated_extra_cost_clp",
            "allocated_tax_clp",
            "real_unit_cost_clp",
            "suggested_sale_price_clp",
        ],
    )


def recalculate_purchase_order(order):
    totals = calculate_purchase_order_totals(order)

    for field, value in totals.items():
        setattr(order, field, value)

    order.save(update_fields=list(totals.keys()) + ["updated_at"])

    allocate_extra_costs(order)

    return order


@transaction.atomic
def receive_purchase_order(order, user):
    """
    Recibe una orden de compra.

    Reglas:
    - Recalcula totales.
    - Valida que todos los ítems tengan producto asociado.
    - Ingresa stock mediante Kardex PURCHASE_IN.
    - Crea lotes FIFO.
    - Opcionalmente actualiza precio de venta.
    - Impide recibir dos veces.
    """
    purchase_order = (
        PurchaseOrder.objects.select_for_update()
        .prefetch_related("items__product")
        .get(pk=order.pk)
    )

    if purchase_order.status == PurchaseOrder.Status.CANCELLED:
        raise ValidationError("No se puede recibir una orden cancelada.")

    if purchase_order.status == PurchaseOrder.Status.RECEIVED:
        raise ValidationError("No se puede recibir una orden dos veces.")

    recalculate_purchase_order(purchase_order)

    items = list(purchase_order.items.all())

    if not items:
        raise ValidationError("No se puede recibir una orden sin ítems.")

    receivable_items = [
        item
        for item in items
        if int(item.quantity_ordered or 0) > int(item.quantity_received or 0)
    ]

    if not receivable_items:
        raise ValidationError(
            "La orden no tiene ítems pendientes de recepción."
        )

    missing_items = [
        {
            "id": item.id,
            "raw_description": item.raw_description,
            "normalized_card_name": item.normalized_card_name,
            "style_condition": item.style_condition,
        }
        for item in receivable_items
        if not item.product_id
    ]

    if missing_items:
        raise ValidationError(
            {
                "detail": (
                    "No se puede recibir la orden porque existen ítems "
                    "sin producto vinculado."
                ),
                "missing_products_count": len(missing_items),
                "missing_items": missing_items,
            }
        )

    for item in receivable_items:
        qty = int(item.quantity_ordered or 0) - \
            int(item.quantity_received or 0)

        if qty <= 0:
            continue

        # Blindaje: derivar siempre el costo unitario desde los montos unitarios
        # de la línea para no arrastrar un total de línea como costo unitario.
        ordered_qty = int(item.quantity_ordered or 0)
        line_total_clp = int(item.line_total_clp or 0)
        allocated_extra_cost_clp = int(item.allocated_extra_cost_clp or 0)

        recalculated_unit_cost = 0
        if ordered_qty > 0:
            recalculated_unit_cost = _clp(
                (
                    _d(line_total_clp)
                    + _d(allocated_extra_cost_clp)
                )
                / _d(ordered_qty)
            )

        unit_cost = int(
            recalculated_unit_cost
            or item.real_unit_cost_clp
            or item.unit_price_clp
            or 0
        )

        if unit_cost <= 0:
            raise ValidationError(
                f"Costo unitario inválido para item {item.id} "
                f"({item.normalized_card_name or item.raw_description}): "
                "real_unit_cost_clp debe ser mayor a 0. "
                f"currency={purchase_order.original_currency}, "
                f"exchange_rate={purchase_order.exchange_rate_snapshot_clp}, "
                f"unit_price_original={item.unit_price_original}, "
                f"real_unit_cost_clp={item.real_unit_cost_clp}"
            )

        create_stock_movement(
            product=item.product,
            movement_type=KardexMovement.MovementType.PURCHASE_IN,
            quantity=qty,
            created_by=user,
            unit_cost_clp=unit_cost,
            reference_type="PURCHASE_ORDER",
            reference_id=purchase_order.id,
            reference_label=purchase_order.order_number,
            notes="Ingreso por recepción de orden de compra",
        )

        InventoryLot.objects.create(
            product=item.product,
            purchase_order_item=item,
            quantity_initial=qty,
            quantity_remaining=qty,
            unit_cost_clp=max(1, unit_cost),
            received_at=timezone.now(),
        )

        real_cost = int(item.real_unit_cost_clp or unit_cost or 0)
        suggested_price = int(
            item.suggested_sale_price_clp
            or calculate_suggested_price_from_real_cost(real_cost)
            or 0
        )

        if suggested_price != int(item.suggested_sale_price_clp or 0):
            item.suggested_sale_price_clp = suggested_price
            item.save(update_fields=["suggested_sale_price_clp"])

        # average_cost_clp y last_purchase_cost_clp se actualizan internamente
        # en create_stock_movement para ingresos PURCHASE_IN.
        update_payload = {}

        if purchase_order.update_prices_on_receive:
            manual_sale_price = int(item.sale_price_to_apply_clp or 0)

            if manual_sale_price > 0 and manual_sale_price >= real_cost:
                sale_price = manual_sale_price
            else:
                sale_price = suggested_price

            if sale_price > 0:
                update_payload["price_clp"] = max(sale_price, real_cost)

            if real_cost > 0 and int(update_payload.get("price_clp", 0)) < real_cost:
                update_payload["is_active"] = False
        else:
            current_price = int(
                Product.objects.values_list("price_clp", flat=True).get(pk=item.product_id)
                or 0
            )
            if real_cost > 0 and current_price < real_cost:
                update_payload["is_active"] = False

        if update_payload:
            Product.objects.filter(pk=item.product_id).update(**update_payload)

        item.quantity_received = int(item.quantity_received or 0) + qty
        item.save(update_fields=["quantity_received"])

    purchase_order.status = PurchaseOrder.Status.RECEIVED
    purchase_order.received_at = timezone.now()
    purchase_order.received_by = user
    purchase_order.save(
        update_fields=[
            "status",
            "received_at",
            "received_by",
            "updated_at",
        ]
    )

    return purchase_order
