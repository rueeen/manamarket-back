from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from orders.models import Order, OrderItem
from payments.models import PaymentTransaction
from payments.services import create_webpay_transaction, finalize_paid_order, release_order_stock_reservation
from products.models import Product


class StockReservationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="buyer", password="x", role="customer")
        self.product = Product.objects.create(name="Test", product_type="single", price_clp=1000, stock=1, is_active=True)
        self.order = Order.objects.create(user=self.user, total_clp=1000)
        OrderItem.objects.create(order=self.order, product=self.product, quantity=1, unit_price_clp=1000, subtotal_clp=1000)

    @patch("payments.services._request", return_value={"token": "tok_1", "url": "https://webpay"})
    def test_reserve_stock_on_webpay_create(self, _mock_request):
        create_webpay_transaction(self.order, self.user)
        self.product.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.product.stock_reserved, 1)
        self.assertEqual(self.product.available_stock, 0)
        self.assertEqual(self.order.stock_reservation_status, Order.StockReservationStatus.RESERVED)

    @patch("payments.services._request", return_value={"token": "tok_2", "url": "https://webpay"})
    def test_second_order_fails_when_last_stock_reserved(self, _mock_request):
        create_webpay_transaction(self.order, self.user)
        other_user = get_user_model().objects.create_user(username="buyer2", password="x", role="customer")
        order2 = Order.objects.create(user=other_user, total_clp=1000)
        OrderItem.objects.create(order=order2, product=self.product, quantity=1, unit_price_clp=1000, subtotal_clp=1000)
        with self.assertRaisesMessage(Exception, "Stock insuficiente"):
            create_webpay_transaction(order2, other_user)

    def test_release_is_idempotent(self):
        self.order.stock_reservation_status = Order.StockReservationStatus.RESERVED
        self.order.save(update_fields=["stock_reservation_status"])
        self.product.stock_reserved = 1
        self.product.save(update_fields=["stock_reserved"])
        release_order_stock_reservation(self.order)
        release_order_stock_reservation(self.order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_reserved, 0)

    def test_expired_reservation_command_releases(self):
        self.order.status = Order.Status.PAYMENT_STARTED
        self.order.stock_reservation_status = Order.StockReservationStatus.RESERVED
        self.order.stock_reservation_expires_at = timezone.now() - timedelta(minutes=1)
        self.order.save(update_fields=["status", "stock_reservation_status", "stock_reservation_expires_at"])
        self.product.stock_reserved = 1
        self.product.save(update_fields=["stock_reserved"])
        call_command("release_expired_stock_reservations")
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.EXPIRED)
        self.assertEqual(self.product.stock_reserved, 0)

    def test_finalize_consumes_reservation(self):
        self.order.status = Order.Status.PAYMENT_STARTED
        self.order.stock_reservation_status = Order.StockReservationStatus.RESERVED
        self.order.save(update_fields=["status", "stock_reservation_status"])
        self.product.stock_reserved = 1
        self.product.save(update_fields=["stock_reserved"])
        payment = PaymentTransaction.objects.create(
            order=self.order,
            user=self.user,
            status=PaymentTransaction.Status.AUTHORIZED,
            amount_clp=1000,
            buy_order="bo",
            session_id="sid",
            token="t-final",
        )
        with patch("payments.services.confirm_order_payment", return_value=self.order):
            finalize_paid_order(self.order, payment)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_reserved, 0)
