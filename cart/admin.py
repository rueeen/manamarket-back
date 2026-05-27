from django.contrib import admin

from .models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ("product", "quantity", "subtotal_clp")

    def subtotal_clp(self, obj):
        return obj.subtotal

    subtotal_clp.short_description = "Subtotal CLP"


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("user", "total_items", "total_clp",
                    "created_at", "updated_at")
    readonly_fields = ("user", "total_items", "total_clp",
                       "created_at", "updated_at")
    inlines = [CartItemInline]
    search_fields = ("user__username", "user__email")
    list_select_related = ("user",)

    def total_items(self, obj):
        return obj.items.count()

    total_items.short_description = "Items"

    def total_clp(self, obj):
        return obj.total

    total_clp.short_description = "Total CLP"
