import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import is_admin_user, is_worker_user
from django.contrib.auth import get_user_model
from payments.models import SalesReceipt
from products.inventory_services import consume_fifo_stock, create_stock_movement
from products.models import KardexMovement, Product

from .models import AssistedPurchaseOrder, Order, ShipmentTracking
from .serializers import (
    AssistedPurchaseOrderPublicSerializer,
    AssistedPurchaseOrderSerializer,
    CreateOrderFromCartSerializer,
    ManualOrderCreateSerializer,
    OrderAdminSerializer,
    OrderSerializer,
)
from .services import cancel_order, confirm_order_payment, create_order_from_cart

User = get_user_model()
logger = logging.getLogger(__name__)


VALID_TRANSITIONS = {
    Order.Status.PAID: [Order.Status.PROCESSING, Order.Status.MANUAL_REVIEW],
    Order.Status.PROCESSING: [Order.Status.SHIPPED, Order.Status.MANUAL_REVIEW],
    Order.Status.SHIPPED: [Order.Status.DELIVERED, Order.Status.MANUAL_REVIEW],
    Order.Status.DELIVERED: [Order.Status.COMPLETED],
    Order.Status.MANUAL_REVIEW: [
        Order.Status.PROCESSING,
        Order.Status.SHIPPED,
        Order.Status.DELIVERED,
    ],
    Order.Status.PAYMENT_FAILED: [Order.Status.MANUAL_REVIEW],
    Order.Status.EXPIRED: [Order.Status.MANUAL_REVIEW],
}

def validation_error_response(exc):
    if hasattr(exc, "message"):
        detail = exc.message
    elif hasattr(exc, "messages"):
        detail = exc.messages
    else:
        detail = str(exc)

    return Response(
        {"detail": detail},
        status=status.HTTP_400_BAD_REQUEST,
    )


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["id", "user__username", "user__email"]

    def get_serializer_class(self):
        if is_admin_user(self.request.user) or is_worker_user(self.request.user):
            return OrderAdminSerializer
        return OrderSerializer

    def get_queryset(self):
        qs = Order.objects.select_related("user").prefetch_related(
            "items__product"
        )

        if is_admin_user(self.request.user) or is_worker_user(self.request.user):
            status_value = self.request.query_params.get("status")

            if status_value:
                qs = qs.filter(status=status_value)

            return qs

        return qs.filter(user=self.request.user)

    @action(detail=False, methods=["post"], url_path="from-cart")
    def from_cart(self, request):
        serializer = CreateOrderFromCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = create_order_from_cart(request.user, **serializer.validated_data)
        except ValidationError as exc:
            return validation_error_response(exc)

        return Response(
            self.get_serializer(order).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="confirm-payment")
    def confirm_payment(self, request, pk=None):
        order = self.get_object()

        if not (is_admin_user(request.user) or is_worker_user(request.user)):
            return Response(
                {"detail": "No autorizado."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            order = confirm_order_payment(order, user=request.user)
        except ValidationError as exc:
            return validation_error_response(exc)

        total = order.total_clp
        tax_rate = Decimal(str(getattr(settings, "TAX_RATE", "0.19")))
        net = int((Decimal(total) / (1 + tax_rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        try:
            SalesReceipt.objects.get_or_create(
                order=order,
                defaults={
                    "payment_transaction": None,
                    "document_type": SalesReceipt.DocumentType.INTERNAL_RECEIPT,
                    "document_number": f"MAN-{order.id}",
                    "net_amount_clp": net,
                    "tax_amount_clp": total - net,
                    "total_amount_clp": total,
                    "raw_data": {"source": "manual_confirmation"},
                },
            )
        except IntegrityError:
            SalesReceipt.objects.get(order=order)

        return Response(self.get_serializer(order).data)


    @action(detail=True, methods=["patch"], url_path="update-status")
    def update_status(self, request, pk=None):
        if not (is_admin_user(request.user) or is_worker_user(request.user)):
            return Response(
                {"detail": "No autorizado."},
                status=status.HTTP_403_FORBIDDEN,
            )

        order = self.get_object()
        new_status = request.data.get("status")
        allowed = VALID_TRANSITIONS.get(order.status, [])

        if new_status not in [s.value for s in allowed]:
            return Response(
                {
                    "detail": f"Transición no permitida: {order.status} → {new_status}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        order.status = new_status
        order.save(update_fields=["status", "updated_at"])

        if new_status == Order.Status.SHIPPED:
            from shipping.chilexpress_service import create_shipment

            try:
                shipment_data = create_shipment(order)
                ShipmentTracking.objects.update_or_create(
                    order=order,
                    defaults={
                        "tracking_number": shipment_data.get("tracking_number", ""),
                        "label_url": shipment_data.get("label_url", ""),
                        "status": ShipmentTracking.Status.CREATED,
                        "raw_response": shipment_data,
                    },
                )
            except Exception as e:
                ShipmentTracking.objects.update_or_create(
                    order=order,
                    defaults={
                        "status": ShipmentTracking.Status.FAILED,
                        "error_message": str(e),
                    },
                )
                # No bloquear el cambio de estado, solo registrar el error

        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        order = self.get_object()

        try:
            order = cancel_order(
                order,
                user=request.user,
                requesting_user=request.user,
            )
        except ValidationError as exc:
            return validation_error_response(exc)

        return Response(self.get_serializer(order).data)

    @action(detail=False, methods=["post"], url_path="manual")
    @transaction.atomic
    def manual(self, request):
        if not (is_admin_user(request.user) or is_worker_user(request.user)):
            return Response(
                {"detail": "No autorizado."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ManualOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            user = User.objects.get(id=data["user_id"])
        except User.DoesNotExist:
            return Response(
                {"detail": f"No existe un usuario con id {data['user_id']}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        item_payloads = data["items"]
        product_ids = [item["product_id"] for item in item_payloads]
        products_queryset = Product.objects.select_for_update().filter(id__in=product_ids)
        products = {product.id: product for product in products_queryset}

        validated_items = []
        subtotal = 0

        for item in item_payloads:
            product = products.get(item["product_id"])
            quantity = item["quantity"]

            if not product:
                return Response(
                    {"detail": "Uno de los productos indicados no existe."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not product.is_active:
                return Response(
                    {"detail": f"El producto '{product.name}' no está activo."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if product.available_stock < quantity:
                return Response(
                    {"detail": f"Stock insuficiente para '{product.name}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            unit_price_clp = item.get("unit_price_clp")
            if unit_price_clp is None:
                unit_price_clp = int(product.computed_price_clp or product.price_clp or 0)

            if unit_price_clp <= 0:
                return Response(
                    {"detail": f"El precio para '{product.name}' debe ser mayor a 0."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            line_subtotal = quantity * unit_price_clp
            subtotal += line_subtotal
            validated_items.append({
                "product": product,
                "quantity": quantity,
                "unit_price_clp": unit_price_clp,
                "subtotal_clp": line_subtotal,
            })

        shipping_clp = data.get("shipping_clp", 0)
        discount_clp = data.get("discount_clp", 0)
        total_clp = max(subtotal + shipping_clp - discount_clp, 0)

        order = Order.objects.create(
            user=user,
            status=Order.Status.PAID,
            subtotal_clp=subtotal,
            shipping_clp=shipping_clp,
            discount_clp=discount_clp,
            total_clp=total_clp,
            stock_consumed=True,
            paid_at=timezone.now(),
        )

        created_order_items = []
        for item in validated_items:
            order_item = order.items.create(
                product=item["product"],
                product_name_snapshot=item["product"].name,
                product_type_snapshot=item["product"].product_type,
                quantity=item["quantity"],
                unit_price_clp=item["unit_price_clp"],
                subtotal_clp=item["subtotal_clp"],
            )
            created_order_items.append((item, order_item))

        for item, order_item in created_order_items:
            product = item["product"]
            total_cost_clp = 0
            unit_cost_clp = 0

            if product.product_type == product.ProductType.BUNDLE:
                bundle_items = list(product.bundle_items.select_related("item").all())
                if bundle_items:
                    for bundle_item in bundle_items:
                        component = Product.objects.select_for_update().get(pk=bundle_item.item_id)
                        component_qty = bundle_item.quantity * item["quantity"]
                        fifo_cost = consume_fifo_stock(component, component_qty)
                        comp_cost = int(fifo_cost["total_cost_clp"])
                        total_cost_clp += comp_cost
                        create_stock_movement(
                            product=component,
                            movement_type=KardexMovement.MovementType.SALE_OUT,
                            quantity=component_qty,
                            created_by=request.user,
                            unit_cost_clp=int(fifo_cost["unit_cost_clp"]),
                            unit_price_clp=0,
                            reference_type="ORDER",
                            reference_id=order.id,
                            reference_label=f"Orden #{order.id} (bundle: {product.name})",
                            notes="Salida por venta manual de bundle",
                        )
                    unit_cost_clp = int(round(total_cost_clp / item["quantity"])) if item["quantity"] else 0
                else:
                    # Bundle sin componentes: consume sobre el bundle mismo
                    fifo_cost = consume_fifo_stock(product, item["quantity"])
                    total_cost_clp = int(fifo_cost["total_cost_clp"])
                    unit_cost_clp = int(fifo_cost["unit_cost_clp"])
                    create_stock_movement(
                        product=product,
                        movement_type=KardexMovement.MovementType.SALE_OUT,
                        quantity=item["quantity"],
                        created_by=request.user,
                        unit_cost_clp=unit_cost_clp,
                        unit_price_clp=item["unit_price_clp"],
                        reference_type="ORDER",
                        reference_id=order.id,
                        reference_label=f"Orden #{order.id}",
                        notes="Salida por venta manual (bundle sin componentes)",
                    )
            else:
                fifo_cost = consume_fifo_stock(product, item["quantity"])
                total_cost_clp = int(fifo_cost["total_cost_clp"])
                unit_cost_clp = int(fifo_cost["unit_cost_clp"])
                create_stock_movement(
                    product=product,
                    movement_type=KardexMovement.MovementType.SALE_OUT,
                    quantity=item["quantity"],
                    created_by=request.user,
                    unit_cost_clp=unit_cost_clp,
                    unit_price_clp=item["unit_price_clp"],
                    reference_type="ORDER",
                    reference_id=order.id,
                    reference_label=f"Orden #{order.id}",
                    notes="Salida por venta manual",
                )

            order_item.unit_cost_clp = unit_cost_clp
            order_item.total_cost_clp = total_cost_clp
            order_item.gross_profit_clp = item["subtotal_clp"] - total_cost_clp
            order_item.save(
                update_fields=[
                    "unit_cost_clp",
                    "total_cost_clp",
                    "gross_profit_clp",
                    "updated_at",
                ]
            )

        return Response(
            self.get_serializer(order).data,
            status=status.HTTP_201_CREATED,
        )


class AssistedPurchaseOrderViewSet(viewsets.ModelViewSet):
    serializer_class = AssistedPurchaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if is_admin_user(self.request.user) or is_worker_user(self.request.user):
            return AssistedPurchaseOrderSerializer
        return AssistedPurchaseOrderPublicSerializer

    def get_queryset(self):
        qs = AssistedPurchaseOrder.objects.select_related(
            "user",
            "supplier",
        ).prefetch_related(
            "items__product"
        )

        if is_admin_user(self.request.user) or is_worker_user(self.request.user):
            status_value = self.request.query_params.get("status")

            if status_value:
                qs = qs.filter(status=status_value)

            return qs

        return qs.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="recalculate")
    def recalculate(self, request, pk=None):
        order = self.get_object()

        is_owner = order.user_id == request.user.id
        is_staff_role = is_admin_user(
            request.user) or is_worker_user(request.user)

        if not is_owner and not is_staff_role:
            return Response(
                {"detail": "No autorizado."},
                status=status.HTTP_403_FORBIDDEN,
            )

        order.calculate_totals()
        order.save()

        return Response(self.get_serializer(order).data)


from rest_framework.views import APIView


class ShippingQuoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        commune = (request.data.get('commune') or '').strip()
        region = (request.data.get('region') or '').strip()
        if not commune:
            return Response(
                {'detail': 'La comuna es requerida.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from shipping.chilexpress_service import quote_shipment
            result = quote_shipment(commune, region_name=region)
        except Exception as exc:
            logger.exception('Error en cotización de envío: %s', exc)
            return Response(
                {'detail': 'Error al contactar el servicio de envíos.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if result is None:
            return Response(
                {'detail': 'Sin cobertura disponible para esta comuna.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(result)
