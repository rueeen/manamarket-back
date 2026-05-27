from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum

from products.models import Product


def get_product_sale_price_clp(product: Product) -> Decimal:
    for value in (
        product.computed_price_clp,
        product.price_clp,
        product.suggested_price_clp,
    ):
        if value and value > 0:
            return Decimal(value)
    return Decimal("0")


class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Cart({self.user})"

    def touch(self):
        self.save(update_fields=['updated_at'])

    @property
    def total(self) -> Decimal:
        return sum(
            (item.subtotal for item in self.items.select_related("product")),
            Decimal("0"),
        )

    @property
    def total_items(self) -> int:
        result = self.items.aggregate(total=Sum("quantity"))["total"]
        return result or 0


class CartItem(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="cart_items",
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product"],
                name="unique_cart_product",
            )
        ]

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError(
                {"quantity": "La cantidad debe ser mayor a 0."})

    def __str__(self) -> str:
        return f"{self.product.name} x {self.quantity}"

    @property
    def unit_price_clp(self) -> Decimal:
        return get_product_sale_price_clp(self.product)

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price_clp * self.quantity
