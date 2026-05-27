from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from products.models import PricingSettings, Product, Supplier


class AssistedPurchaseOrder(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Solicitado"
        QUOTED = "quoted", "Cotizado"
        APPROVED = "approved", "Aprobado"
        PAID = "paid", "Pagado"
        PURCHASED = "purchased", "Comprado"
        RECEIVED = "received", "Recibido"
        SHIPPED = "shipped", "Enviado"
        DELIVERED = "delivered", "Entregado"
        CANCELLED = "cancelled", "Cancelado"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assisted_orders",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="assisted_orders",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True,
    )

    subtotal_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"))
    shipping_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_fee_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"))

    exchange_rate_real = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("1000.00"))
    exchange_rate_store = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("1150.00"))

    customs_clp = models.PositiveIntegerField(default=0)
    handling_clp = models.PositiveIntegerField(default=0)
    other_costs_clp = models.PositiveIntegerField(default=0)
    service_fee_clp = models.PositiveIntegerField(default=0)

    total_customer_clp = models.PositiveIntegerField(default=0)
    total_real_cost_clp = models.PositiveIntegerField(default=0)
    profit_clp = models.IntegerField(default=0)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Compra asistida"
        verbose_name_plural = "Compras asistidas"

    def __str__(self):
        return f"Compra asistida #{self.id} - {self.user} - {self.get_status_display()}"

    def _active_pricing(self):
        return PricingSettings.objects.filter(is_active=True).order_by("-updated_at").first()

    def recalculate_items(self):
        self.subtotal_usd = sum(
            (item.subtotal_usd for item in self.items.all()),
            Decimal("0.00"),
        )
        return self.subtotal_usd

    def calculate_real_cost(self):
        usd_cost = self.subtotal_usd + self.shipping_usd + self.payment_fee_usd

        self.total_real_cost_clp = (
            int(usd_cost * self.exchange_rate_real)
            + self.customs_clp
            + self.handling_clp
            + self.other_costs_clp
        )

        return self.total_real_cost_clp

    def calculate_customer_total(self):
        usd_customer = self.subtotal_usd + self.shipping_usd + self.payment_fee_usd

        self.total_customer_clp = (
            int(usd_customer * self.exchange_rate_store)
            + self.customs_clp
            + self.handling_clp
            + self.other_costs_clp
            + self.service_fee_clp
        )

        return self.total_customer_clp

    def calculate_profit(self):
        self.profit_clp = self.total_customer_clp - self.total_real_cost_clp
        return self.profit_clp

    def calculate_totals(self):
        settings_obj = self._active_pricing()

        if settings_obj:
            self.exchange_rate_real = settings_obj.usd_to_clp_real
            self.exchange_rate_store = settings_obj.usd_to_clp_store

        self.recalculate_items()
        self.calculate_real_cost()
        self.calculate_customer_total()
        self.calculate_profit()


class AssistedPurchaseItem(models.Model):
    order = models.ForeignKey(
        AssistedPurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="assisted_order_items",
        null=True,
        blank=True,
    )

    external_name = models.CharField(max_length=255, blank=True)
    external_url = models.URLField(blank=True)
    external_sku = models.CharField(max_length=120, blank=True)

    requested_condition = models.CharField(max_length=20, blank=True)
    requested_language = models.CharField(max_length=20, blank=True)
    is_foil = models.BooleanField(default=False)

    quantity = models.PositiveIntegerField(default=1)
    unit_price_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"))
    subtotal_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        verbose_name = "Producto de compra asistida"
        verbose_name_plural = "Productos de compra asistida"

    def clean(self):
        if not self.product and not self.external_name:
            raise ValidationError(
                "Debe indicar un producto interno o un nombre externo.")

        if self.quantity <= 0:
            raise ValidationError("La cantidad debe ser mayor a 0.")

        if self.unit_price_usd < 0:
            raise ValidationError("El precio unitario no puede ser negativo.")

    def save(self, *args, **kwargs):
        self.full_clean()
        self.subtotal_usd = self.unit_price_usd * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        name = self.product.name if self.product else self.external_name
        return f"{name} x {self.quantity}"


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pendiente de pago"
        PAYMENT_STARTED = "payment_started", "Pago iniciado"
        PAID = "paid", "Pagado"
        PROCESSING = "processing", "Procesando"
        SHIPPED = "shipped", "Enviado"
        DELIVERED = "delivered", "Entregado"
        PAYMENT_FAILED = "payment_failed", "Pago rechazado"
        CANCELED = "canceled", "Cancelado"
        COMPLETED = "completed", "Completada"
        EXPIRED = "expired", "Expirada"
        MANUAL_REVIEW = "manual_review", "Revisión manual"

    class StockReservationStatus(models.TextChoices):
        NONE = "none", "Sin reserva"
        RESERVED = "reserved", "Reservada"
        RELEASED = "released", "Liberada"
        CONSUMED = "consumed", "Consumida"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        db_index=True,
    )

    subtotal_clp = models.PositiveIntegerField(default=0)
    shipping_clp = models.PositiveIntegerField(default=0)
    discount_clp = models.PositiveIntegerField(default=0)
    total_clp = models.PositiveIntegerField(default=0)
    recipient_name = models.CharField(max_length=150, blank=True)
    recipient_phone = models.CharField(max_length=20, blank=True)
    shipping_street = models.CharField(max_length=200, blank=True)
    shipping_number = models.CharField(max_length=20, blank=True)
    shipping_commune = models.CharField(max_length=100, blank=True)
    shipping_region = models.CharField(max_length=100, blank=True)
    shipping_notes = models.TextField(blank=True)

    # Evita dobles descuentos de stock/Kardex.
    stock_consumed = models.BooleanField(default=False)

    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    stock_reserved_at = models.DateTimeField(null=True, blank=True)
    stock_reservation_expires_at = models.DateTimeField(null=True, blank=True)
    stock_released_at = models.DateTimeField(null=True, blank=True)
    stock_reservation_status = models.CharField(
        max_length=20,
        choices=StockReservationStatus.choices,
        default=StockReservationStatus.NONE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Orden"
        verbose_name_plural = "Órdenes"
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"Orden #{self.id} - {self.user} - {self.get_status_display()}"

    def calculate_totals(self):
        self.subtotal_clp = sum(item.subtotal_clp for item in self.items.all())
        self.total_clp = max(
            self.subtotal_clp + self.shipping_clp - self.discount_clp,
            0,
        )
        return self.total_clp

    @property
    def can_be_paid(self):
        return self.status in [self.Status.PENDING_PAYMENT, self.Status.PAYMENT_FAILED]

    @property
    def stock_reservation_is_active(self):
        return (
            self.stock_reservation_status == self.StockReservationStatus.RESERVED
            and self.stock_reservation_expires_at is not None
            and self.stock_reservation_expires_at > timezone.now()
        )

    @property
    def can_be_canceled(self):
        return self.status in [
            self.Status.PENDING_PAYMENT,
            self.Status.PAYMENT_STARTED,
            self.Status.PAID,
            self.Status.PROCESSING,
        ]

    @property
    def is_finalized(self):
        return self.status in [
            self.Status.DELIVERED,
            self.Status.CANCELED,
            self.Status.COMPLETED,
        ]


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    quantity = models.PositiveIntegerField()

    # Snapshots para mantener historial aunque el producto cambie.
    product_name_snapshot = models.CharField(max_length=255, default="")
    product_type_snapshot = models.CharField(max_length=20, default="")

    # Precio congelado al crear la orden.
    unit_price_clp = models.PositiveIntegerField(default=0)
    subtotal_clp = models.PositiveIntegerField(default=0)

    # Costos y utilidad calculados al confirmar pago / consumir stock.
    unit_cost_clp = models.IntegerField(default=0)
    total_cost_clp = models.IntegerField(default=0)
    gross_profit_clp = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Producto de orden"
        verbose_name_plural = "Productos de orden"

    def __str__(self):
        return f"{self.product_name_snapshot} x {self.quantity}"


class ShipmentTracking(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Creado"
        IN_TRANSIT = "in_transit", "En tránsito"
        DELIVERED = "delivered", "Entregado"
        FAILED = "failed", "Fallido"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="shipment")
    carrier = models.CharField(max_length=40, default="chilexpress")
    tracking_number = models.CharField(max_length=120, blank=True)
    label_url = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    raw_request = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Seguimiento de envío"
