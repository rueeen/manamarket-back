from django.core.management.base import BaseCommand
from django.db import transaction

from products.models import KardexMovement, Product


class Command(BaseCommand):
    help = "Inicializa Kardex para productos con stock existente sin modificar el stock actual"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra cuántos movimientos se crearían sin guardarlos.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        created = 0
        skipped = 0

        products = Product.objects.filter(stock__gt=0).order_by("id")

        for product in products:
            exists = KardexMovement.objects.filter(
                product=product,
                reference_type="MIGRATION",
                reference_label="Saldo inicial por migración",
            ).exists()

            if exists:
                skipped += 1
                continue

            if dry_run:
                created += 1
                continue

            KardexMovement.objects.create(
                product=product,
                movement_type=KardexMovement.MovementType.CORRECTION,
                quantity=product.stock,
                previous_stock=0,
                new_stock=product.stock,
                unit_cost_clp=product.cost_real_clp,
                unit_price_clp=product.computed_price_clp,
                reference_type="MIGRATION",
                reference_id=str(product.id),
                reference_label="Saldo inicial por migración",
                notes="Inicialización de Kardex desde stock histórico existente.",
                created_by=None,
            )

            created += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Se crearían {created} movimientos. Omitidos por existentes: {skipped}"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Movimientos creados: {created}. Omitidos por existentes: {skipped}"
            )
        )
