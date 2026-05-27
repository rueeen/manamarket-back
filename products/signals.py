from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PricingSettings, PurchaseOrderItem
from .purchase_order_services import calculate_suggested_price_from_real_cost


@receiver(post_save, sender=PricingSettings)
def recalculate_po_item_suggested_prices_on_margin_change(sender, instance, created, update_fields=None, **kwargs):
    """
    Recalcula en batch precios sugeridos almacenados en PurchaseOrderItem cuando
    cambia PricingSettings.

    Se usa bulk_update para evitar N queries individuales.
    """
    tracked_fields = {"margin_factor", "rounding_to", "is_active"}

    if not created and update_fields is not None and tracked_fields.isdisjoint(set(update_fields)):
        return

    items = list(PurchaseOrderItem.objects.only("id", "real_unit_cost_clp", "suggested_sale_price_clp"))
    if not items:
        return

    to_update = []
    for item in items:
        recomputed = int(calculate_suggested_price_from_real_cost(int(item.real_unit_cost_clp or 0)) or 0)
        if recomputed != int(item.suggested_sale_price_clp or 0):
            item.suggested_sale_price_clp = recomputed
            to_update.append(item)

    if to_update:
        PurchaseOrderItem.objects.bulk_update(to_update, ["suggested_sale_price_clp"])
