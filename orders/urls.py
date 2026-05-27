from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AssistedPurchaseOrderViewSet, OrderViewSet, ShippingQuoteView

app_name = "orders"

router = DefaultRouter()
router.register("assisted", AssistedPurchaseOrderViewSet,
                basename="assisted-order")
router.register("", OrderViewSet, basename="order")

urlpatterns = [
    path('shipping-quote/', ShippingQuoteView.as_view(), name='shipping-quote'),
    *router.urls,
]
