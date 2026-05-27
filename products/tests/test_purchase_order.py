from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from products.models import InventoryLot, KardexMovement, PricingSettings, Product, Supplier
from products.purchase_order_services import receive_purchase_order
from products.serializers import PurchaseOrderSerializer


class PurchaseOrderFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tester", password="secret")
        self.supplier = Supplier.objects.create(name="Proveedor Test")
        self.product = Product.objects.create(name="Producto Test", product_type=Product.ProductType.SINGLE, price_clp=0, stock=0)

    def _payload(self, currency="CLP"):
        return {
            "supplier": self.supplier.id,
            "original_currency": currency,
            "shipping_original": "10.00" if currency == "USD" else "1000.00",
            "sales_tax_original": "5.00" if currency == "USD" else "500.00",
            "import_duties_clp": 300,
            "customs_fee_clp": 200,
            "handling_fee_clp": 100,
            "paypal_variation_clp": 50,
            "other_costs_clp": 350,
            "items": [
                {
                    "product": self.product.id,
                    "quantity_ordered": 2,
                    "unit_price_original": "100.00" if currency == "USD" else "1000.00",
                    "line_total_original": "200.00" if currency == "USD" else "2000.00",
                    "margin_percent": "35.00",
                }
            ],
        }

    def _create_po(self, currency="CLP"):
        serializer = PurchaseOrderSerializer(data=self._payload(currency))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save(created_by=self.user)

    def test_01_create_clp_order(self):
        po = self._create_po("CLP")
        self.assertEqual(po.original_currency, "CLP")

    def test_02_create_usd_order_with_active_exchange_rate(self):
        PricingSettings.objects.create(name="Main", usd_to_clp=Decimal("1000"), is_active=True)
        po = self._create_po("USD")
        self.assertEqual(po.original_currency, "USD")

    def test_03_exchange_rate_snapshot_clp(self):
        PricingSettings.objects.create(name="Main", usd_to_clp=Decimal("1000"), is_active=True)
        po = self._create_po("USD")
        self.assertEqual(po.exchange_rate_snapshot_clp, Decimal("1000.00"))

    def test_04_subtotal_clp_calculation(self):
        po = self._create_po("CLP")
        self.assertEqual(po.subtotal_clp, 2000)

    def test_05_proportional_extra_cost_distribution(self):
        payload = self._payload("CLP")
        payload["items"].append({
            "product": self.product.id,
            "quantity_ordered": 1,
            "unit_price_original": "1000.00",
            "line_total_original": "1000.00",
            "margin_percent": "35.00",
        })
        serializer = PurchaseOrderSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        po = serializer.save(created_by=self.user)
        item1, item2 = po.items.order_by("id")
        self.assertGreater(item1.allocated_extra_cost_clp, item2.allocated_extra_cost_clp)

    def test_06_real_unit_cost_clp(self):
        po = self._create_po("CLP")
        item = po.items.first()
        self.assertEqual(item.real_unit_cost_clp, 2500)

    def test_07_suggested_sale_price_clp(self):
        PricingSettings.objects.create(name="Main", usd_to_clp=Decimal("1000"), rounding_to=100, is_active=True)
        po = self._create_po("CLP")
        item = po.items.first()
        self.assertGreater(item.suggested_sale_price_clp, item.real_unit_cost_clp)

    def test_08_not_allow_create_order_without_items(self):
        payload = self._payload("CLP")
        payload["items"] = []
        serializer = PurchaseOrderSerializer(data=payload)
        self.assertFalse(serializer.is_valid())

    def test_09_not_allow_receive_twice(self):
        po = self._create_po("CLP")
        receive_purchase_order(po, self.user)
        with self.assertRaises(ValidationError):
            receive_purchase_order(po, self.user)

    def test_10_receive_creates_kardex_and_inventory_lot(self):
        po = self._create_po("CLP")
        receive_purchase_order(po, self.user)
        self.assertEqual(KardexMovement.objects.filter(reference_type="PURCHASE_ORDER", reference_id=str(po.id)).count(), 1)
        self.assertEqual(InventoryLot.objects.filter(purchase_order_item__purchase_order=po).count(), 1)
