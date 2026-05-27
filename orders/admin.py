from django.contrib import admin

from .models import (
    AssistedPurchaseItem,
    AssistedPurchaseOrder,
    Order,
    OrderItem,
)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "product",
        "quantity",
        "unit_price_clp",
        "subtotal_clp",
        "unit_cost_clp",
        "total_cost_clp",
        "gross_profit_clp",
        "product_name_snapshot",
        "product_type_snapshot",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "subtotal_clp",
        "shipping_clp",
        "discount_clp",
        "total_clp",
        "stock_consumed",
        "created_at",
    )
    list_filter = (
        "status",
        "stock_consumed",
        "created_at",
    )
    search_fields = (
        "id",
        "user__username",
        "user__email",
        "items__product_name_snapshot",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "paid_at",
        "cancelled_at",
    )
    inlines = [OrderItemInline]


class AssistedPurchaseItemInline(admin.TabularInline):
    model = AssistedPurchaseItem
    extra = 0
    readonly_fields = ("subtotal_usd",)


@admin.register(AssistedPurchaseOrder)
class AssistedPurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "supplier",
        "status",
        "subtotal_usd",
        "total_real_cost_clp",
        "total_customer_clp",
        "profit_clp",
        "created_at",
    )
    list_filter = (
        "status",
        "supplier",
        "created_at",
    )
    search_fields = (
        "id",
        "user__username",
        "user__email",
        "items__external_name",
        "items__product__name",
    )
    readonly_fields = (
        "subtotal_usd",
        "total_real_cost_clp",
        "total_customer_clp",
        "profit_clp",
        "created_at",
        "updated_at",
    )
    inlines = [AssistedPurchaseItemInline]
