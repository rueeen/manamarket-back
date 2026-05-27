from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from cart.models import Cart, CartItem
from orders.models import Order
from orders.services import create_order_from_cart
from products.inventory_services import consume_fifo_stock, receive_purchase_order
from products.models import InventoryLot, Product, PurchaseOrder, PurchaseOrderItem, Supplier


class FifoInventoryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="fifo", password="x", role="customer")
        self.staff = get_user_model().objects.create_user(username="staff", password="x", role="admin", is_staff=True)
        self.supplier = Supplier.objects.create(name="Proveedor FIFO")
        self.product = Product.objects.create(name="Lightning Bolt", product_type="single", price_clp=3000, stock=0, is_active=True)

    def _receive_po(self, order_number, qty, cost):
        po = PurchaseOrder.objects.create(supplier=self.supplier, created_by=self.staff, order_number=order_number)
        PurchaseOrderItem.objects.create(purchase_order=po, product=self.product, quantity_ordered=qty, unit_cost_clp=cost)
        receive_purchase_order(po.id, self.staff)

    def test_receive_purchase_creates_lots_with_different_costs(self):
        self._receive_po("PO-FIFO-1", 2, 1000)
        self._receive_po("PO-FIFO-2", 3, 2000)
        lots = list(InventoryLot.objects.filter(product=self.product).order_by("received_at", "id"))
        self.assertEqual(len(lots), 2)
        self.assertEqual(lots[0].unit_cost_clp, 1000)
        self.assertEqual(lots[1].unit_cost_clp, 2000)

    def test_fifo_partial_sale_cost_and_profit(self):
        self._receive_po("PO-FIFO-1", 2, 1000)
        self._receive_po("PO-FIFO-2", 3, 2000)
        cart, _ = Cart.objects.get_or_create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=3)

        order = create_order_from_cart(self.user)
        item = order.items.get()
        self.assertEqual(item.total_cost_clp, 4000)
        self.assertEqual(item.unit_cost_clp, 1333)
        self.assertEqual(item.gross_profit_clp, item.subtotal_clp - 4000)

    def test_fifo_complete_sale_consumes_all_stock(self):
        self._receive_po("PO-FIFO-1", 2, 1000)
        self._receive_po("PO-FIFO-2", 3, 2000)
        cost = consume_fifo_stock(self.product, 5)
        self.assertEqual(cost["total_cost_clp"], 8000)
        self.assertEqual(sum(InventoryLot.objects.filter(product=self.product).values_list("quantity_remaining", flat=True)), 0)

    def test_fifo_ordering_is_correct(self):
        self._receive_po("PO-FIFO-1", 1, 500)
        self._receive_po("PO-FIFO-2", 1, 1500)
        cost = consume_fifo_stock(self.product, 1)
        self.assertEqual(cost["total_cost_clp"], 500)

    def test_error_when_insufficient_stock(self):
        self._receive_po("PO-FIFO-1", 1, 1000)
        with self.assertRaises(ValidationError):
            consume_fifo_stock(self.product, 2)

class OrderStockDeductionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="buyer", password="x", role="customer")
        self.staff = get_user_model().objects.create_user(username="ops", password="x", role="admin", is_staff=True)
        self.supplier = Supplier.objects.create(name="Supplier Stock")
        self.product = Product.objects.create(name="Shock", product_type="single", price_clp=2500, stock=0, is_active=True)

        po = PurchaseOrder.objects.create(supplier=self.supplier, created_by=self.staff, order_number="PO-STOCK-1")
        PurchaseOrderItem.objects.create(purchase_order=po, product=self.product, quantity_ordered=5, unit_cost_clp=1000)
        receive_purchase_order(po.id, self.staff)

    def test_create_order_deducts_product_stock_once(self):
        cart, _ = Cart.objects.get_or_create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)

        create_order_from_cart(self.user)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_create_order_sets_sale_kardex_unit_cost_from_fifo(self):
        cart, _ = Cart.objects.get_or_create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)

        order = create_order_from_cart(self.user)
        movement = KardexMovement.objects.get(
            product=self.product,
            movement_type=KardexMovement.MovementType.SALE_OUT,
            reference_id=str(order.id),
        )

        self.assertEqual(movement.unit_cost_clp, 1000)
        self.assertEqual(movement.quantity, 2)


class OrderCancelPermissionTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = get_user_model().objects.create_user(
            username="customer", password="x", role="customer"
        )
        self.other_customer = get_user_model().objects.create_user(
            username="other_customer", password="x", role="customer"
        )
        self.worker = get_user_model().objects.create_user(
            username="worker", password="x", role="worker", is_staff=True
        )

        self.order = Order.objects.create(user=self.customer, status=Order.Status.PENDING)
        self.other_order = Order.objects.create(user=self.other_customer, status=Order.Status.PENDING)

    def test_customer_cannot_cancel_other_users_order(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(f"/api/orders/{self.other_order.id}/cancel/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_can_cancel_own_order(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(f"/api/orders/{self.order.id}/cancel/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELED)

    def test_worker_can_cancel_any_order(self):
        self.client.force_authenticate(self.worker)

        response = self.client.post(f"/api/orders/{self.order.id}/cancel/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELED)

    def test_confirm_payment_returns_404_for_foreign_order(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(f"/api/orders/{self.other_order.id}/confirm-payment/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
