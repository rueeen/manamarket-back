from rest_framework import serializers

from products.models import Product

from .models import Cart, CartItem, get_product_sale_price_clp


class CartItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    product_stock = serializers.IntegerField(
        source="product.stock",
        read_only=True,
    )
    product_stock_reserved = serializers.IntegerField(source="product.stock_reserved", read_only=True)
    product_available_stock = serializers.IntegerField(source="product.available_stock", read_only=True)
    product_is_active = serializers.BooleanField(
        source="product.is_active",
        read_only=True,
    )
    unit_price_clp = serializers.IntegerField(read_only=True)
    price_clp = serializers.IntegerField(source="unit_price_clp", read_only=True)
    subtotal_clp = serializers.IntegerField(
        source="subtotal",
        read_only=True,
    )

    class Meta:
        model = CartItem
        fields = (
            "id",
            "product",
            "product_name",
            "product_stock",
            "product_stock_reserved",
            "product_available_stock",
            "product_is_active",
            "quantity",
            "unit_price_clp",
            "price_clp",
            "subtotal_clp",
        )
        read_only_fields = (
            "id",
            "product_name",
            "product_stock",
            "product_is_active",
            "unit_price_clp",
            "price_clp",
            "subtotal_clp",
        )


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total_clp = serializers.IntegerField(source="total", read_only=True)
    total_items = serializers.IntegerField(read_only=True)

    class Meta:
        model = Cart
        fields = (
            "id",
            "items",
            "total_items",
            "total_clp",
            "updated_at",
        )


class AddCartItemSerializer(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source="product",
    )
    quantity = serializers.IntegerField(min_value=1)

    def validate_product(self, product):
        if not product.is_active:
            raise serializers.ValidationError(
                "No se puede comprar un producto inactivo."
            )

        if get_product_sale_price_clp(product) <= 0:
            raise serializers.ValidationError(
                "El producto no tiene precio configurado."
            )

        return product

    def validate(self, attrs):
        product = attrs["product"]
        quantity = attrs["quantity"]

        if product.available_stock < quantity:
            raise serializers.ValidationError({
                "quantity": f"Stock insuficiente. Disponible actualmente: {product.available_stock}."
            })

        return attrs


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)

    def validate_quantity(self, quantity):
        item = self.context.get("cart_item")

        if item and item.product.available_stock < quantity:
            raise serializers.ValidationError(
                f"Stock insuficiente. Disponible actualmente: {item.product.available_stock}."
            )

        return quantity
