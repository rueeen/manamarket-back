from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import (
    BundleItem,
    Category,
    ProductTypeConfig,
    InventoryLot,
    KardexMovement,
    MTGCard,
    PricingSettings,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    SealedProduct,
    ServiceFeeConfig,
    ShippingConfig,
    SingleCard,
    Supplier,
    ExchangeRateConfig,
)
from .purchase_order_services import (
    calculate_suggested_price_from_real_cost,
    get_active_exchange_rate,
    get_active_pricing_settings,
    recalculate_purchase_order,
)


D = Decimal
TOLERANCE = D("0.02")


class MTGCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = MTGCard
        exclude = ("raw_data",)


class SingleCardSerializer(serializers.ModelSerializer):
    mtg_card = MTGCardSerializer(read_only=True)
    mtg_card_id = serializers.PrimaryKeyRelatedField(
        source="mtg_card",
        queryset=MTGCard.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = SingleCard
        fields = (
            "mtg_card",
            "mtg_card_id",
            "condition",
            "language",
            "is_foil",
            "edition",
            "price_usd_reference",
        )


class SealedProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = SealedProduct
        fields = (
            "sealed_kind",
            "set_code",
        )


class BundleItemSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(
        source="item.name",
        read_only=True,
    )
    item_price_clp = serializers.IntegerField(
        source="item.computed_price_clp",
        read_only=True,
    )
    subtotal_clp = serializers.SerializerMethodField()

    class Meta:
        model = BundleItem
        fields = (
            "id",
            "item",
            "item_name",
            "item_price_clp",
            "quantity",
            "subtotal_clp",
        )

    def get_subtotal_clp(self, obj):
        return int(obj.quantity or 0) * int(obj.item.computed_price_clp or 0)


class ProductSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    product_type_display = serializers.CharField(source="get_product_type_display", read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=Category.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    product_type_config = serializers.PrimaryKeyRelatedField(read_only=True)
    product_type_config_name = serializers.CharField(source="product_type_config.name", read_only=True)
    product_type_config_id = serializers.PrimaryKeyRelatedField(
        source="product_type_config",
        queryset=ProductTypeConfig.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    single_card = SingleCardSerializer(read_only=True)
    sealed_product = SealedProductSerializer(read_only=True)
    bundle_items = BundleItemSerializer(many=True, read_only=True)

    computed_price_clp = serializers.IntegerField(read_only=True)
    available_stock = serializers.SerializerMethodField()
    cost_real_clp = serializers.IntegerField(read_only=True)
    margin_clp = serializers.SerializerMethodField()
    margin_percentage = serializers.SerializerMethodField()
    suggested_price_clp = serializers.SerializerMethodField()
    margen_clp = serializers.SerializerMethodField()
    margen_pct = serializers.SerializerMethodField()
    is_profitable = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    image = serializers.URLField(required=False, allow_blank=True, default='')

    class Meta:
        model = Product
        fields = (
            "id",
            "category",
            "category_id",
            "category_name",
            "category_slug",
            "name",
            "description",
            "product_type",
            "product_type_config",
            "product_type_config_id",
            "product_type_config_name",
            "product_type_display",
            "price_clp",
            "computed_price_clp",
            "stock",
            "stock_reserved",
            "available_stock",
            "stock_minimum",
            "average_cost_clp",
            "last_purchase_cost_clp",
            "cost_real_clp",
            "margin_clp",
            "margin_percentage",
            "suggested_price_clp",
            "margen_clp",
            "margen_pct",
            "is_profitable",
            "image",
            "image_file",
            "image_url",
            "is_active",
            "notes",
            "price_external_usd",
            "exchange_rate_usd_clp",
            "pricing_source",
            "pricing_last_update",
            "created_at",
            "updated_at",
            "single_card",
            "sealed_product",
            "bundle_items",
        )
        read_only_fields = (
            "id",
            "computed_price_clp",
            "cost_real_clp",
            "margin_clp",
            "margin_percentage",
            "suggested_price_clp",
            "is_profitable",
            "created_at",
            "updated_at",
            "single_card",
            "sealed_product",
            "bundle_items",
        )


    def _get_margin_values(self, obj):
        price = int((getattr(obj, "price_clp", 0) or getattr(obj, "computed_price_clp", 0) or 0))
        cost = int(
            (
                getattr(obj, "cost_real_clp", 0)
                or getattr(obj, "average_cost_clp", 0)
                or getattr(obj, "last_purchase_cost_clp", 0)
                or 0
            )
        )

        if cost > 0:
            margin_clp = price - cost
            margin_percentage = round((margin_clp / cost) * 100, 2)
        else:
            margin_clp = 0
            margin_percentage = 0.0

        is_profitable = cost <= 0 or price >= cost
        return margin_clp, margin_percentage, is_profitable

    def get_margin_clp(self, obj):
        margin_clp, _, _ = self._get_margin_values(obj)
        return margin_clp

    def get_margin_percentage(self, obj):
        _, margin_percentage, _ = self._get_margin_values(obj)
        return margin_percentage

    def get_is_profitable(self, obj):
        _, _, is_profitable = self._get_margin_values(obj)
        return is_profitable

    def get_margen_clp(self, obj):
        margin_clp, _, _ = self._get_margin_values(obj)
        return margin_clp

    def get_margen_pct(self, obj):
        _, margin_percentage, _ = self._get_margin_values(obj)
        return margin_percentage

    def _get_pricing_settings_cached(self):
        cache_key = "_active_pricing_settings"
        if cache_key not in self.context:
            self.context[cache_key] = get_active_pricing_settings()
        return self.context[cache_key]

    def get_suggested_price_clp(self, obj):
        pricing_settings = self._get_pricing_settings_cached()
        return int(
            calculate_suggested_price_from_real_cost(
                int(obj.cost_real_clp or 0),
                pricing_settings=pricing_settings,
            )
            or 0
        )

    def get_available_stock(self, obj):
        return obj.available_stock

    def get_image_url(self, obj):
        if obj.image_file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.image_file.url)
            return obj.image_file.url
        return obj.image or ""



class ProductPublicSerializer(serializers.ModelSerializer):
    """Serializer para clientes y visitantes. Sin datos de costo ni margen."""
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    product_type_display = serializers.CharField(source="get_product_type_display", read_only=True)
    product_type_config_name = serializers.CharField(source="product_type_config.name", read_only=True)
    computed_price_clp = serializers.IntegerField(read_only=True)
    available_stock = serializers.SerializerMethodField()
    single_card = SingleCardSerializer(read_only=True)
    sealed_product = SealedProductSerializer(read_only=True)
    bundle_items = BundleItemSerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "category",
            "category_name",
            "category_slug",
            "name",
            "description",
            "product_type",
            "product_type_display",
            "product_type_config",
            "product_type_config_name",
            "price_clp",
            "computed_price_clp",
            "available_stock",
            "image",
            "image_file",
            "image_url",
            "is_active",
            "pricing_source",
            "pricing_last_update",
            "created_at",
            "updated_at",
            "single_card",
            "sealed_product",
            "bundle_items",
        )
        read_only_fields = fields

    def get_available_stock(self, obj):
        return obj.available_stock

    def get_image_url(self, obj):
        if obj.image_file:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.image_file.url)
            return obj.image_file.url
        return obj.image or ""


class ProductCatalogSerializer(serializers.ModelSerializer):
    category = serializers.StringRelatedField(read_only=True)
    computed_price_clp = serializers.IntegerField(read_only=True)
    available_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "category",
            "product_type",
            "computed_price_clp",
            "stock",
            "stock_reserved",
            "available_stock",
            "image",
            "is_active",
        )

    def get_available_stock(self, obj):
        return obj.available_stock


class CategorySerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "is_active",
            "sort_order",
            "parent",
            "products_count",
            "created_at",
            "updated_at",
        )


class ProductTypeConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductTypeConfig
        fields = "__all__"


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = "__all__"


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )

    class Meta:
        model = PurchaseOrderItem
        fields = (
            "id",
            "product",
            "product_name",
            "raw_description",
            "normalized_card_name",
            "set_name_detected",
            "style_condition",
            "quantity_ordered",
            "quantity_received",
            "unit_price_original",
            "line_total_original",
            "unit_price_clp",
            "line_total_clp",
            "allocated_extra_cost_clp",
            "allocated_tax_clp",
            "real_unit_cost_clp",
            "margin_percent",
            "suggested_sale_price_clp",
            "sale_price_to_apply_clp",
            "scryfall_id",
            "scryfall_data",
        )
        read_only_fields = (
            "id",
            "product_name",
            "quantity_received",
            "unit_price_clp",
            "line_total_clp",
            "allocated_extra_cost_clp",
            "allocated_tax_clp",
            "real_unit_cost_clp",
            "suggested_sale_price_clp",
        )


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(
        source="supplier.name",
        read_only=True,
    )
    items = PurchaseOrderItemSerializer(many=True)
    order_number = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    missing_products_count = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "order_number",
            "supplier",
            "supplier_name",
            "external_reference",
            "status",
            "source_store",
            "purchase_order_type",
            "original_currency",
            "exchange_rate_snapshot_clp",
            "subtotal_original",
            "shipping_original",
            "sales_tax_original",
            "total_original",
            "import_duties_clp",
            "customs_fee_clp",
            "handling_fee_clp",
            "paypal_variation_clp",
            "other_costs_clp",
            "subtotal_clp",
            "shipping_clp",
            "sales_tax_clp",
            "total_origin_clp",
            "total_extra_costs_clp",
            "grand_total_clp",
            "notes",
            "update_prices_on_receive",
            "missing_products_count",
            "created_at",
            "updated_at",
            "received_at",
            "items",
        )
        read_only_fields = (
            "id",
            "exchange_rate_snapshot_clp",
            "subtotal_clp",
            "shipping_clp",
            "sales_tax_clp",
            "total_origin_clp",
            "total_extra_costs_clp",
            "grand_total_clp",
            "missing_products_count",
            "created_at",
            "updated_at",
            "received_at",
        )

    def get_missing_products_count(self, obj):
        return obj.items.filter(product__isnull=True).count()

    def validate(self, attrs):
        items = attrs.get("items")

        if self.instance is None and not items:
            raise serializers.ValidationError({
                "items": "Debes agregar al menos 1 item."
            })

        supplier = attrs.get("supplier") or getattr(
            self.instance, "supplier", None)

        if not supplier:
            raise serializers.ValidationError({
                "supplier": "Este campo es requerido."
            })

        currency = (
            attrs.get("original_currency")
            or getattr(self.instance, "original_currency", "CLP")
            or "CLP"
        ).upper()

        if currency not in ("CLP", "USD"):
            raise serializers.ValidationError({
                "original_currency": "Debe ser CLP o USD."
            })

        if currency == "USD":
            get_active_exchange_rate()

        purchase_order_type = (
            attrs.get("purchase_order_type")
            or getattr(self.instance, "purchase_order_type", PurchaseOrder.PurchaseOrderType.GENERAL)
        )

        for item in items or []:
            if purchase_order_type == PurchaseOrder.PurchaseOrderType.GENERAL and not item.get("product"):
                raise serializers.ValidationError({
                    "items": "Las órdenes generales deben seleccionar productos existentes desde el mantenedor."
                })

            qty = int(item.get("quantity_ordered") or 0)

            if qty <= 0:
                raise serializers.ValidationError({
                    "items": "quantity_ordered debe ser mayor a 0."
                })

            unit_price_original = item.get("unit_price_original")

            if unit_price_original is None or unit_price_original < 0:
                raise serializers.ValidationError({
                    "items": "unit_price_original debe ser mayor o igual a 0."
                })

            if (
                purchase_order_type == PurchaseOrder.PurchaseOrderType.GENERAL
                and unit_price_original <= 0
            ):
                raise serializers.ValidationError({
                    "items": "El costo unitario de compra debe ser mayor a 0."
                })

            expected = (unit_price_original * qty).quantize(D("0.01"))
            line_total = item.get("line_total_original")

            if line_total is None:
                item["line_total_original"] = expected
                continue

            if abs(line_total - expected) > TOLERANCE:
                raise serializers.ValidationError({
                    "items": (
                        "line_total_original debe coincidir con "
                        "quantity_ordered * unit_price_original."
                    )
                })

        return attrs

    def _generate_order_number(self):
        date_prefix = timezone.localdate().strftime("%Y%m%d")
        base = f"PO-{date_prefix}-"

        last_po = (
            PurchaseOrder.objects.filter(order_number__startswith=base)
            .order_by("-order_number")
            .first()
        )

        sequence = (
            int(last_po.order_number.split("-")[-1]) + 1
            if last_po
            else 1
        )

        return f"{base}{sequence:04d}"

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")

        order_number = str(
            validated_data.get("order_number") or ""
        ).strip()

        validated_data["order_number"] = (
            order_number or self._generate_order_number()
        )

        currency = validated_data.get("original_currency", "CLP")

        validated_data["exchange_rate_snapshot_clp"] = (
            1
            if currency == "CLP"
            else get_active_exchange_rate()
        )

        if validated_data.get("status") == PurchaseOrder.Status.RECEIVED:
            raise serializers.ValidationError({
                "status": "No se puede crear una orden recibida directamente."
            })

        order = PurchaseOrder.objects.create(**validated_data)

        for item_data in items_data:
            PurchaseOrderItem.objects.create(
                purchase_order=order,
                **item_data,
            )

        recalculate_purchase_order(order)

        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)

        if instance.status == PurchaseOrder.Status.RECEIVED:
            raise serializers.ValidationError({
                "status": "No se puede editar una orden ya recibida."
            })

        if "original_currency" in validated_data:
            currency = validated_data["original_currency"]

            validated_data["exchange_rate_snapshot_clp"] = (
                1
                if currency == "CLP"
                else get_active_exchange_rate()
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if items_data is not None:
            instance.items.all().delete()

            for item_data in items_data:
                PurchaseOrderItem.objects.create(
                    purchase_order=instance,
                    **item_data,
                )

        recalculate_purchase_order(instance)

        return instance


class KardexMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = KardexMovement
        fields = (
            "id",
            "product",
            "product_name",
            "movement_type",
            "quantity",
            "previous_stock",
            "new_stock",
            "unit_cost_clp",
            "unit_price_clp",
            "reference_type",
            "reference_id",
            "reference_label",
            "notes",
            "created_by",
            "created_by_username",
            "created_at",
        )
        read_only_fields = fields


class InventoryLotSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )

    class Meta:
        model = InventoryLot
        fields = (
            "id",
            "product",
            "product_name",
            "purchase_order_item",
            "quantity_initial",
            "quantity_remaining",
            "unit_cost_clp",
            "received_at",
            "created_at",
        )
        read_only_fields = fields


class PricingSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingSettings
        fields = "__all__"


class ExchangeRateConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRateConfig
        fields = "__all__"


class ServiceFeeConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceFeeConfig
        fields = "__all__"


class ShippingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShippingConfig
        fields = "__all__"
