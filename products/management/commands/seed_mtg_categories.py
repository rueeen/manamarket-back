from django.core.management.base import BaseCommand

from products.models import Category, Product

BASE_CATEGORIES = [
    {"name":"Cartas individuales","slug":"cartas-individuales","description":"Singles de Magic: The Gathering por carta, condición, idioma y foil."},
    {"name":"Productos sellados","slug":"productos-sellados","description":"Productos sellados oficiales de Magic: The Gathering."},
    {"name":"Commander Precons","slug":"commander-precons","description":"Mazos preconstruidos de Commander."},
    {"name":"Booster Boxes","slug":"booster-boxes","description":"Cajas de sobres selladas."},
    {"name":"Play Boosters","slug":"play-boosters","description":"Sobres Play Booster individuales o en packs."},
    {"name":"Collector Boosters","slug":"collector-boosters","description":"Sobres Collector Booster individuales o en packs."},
    {"name":"Bundles oficiales","slug":"bundles-oficiales","description":"Bundles oficiales de Magic: The Gathering."},
    {"name":"Starter Kits","slug":"starter-kits","description":"Kits de inicio para nuevos jugadores."},
    {"name":"Secret Lair","slug":"secret-lair","description":"Productos Secret Lair oficiales."},
    {"name":"Universes Beyond","slug":"universes-beyond","description":"Productos de Universes Beyond."},
    {"name":"Accesorios","slug":"accesorios","description":"Accesorios generales para jugar y proteger cartas."},
    {"name":"Sleeves","slug":"sleeves","description":"Protectores de cartas."},
    {"name":"Deck Boxes","slug":"deck-boxes","description":"Cajas para guardar mazos."},
    {"name":"Playmats","slug":"playmats","description":"Tapetes de juego."},
    {"name":"Dados y contadores","slug":"dados-y-contadores","description":"Dados, contadores, tokens físicos y accesorios de mesa."},
    {"name":"Bundles tienda","slug":"bundles-tienda","description":"Packs armados manualmente por la tienda."},
    {"name":"Lotes de cartas","slug":"lotes-de-cartas","description":"Lotes de cartas agrupadas por colección, rareza, color o formato."},
    {"name":"Preventas","slug":"preventas","description":"Productos disponibles para reserva o preventa."},
    {"name":"Productos por encargo","slug":"productos-por-encargo","description":"Productos solicitados a proveedor bajo pedido."},
    {"name":"Otros","slug":"otros","description":"Productos no clasificados."},
]

DEFAULT_BY_TYPE = {
    Product.ProductType.SINGLE: "cartas-individuales",
    Product.ProductType.SEALED: "productos-sellados",
    Product.ProductType.BUNDLE: "bundles-tienda",
    Product.ProductType.ACCESSORY: "accesorios",
    Product.ProductType.SERVICE: "productos-por-encargo",
    Product.ProductType.OTHER: "otros",
}


class Command(BaseCommand):
    help = "Crea/actualiza categorías base MTG y asigna categoría por defecto a productos sin categoría."

    def handle(self, *args, **options):
        by_slug = {}
        for index, item in enumerate(BASE_CATEGORIES, start=1):
            category, created = Category.objects.get_or_create(
                slug=item["slug"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "is_active": True,
                    "sort_order": index,
                },
            )
            changed = False
            if category.name != item["name"]:
                category.name = item["name"]
                changed = True
            if category.description != item["description"]:
                category.description = item["description"]
                changed = True
            if not category.is_active:
                category.is_active = True
                changed = True
            if category.sort_order != index:
                category.sort_order = index
                changed = True
            if changed:
                category.save(update_fields=["name", "description", "is_active", "sort_order", "updated_at"])
            by_slug[item["slug"]] = category
            self.stdout.write(self.style.SUCCESS(f"{'Creada' if created else 'Actualizada'}: {category.name}"))

        updated = 0
        for product_type, slug in DEFAULT_BY_TYPE.items():
            category = by_slug.get(slug)
            if not category:
                continue
            updated += Product.objects.filter(product_type=product_type, category__isnull=True).update(category=category)

        self.stdout.write(self.style.SUCCESS(f"Productos sin categoría actualizados: {updated}"))
