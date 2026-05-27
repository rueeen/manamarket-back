from django.contrib import admin

from .models import (
    BundleItem,
    Category,
    ExchangeRateConfig,
    InventoryLot,
    KardexMovement,
    MTGCard,
    PricingSettings,
    Product,
    ProductTypeConfig,
    PurchaseOrder,
    PurchaseOrderItem,
    SealedProduct,
    ServiceFeeConfig,
    ShippingConfig,
    SingleCard,
    Supplier,
)


class SingleCardInline(admin.StackedInline):
    model = SingleCard
    extra = 0
    autocomplete_fields = ("mtg_card",)
    fields = (
        "mtg_card",
        "condition",
        "language",
        "is_foil",
        "edition",
        "price_usd_reference",
    )


class SealedProductInline(admin.StackedInline):
    model = SealedProduct
    extra = 0
    fields = (
        "sealed_kind",
        "set_code",
    )


class BundleItemInline(admin.TabularInline):
    model = BundleItem
    fk_name = "bundle"
    extra = 0
    autocomplete_fields = ("item",)
    fields = (
        "item",
        "quantity",
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "created_at",
    )
    search_fields = (
        "name",
        "slug",
        "description",
    )
    prepopulated_fields = {
        "slug": ("name",),
    }
    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(MTGCard)
class MTGCardAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "set_code",
        "collector_number",
        "rarity",
        "released_at",
    )
    list_filter = (
        "rarity",
        "set_code",
        "released_at",
    )
    search_fields = (
        "name",
        "printed_name",
        "scryfall_id",
        "set_name",
        "set_code",
        "collector_number",
        "type_line",
    )
    readonly_fields = (
        "scryfall_id",
        "raw_data",
        "created_at",
        "updated_at",
    )
    ordering = (
        "name",
        "set_code",
        "collector_number",
    )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "product_type_config",
        "product_type",
        "price_clp",
        "computed_price_display",
        "stock",
        "stock_reserved",
        "available_stock_display",
        "stock_minimum",
        "cost_real_display",
        "margin_display",
        "is_active",
        "pricing_source",
        "updated_at",
    )
    list_filter = (
        "product_type",
        "product_type_config",
        "is_active",
        "pricing_source",
        "created_at",
        "updated_at",
        "stock_reserved",
    )
    search_fields = (
        "name",
        "description",
        "single_card__mtg_card__name",
        "single_card__mtg_card__printed_name",
        "single_card__mtg_card__scryfall_id",
        "single_card__mtg_card__set_code",
        "single_card__mtg_card__collector_number",
    )
    autocomplete_fields = (
        "category",
        "product_type_config",
    )
    readonly_fields = (
        "computed_price_display",
        "cost_real_display",
        "margin_display",
        "margin_percentage_display",
        "suggested_price_display",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Información general",
            {
                "fields": (
                    "category",
                    "product_type_config",
                    "name",
                    "description",
                    "product_type",
                    "image",
                    "is_active",
                    "notes",
                )
            },
        ),
        (
            "Precio y stock",
            {
                "fields": (
                    "price_clp",
                    "computed_price_display",
                    "suggested_price_display",
                    "stock",
                    "stock_reserved",
                    "available_stock_display",
                    "stock_minimum",
                )
            },
        ),
        (
            "Costos y margen",
            {
                "fields": (
                    "average_cost_clp",
                    "last_purchase_cost_clp",
                    "cost_real_display",
                    "margin_display",
                    "margin_percentage_display",
                )
            },
        ),
        (
            "Pricing",
            {
                "fields": (
                    "pricing_source",
                    "pricing_last_update",
                )
            },
        ),
        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    inlines = (
        SingleCardInline,
        SealedProductInline,
        BundleItemInline,
    )

    def computed_price_display(self, obj):
        return obj.computed_price_clp

    computed_price_display.short_description = "Precio calculado CLP"

    def cost_real_display(self, obj):
        return obj.cost_real_clp

    cost_real_display.short_description = "Costo real CLP"

    def margin_display(self, obj):
        return obj.margin_clp

    margin_display.short_description = "Margen CLP"

    def margin_percentage_display(self, obj):
        return f"{obj.margin_percentage}%"

    margin_percentage_display.short_description = "Margen %"

    def suggested_price_display(self, obj):
        return obj.suggested_price_clp

    suggested_price_display.short_description = "Precio sugerido CLP"

    def available_stock_display(self, obj):
        return obj.available_stock

    available_stock_display.short_description = "Stock disponible"


@admin.register(ProductTypeConfig)
class ProductTypeConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "sort_order", "uses_scryfall", "is_sealed", "is_bundle", "is_service")
    list_filter = ("is_active", "uses_scryfall", "is_sealed", "is_bundle", "is_service")
    search_fields = ("name", "slug", "description")


@admin.register(SingleCard)
class SingleCardAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "mtg_card",
        "condition",
        "language",
        "is_foil",
        "edition",
        "price_usd_reference",
    )
    list_filter = (
        "condition",
        "language",
        "is_foil",
    )
    search_fields = (
        "product__name",
        "mtg_card__name",
        "mtg_card__printed_name",
        "mtg_card__scryfall_id",
        "mtg_card__set_code",
        "mtg_card__collector_number",
    )
    autocomplete_fields = (
        "product",
        "mtg_card",
    )


@admin.register(SealedProduct)
class SealedProductAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "sealed_kind",
        "set_code",
    )
    list_filter = (
        "sealed_kind",
        "set_code",
    )
    search_fields = (
        "product__name",
        "set_code",
    )
    autocomplete_fields = (
        "product",
    )


@admin.register(BundleItem)
class BundleItemAdmin(admin.ModelAdmin):
    list_display = (
        "bundle",
        "item",
        "quantity",
        "line_price_display",
    )
    search_fields = (
        "bundle__name",
        "item__name",
    )
    autocomplete_fields = (
        "bundle",
        "item",
    )

    def line_price_display(self, obj):
        return obj.quantity * obj.item.computed_price_clp

    line_price_display.short_description = "Subtotal CLP"


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "country",
        "email",
        "phone",
        "is_active",
        "created_at",
    )
    list_filter = (
        "country",
        "is_active",
        "created_at",
    )
    search_fields = (
        "name",
        "rut",
        "contact_name",
        "email",
        "phone",
        "country",
        "website",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    autocomplete_fields = (
        "product",
    )
    fields = (
        "product",
        "raw_description",
        "normalized_card_name",
        "style_condition",
        "quantity_ordered",
        "quantity_received",
        "unit_price_original",
        "line_total_original",
        "unit_price_clp",
        "line_total_clp",
        "real_unit_cost_clp",
        "suggested_sale_price_clp",
        "sale_price_to_apply_clp",
    )
    readonly_fields = (
        "line_total_original",
        "line_total_clp",
    )


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "supplier",
        "status",
        "original_currency",
        "total_original",
        "grand_total_clp",
        "update_prices_on_receive",
        "created_at",
        "received_at",
    )
    list_filter = (
        "status",
        "supplier",
        "original_currency",
        "update_prices_on_receive",
        "created_at",
        "received_at",
    )
    search_fields = (
        "order_number",
        "external_reference",
        "supplier__name",
        "source_store",
        "notes",
    )
    autocomplete_fields = (
        "supplier",
        "created_by",
        "received_by",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "received_at",
    )
    inlines = (
        PurchaseOrderItemInline,
    )


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "purchase_order",
        "product",
        "normalized_card_name",
        "style_condition",
        "quantity_ordered",
        "quantity_received",
        "unit_price_original",
        "line_total_original",
        "real_unit_cost_clp",
        "suggested_sale_price_clp",
        "sale_price_to_apply_clp",
    )
    list_filter = (
        "style_condition",
        "purchase_order__status",
    )
    search_fields = (
        "purchase_order__order_number",
        "product__name",
        "raw_description",
        "normalized_card_name",
        "set_name_detected",
        "scryfall_id",
    )
    autocomplete_fields = (
        "purchase_order",
        "product",
    )
    readonly_fields = (
        "line_total_original",
        "line_total_clp",
    )


@admin.register(KardexMovement)
class KardexMovementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "movement_type",
        "quantity",
        "previous_stock",
        "new_stock",
        "unit_cost_clp",
        "unit_price_clp",
        "reference_type",
        "reference_id",
        "created_by",
        "created_at",
    )
    list_filter = (
        "movement_type",
        "reference_type",
        "created_at",
    )
    search_fields = (
        "product__name",
        "reference_type",
        "reference_id",
        "reference_label",
        "notes",
        "created_by__username",
    )
    autocomplete_fields = (
        "product",
        "created_by",
    )
    readonly_fields = (
        "created_at",
    )


@admin.register(InventoryLot)
class InventoryLotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "purchase_order_item",
        "quantity_initial",
        "quantity_remaining",
        "unit_cost_clp",
        "received_at",
        "created_at",
    )
    list_filter = (
        "received_at",
        "created_at",
    )
    search_fields = (
        "product__name",
        "purchase_order_item__purchase_order__order_number",
        "purchase_order_item__raw_description",
        "purchase_order_item__normalized_card_name",
    )
    autocomplete_fields = (
        "product",
        "purchase_order_item",
    )
    readonly_fields = (
        "created_at",
    )


@admin.register(ExchangeRateConfig)
class ExchangeRateConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "usd_to_clp",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "created_at",
    )
    search_fields = (
        "name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(ServiceFeeConfig)
class ServiceFeeConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "percentage",
        "flat_fee_clp",
        "is_active",
    )
    list_filter = (
        "is_active",
    )
    search_fields = (
        "name",
    )


@admin.register(ShippingConfig)
class ShippingConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "base_clp",
        "per_item_clp",
        "is_active",
    )
    list_filter = (
        "is_active",
    )
    search_fields = (
        "name",
    )


@admin.register(PricingSettings)
class PricingSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "usd_to_clp",
        "usd_to_clp_real",
        "usd_to_clp_store",
        "default_margin",
        "min_margin",
        "import_factor",
        "risk_factor",
        "margin_factor",
        "vat_percentage",
        "rounding_to",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "updated_at",
    )
    search_fields = (
        "name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
