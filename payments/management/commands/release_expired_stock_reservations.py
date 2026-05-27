from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from orders.models import Order
from payments.models import PaymentTransaction
from payments.services import release_order_stock_reservation


class Command(BaseCommand):
    help = "Libera reservas de stock expiradas en órdenes awaiting_payment/payment_started."

    def handle(self, *args, **options):
        now = timezone.now()
        qs = Order.objects.filter(
            status=Order.Status.PAYMENT_STARTED,
            stock_reservation_status=Order.StockReservationStatus.RESERVED,
            stock_reservation_expires_at__lte=now,
        )
        processed = 0
        for order_id in qs.values_list("id", flat=True):
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=order_id)
                if order.status == Order.Status.PAID:
                    continue
                if order.stock_reservation_status != Order.StockReservationStatus.RESERVED:
                    continue
                payment = order.payment_transactions.order_by("-created_at").first()
                if payment and payment.status == PaymentTransaction.Status.AUTHORIZED:
                    continue
                release_order_stock_reservation(order, payment=payment)
                order.status = Order.Status.EXPIRED
                order.save(update_fields=["status", "updated_at"])
                processed += 1
        self.stdout.write(self.style.SUCCESS(f"Reservas liberadas: {processed}"))

        # Marcar como EXPIRED órdenes en payment_failed sin actividad por 24h
        expiry_threshold = now - timedelta(hours=24)

        stale_orders = Order.objects.filter(
            status=Order.Status.PAYMENT_FAILED,
            updated_at__lt=expiry_threshold,
        )

        expired_count = 0
        for order in stale_orders:
            order.status = Order.Status.EXPIRED
            order.save(update_fields=["status", "updated_at"])
            expired_count += 1
            self.stdout.write(
                f"  Orden #{order.id} marcada como EXPIRED "
                f"(payment_failed desde {order.updated_at})"
            )

        if expired_count:
            self.stdout.write(
                self.style.WARNING(
                    f"{expired_count} orden(es) marcadas como EXPIRED."
                )
            )

