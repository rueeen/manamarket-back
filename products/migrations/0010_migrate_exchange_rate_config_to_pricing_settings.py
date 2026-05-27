from decimal import Decimal

from django.db import migrations


def migrate_exchange_rate_to_pricing_settings(apps, schema_editor):
    ExchangeRateConfig = apps.get_model("products", "ExchangeRateConfig")
    PricingSettings = apps.get_model("products", "PricingSettings")

    active_exchange = (
        ExchangeRateConfig.objects.filter(is_active=True)
        .order_by("-updated_at", "-id")
        .first()
    )

    if not active_exchange or active_exchange.usd_to_clp is None:
        return

    active_pricing = (
        PricingSettings.objects.filter(is_active=True)
        .order_by("-updated_at", "-id")
        .first()
    )

    if active_pricing:
        if active_pricing.usd_to_clp != active_exchange.usd_to_clp:
            active_pricing.usd_to_clp = active_exchange.usd_to_clp
            active_pricing.save(update_fields=["usd_to_clp", "updated_at"])
        return

    PricingSettings.objects.create(
        name="Migrated from ExchangeRateConfig",
        usd_to_clp=active_exchange.usd_to_clp,
        is_active=True,
        margin_factor=Decimal("1.25"),
        rounding_to=100,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0009_purchaseorder_real_total_clp_alias_property"),
    ]

    operations = [
        migrations.RunPython(
            migrate_exchange_rate_to_pricing_settings,
            migrations.RunPython.noop,
        ),
    ]
