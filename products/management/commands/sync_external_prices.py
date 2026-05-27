from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from products.models import PricingSource, Product
from products.purchase_order_services import get_active_pricing_settings
from products.services import extract_usd_price, get_scryfall_card_by_id


class Command(BaseCommand):
    help = "Sincroniza precios externos desde Scryfall para todos los singles activos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-id",
            type=int,
            help="Sincronizar solo un producto específico por ID",
        )

    def handle(self, *args, **options):
        product_id = options.get("product_id")

        pricing = get_active_pricing_settings()
        if not pricing:
            self.stderr.write("No hay configuración de precios activa.")
            return

        exchange_rate = float(pricing.exchange_rate_usd_clp or 0)

        if exchange_rate <= 0:
            self.stderr.write("El tipo de cambio USD/CLP es 0 o no está configurado.")
            return

        qs = Product.objects.filter(is_active=True, product_type="single")
        if product_id:
            qs = qs.filter(id=product_id)

        qs = qs.select_related("single_card__mtg_card")

        updated = 0
        errors = 0

        for product in qs:
            if not hasattr(product, "single_card") or not product.single_card:
                continue

            single_card = product.single_card
            if not single_card.mtg_card_id:
                continue

            try:
                card_data = get_scryfall_card_by_id(single_card.mtg_card.scryfall_id)
                usd_price = extract_usd_price(card_data, is_foil=single_card.is_foil)

                product.price_external_usd = Decimal(str(usd_price or 0))
                product.exchange_rate_usd_clp = Decimal(str(exchange_rate))
                product.pricing_source = PricingSource.SCRYFALL
                product.pricing_last_update = timezone.now()
                product.save(
                    update_fields=[
                        "price_external_usd",
                        "exchange_rate_usd_clp",
                        "pricing_source",
                        "pricing_last_update",
                        "updated_at",
                    ]
                )
                updated += 1
            except Exception as exc:
                self.stderr.write(f"Error en producto {product.id} ({product.name}): {exc}")
                errors += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sincronización completada: {updated} actualizados, {errors} errores."
            )
        )
