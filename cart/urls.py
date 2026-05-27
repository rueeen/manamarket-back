from django.urls import path

from .views import (
    AddCartItemView,
    CartView,
    ClearCartView,
    RemoveCartItemView,
    UpdateCartItemView,
)

app_name = "cart"

urlpatterns = [
    path("", CartView.as_view(), name="detail"),
    path("items/", AddCartItemView.as_view(), name="add_item"),
    path("items/<int:item_id>/", UpdateCartItemView.as_view(), name="update_item"),
    path("items/<int:item_id>/remove/",
         RemoveCartItemView.as_view(), name="remove_item"),
    path("clear/", ClearCartView.as_view(), name="clear"),
]
