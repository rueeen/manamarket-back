from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cart.models import Cart, CartItem
from orders.models import (
    AssistedPurchaseItem,
    AssistedPurchaseOrder,
    Order,
    OrderItem,
)
from products.models import (
    BundleItem,
    InventoryLot,
    KardexMovement,
    MTGCard,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
)


class Command(BaseCommand):
    help = (
        "Limpia datos comerciales para reiniciar catálogo y operaciones: "
        "carritos, órdenes, productos, compras, lotes y kardex. "
        "Conserva usuarios, proveedores, categorías y configuraciones."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Confirma la limpieza sin pedir confirmación interactiva.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra cuántos registros se eliminarían sin borrar nada.",
        )
        parser.add_argument(
            "--allow-production",
            action="store_true",
            help="Permite ejecutar el comando con DEBUG=False. Usar con extremo cuidado.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        confirmed = options["yes"]
        allow_production = options["allow_production"]

        if not settings.DEBUG and not allow_production:
            raise CommandError(
                "Este comando está bloqueado con DEBUG=False. "
                "Si realmente necesitas ejecutarlo, usa --allow-production --yes."
            )

        purge_sequence = [
            (CartItem, "items de carrito"),
            (Cart, "carritos"),

            (AssistedPurchaseItem, "items de órdenes asistidas"),
            (AssistedPurchaseOrder, "órdenes asistidas"),

            (OrderItem, "items de órdenes"),
            (Order, "órdenes"),

            (BundleItem, "composiciones de bundles"),

            (InventoryLot, "lotes de inventario"),
            (KardexMovement, "movimientos de kardex"),

            (PurchaseOrderItem, "items de órdenes de compra"),
            (PurchaseOrder, "órdenes de compra"),

            (Product, "productos"),
            (MTGCard, "cartas MTG cacheadas"),
        ]

        self.stdout.write(self.style.WARNING(
            "Este comando eliminará datos comerciales."))
        self.stdout.write("Se eliminarán:")
        for _, label in purge_sequence:
            self.stdout.write(f" - {label}")

        self.stdout.write("")
        self.stdout.write("Se conservarán:")
        self.stdout.write(" - usuarios")
        self.stdout.write(" - proveedores")
        self.stdout.write(" - categorías")
        self.stdout.write(" - configuraciones de precios")
        self.stdout.write(" - configuraciones de dólar/envío/comisiones")

        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "DRY RUN: no se eliminará nada."))

            for model, label in purge_sequence:
                count = model.objects.count()
                self.stdout.write(f"{label}: {count} se eliminarían")

            return

        if not confirmed:
            answer = input(
                "\nEscribe LIMPIAR para confirmar la eliminación de datos comerciales: "
            )

            if answer != "LIMPIAR":
                raise CommandError("Operación cancelada.")

        with transaction.atomic():
            for model, label in purge_sequence:
                deleted_count, _ = model.objects.all().delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{label}: {deleted_count} eliminados"
                    )
                )

        self.stdout.write(
            self.style.WARNING(
                "Limpieza completada. Se conservaron usuarios, proveedores, "
                "categorías y configuraciones."
            )
        )
