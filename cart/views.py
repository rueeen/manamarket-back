from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from products.models import Product

from .models import Cart, CartItem
from .serializers import (
    AddCartItemSerializer,
    CartSerializer,
    UpdateCartItemSerializer,
)


class CartMixin:
    def get_cart(self):
        cart, _ = Cart.objects.prefetch_related(
            "items__product"
        ).get_or_create(
            user=self.request.user
        )
        return cart

    def serialize_cart(self, cart, status_code=status.HTTP_200_OK):
        serializer = CartSerializer(
            cart,
            context={"request": self.request},
        )
        return Response(serializer.data, status=status_code)


class CartView(CartMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        cart = self.get_cart()
        return self.serialize_cart(cart)


class AddCartItemView(CartMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = AddCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cart = self.get_cart()
        product = serializer.validated_data["product"]
        quantity = serializer.validated_data["quantity"]

        item, created = CartItem.objects.select_for_update().get_or_create(
            cart=cart,
            product=product,
            defaults={"quantity": quantity},
        )

        if created:
            locked_product = Product.objects.select_for_update().get(
                pk=product.pk
            )
            if locked_product.available_stock < quantity:
                item.delete()
                return Response(
                    {"quantity": ["Stock insuficiente."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not created:
            new_quantity = item.quantity + quantity

            if product.available_stock < new_quantity:
                return Response(
                    {
                        "quantity": [
                            "Stock insuficiente para actualizar la cantidad."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            item.quantity = new_quantity
            item.save(update_fields=["quantity"])

        cart.refresh_from_db()

        return self.serialize_cart(
            cart,
            status_code=status.HTTP_201_CREATED,
        )


class UpdateCartItemView(CartMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def patch(self, request, item_id):
        cart = self.get_cart()

        try:
            item = cart.items.select_related("product").get(pk=item_id)
        except CartItem.DoesNotExist:
            return Response(
                {"detail": "Item no encontrado en el carrito."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UpdateCartItemSerializer(
            data=request.data,
            context={"cart_item": item},
        )
        serializer.is_valid(raise_exception=True)

        item.quantity = serializer.validated_data["quantity"]
        item.save(update_fields=["quantity"])

        cart.refresh_from_db()

        return self.serialize_cart(cart)


class RemoveCartItemView(CartMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def delete(self, request, item_id):
        cart = self.get_cart()

        try:
            item = cart.items.get(pk=item_id)
        except CartItem.DoesNotExist:
            return Response(
                {"detail": "Item no encontrado en el carrito."},
                status=status.HTTP_404_NOT_FOUND,
            )

        item.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class ClearCartView(CartMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def delete(self, request):
        cart = self.get_cart()
        cart.items.all().delete()
        cart.touch()

        return Response(status=status.HTTP_204_NO_CONTENT)
