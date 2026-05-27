from django.core.management.base import BaseCommand
from products.models import ProductTypeConfig

PRODUCT_TYPES = [
    ("Carta individual", "carta-individual", dict(uses_scryfall=True, requires_condition=True, requires_language=True, requires_foil=True, manages_stock=True)),
    ("Commander Precon", "commander-precon", dict(is_sealed=True)),
    ("Booster Box", "booster-box", dict(is_sealed=True)),
    ("Play Booster", "play-booster", dict(is_sealed=True)),
    ("Collector Booster", "collector-booster", dict(is_sealed=True)),
    ("Bundle oficial", "bundle-oficial", dict(is_sealed=True, is_bundle=True)),
    ("Bundle tienda", "bundle-tienda", dict(is_bundle=True)),
    ("Secret Lair", "secret-lair", dict(is_sealed=True)),
    ("Starter Kit", "starter-kit", dict(is_sealed=True)),
    ("Accesorio", "accesorio", dict()),
    ("Sleeves", "sleeves", dict()),
    ("Deck Box", "deck-box", dict()),
    ("Playmat", "playmat", dict()),
    ("Lote de cartas", "lote-de-cartas", dict(is_bundle=True)),
    ("Producto por encargo", "producto-por-encargo", dict(is_service=True, manages_stock=False)),
    ("Otro", "otro", dict()),
]


class Command(BaseCommand):
    help = "Seed inicial de tipos de producto"

    def handle(self, *args, **options):
        for idx, (name, slug, flags) in enumerate(PRODUCT_TYPES, start=1):
            defaults = {
                "description": "",
                "is_active": True,
                "sort_order": idx,
                "uses_scryfall": False,
                "requires_condition": False,
                "requires_language": False,
                "requires_foil": False,
                "manages_stock": True,
                "is_sealed": False,
                "is_bundle": False,
                "is_service": False,
            }
            defaults.update(flags)
            ProductTypeConfig.objects.update_or_create(slug=slug, defaults={"name": name, **defaults})
        self.stdout.write(self.style.SUCCESS("Tipos de producto creados/actualizados."))
