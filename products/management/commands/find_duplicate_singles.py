from django.core.management.base import BaseCommand
from django.db.models import Count

from products.models import SingleCard


class Command(BaseCommand):
    help = "Detecta productos single duplicados por mtg_card + condition + language + is_foil"

    def handle(self, *args, **options):
        groups = (
            SingleCard.objects.values("mtg_card_id", "condition", "language", "is_foil")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .order_by("-total", "mtg_card_id")
        )

        if not groups.exists():
            self.stdout.write(self.style.SUCCESS("No se encontraron duplicados de singles."))
            return

        for group in groups:
            rows = (
                SingleCard.objects.select_related("product", "mtg_card")
                .filter(
                    mtg_card_id=group["mtg_card_id"],
                    condition=group["condition"],
                    language=group["language"],
                    is_foil=group["is_foil"],
                )
                .order_by("product_id")
            )
            first = rows.first()
            self.stdout.write(
                self.style.WARNING(
                    f"\nCarta={first.mtg_card.name} scryfall_id={first.mtg_card.scryfall_id} "
                    f"condition={group['condition']} language={group['language']} "
                    f"is_foil={group['is_foil']} duplicados={group['total']}"
                )
            )

            for single in rows:
                p = single.product
                self.stdout.write(
                    f"  product_id={p.id} name={p.name} stock={p.stock} "
                    f"price_clp={p.price_clp} is_active={p.is_active}"
                )
