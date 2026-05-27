from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class PricingSource(models.TextChoices):
    SCRYFALL = "SCRYFALL", "Scryfall"
    MANUAL = "MANUAL", "Manual"


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"


    def __str__(self):
        return self.name


class ProductTypeConfig(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    uses_scryfall = models.BooleanField(default=False)
    requires_condition = models.BooleanField(default=False)
    requires_language = models.BooleanField(default=False)
    requires_foil = models.BooleanField(default=False)
    manages_stock = models.BooleanField(default=True)
    is_sealed = models.BooleanField(default=False)
    is_bundle = models.BooleanField(default=False)
    is_service = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Tipo de producto"
        verbose_name_plural = "Tipos de producto"


    def __str__(self):
        return self.name


class MTGCard(models.Model):
    scryfall_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    printed_name = models.CharField(max_length=255, blank=True)
    set_name = models.CharField(max_length=255, blank=True)
    set_code = models.CharField(max_length=20, blank=True)
    collector_number = models.CharField(max_length=20, blank=True)
    rarity = models.CharField(max_length=30, blank=True)
    mana_cost = models.CharField(max_length=80, blank=True)
    type_line = models.CharField(max_length=255, blank=True)
    oracle_text = models.TextField(blank=True)
    colors = models.JSONField(default=list, blank=True)
    color_identity = models.JSONField(default=list, blank=True)
    image_small = models.URLField(blank=True)
    image_normal = models.URLField(blank=True)
    image_large = models.URLField(blank=True)
    scryfall_uri = models.URLField(blank=True)
    released_at = models.DateField(null=True, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "set_code", "collector_number"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["set_code", "collector_number"]),
        ]
        verbose_name = "Carta MTG"
        verbose_name_plural = "Cartas MTG"


    def __str__(self):
        if self.set_code and self.collector_number:
            return f"{self.name} [{self.set_code} #{self.collector_number}]"

        if self.set_code:
            return f"{self.name} [{self.set_code}]"

        return self.name


class Product(models.Model):
    class ProductType(models.TextChoices):
        SINGLE = "single", "Carta individual"
        SEALED = "sealed", "Producto sellado"
        BUNDLE = "bundle", "Bundle"
        ACCESSORY = "accessory", "Accesorio"
        SERVICE = "service", "Servicio / encargo"
        OTHER = "other", "Otro"

    class CardCondition(models.TextChoices):
        NM = "NM", "Near Mint"
        LP = "LP", "Lightly Played"
        MP = "MP", "Moderately Played"
        HP = "HP", "Heavily Played"
        DMG = "DMG", "Damaged"

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.SINGLE,
        db_index=True,
    )
    product_type_config = models.ForeignKey(
        ProductTypeConfig,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    price_clp = models.PositiveIntegerField(default=0)
    stock = models.PositiveIntegerField(default=0)
    stock_reserved = models.PositiveIntegerField(default=0)
    stock_minimum = models.PositiveIntegerField(default=0)
    average_cost_clp = models.PositiveIntegerField(default=0)
    last_purchase_cost_clp = models.PositiveIntegerField(default=0)
    image = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    # Precio de referencia externo (USD) sin conversión ni margen local.
    price_clp_reference = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    # Precio crudo desde proveedor externo en USD.
    price_external_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    # Tasa snapshot usada durante la sincronización.
    exchange_rate_usd_clp = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    pricing_source = models.CharField(
        max_length=20,
        choices=PricingSource.choices,
        default=PricingSource.MANUAL,
    )
    pricing_last_update = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Nuevo: faltaba updated_at para trazabilidad de cambios de producto.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["product_type", "is_active"]),
            models.Index(fields=["name"]),
        ]
        verbose_name = "Producto"
        verbose_name_plural = "Productos"


    def __str__(self):
        return self.name

    @property
    def available_stock(self):
        return max((self.stock or 0) - (self.stock_reserved or 0), 0)

    @property
    def bundle_total_price_clp(self):
        """
        Calcula el precio de un bundle sumando los precios actuales
        de sus componentes.

        Importante:
        - No congela precio.
        - El precio congelado debe guardarse en OrderItem al vender.
        """
        if self.product_type != self.ProductType.BUNDLE:
            return 0

        return sum(
            bundle_item.quantity * bundle_item.item.computed_price_clp
            for bundle_item in self.bundle_items.select_related("item")
        )

    @property
    def computed_price_clp(self):
        """
        Precio utilizado por carrito y órdenes.

        - SINGLE y SEALED usan price_clp.
        - BUNDLE calcula su precio desde sus componentes.
        """
        if self.product_type == self.ProductType.BUNDLE:
            return self.bundle_total_price_clp

        return self.price_clp

    @property
    def cost_real_clp(self):
        """
        Costo real estimado del producto.

        Prioridad:
        1. Último lote disponible.
        2. Último costo de compra.
        3. Costo promedio.
        """
        lot = (
            self.lots.filter(quantity_remaining__gt=0)
            .order_by("-received_at", "-id")
            .first()
        )

        if lot:
            return int(lot.unit_cost_clp or 0)

        return int(self.last_purchase_cost_clp or self.average_cost_clp or 0)

    @property
    def margin_clp(self):
        return int(self.computed_price_clp or 0) - int(self.cost_real_clp or 0)

    @property
    def margin_percentage(self):
        cost = int(self.cost_real_clp or 0)

        if cost <= 0:
            return 0

        return round((self.margin_clp / cost) * 100, 2)

    @property
    def suggested_price_clp(self):
        """
        Precio sugerido calculado desde el costo real usando la configuración activa
        de PricingSettings (margin_factor + rounding_to).

        Import lazy para evitar dependencias circulares en import time con
        purchase_order_services.
        """
        from .purchase_order_services import calculate_suggested_price_from_real_cost

        return int(calculate_suggested_price_from_real_cost(int(self.cost_real_clp or 0)) or 0)

    def clean(self):
        super().clean()


class SingleCard(models.Model):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="single_card",
    )
    mtg_card = models.ForeignKey(
        MTGCard,
        on_delete=models.PROTECT,
        related_name="single_products",
    )
    condition = models.CharField(
        max_length=5,
        choices=Product.CardCondition.choices,
        default=Product.CardCondition.NM,
    )
    language = models.CharField(max_length=40, default="EN")
    is_foil = models.BooleanField(default=False)
    edition = models.CharField(max_length=120, blank=True)
    price_usd_reference = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    class Meta:
        verbose_name = "Carta individual"
        verbose_name_plural = "Cartas individuales"


    def __str__(self):
        foil_text = "Foil" if self.is_foil else "Non-foil"
        return f"{self.product.name} - {self.condition} - {self.language} - {foil_text}"


class SealedProduct(models.Model):
    class SealedKind(models.TextChoices):
        PRECON = "precon", "Precon"
        BOOSTER = "booster", "Booster"
        BUNDLE = "bundle", "Bundle"
        BOX = "box", "Display / Box"
        OTHER = "other", "Otro"

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="sealed_product",
    )
    sealed_kind = models.CharField(
        max_length=20,
        choices=SealedKind.choices,
        default=SealedKind.OTHER,
    )
    set_code = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "Producto sellado"
        verbose_name_plural = "Productos sellados"


    def __str__(self):
        return f"{self.product.name} - {self.get_sealed_kind_display()}"


class BundleItem(models.Model):
    bundle = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="bundle_items",
        limit_choices_to={"product_type": Product.ProductType.BUNDLE},
    )
    item = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="part_of_bundles",
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["bundle", "item"],
                name="unique_item_per_bundle",
            )
        ]
        verbose_name = "Producto de bundle"
        verbose_name_plural = "Productos de bundle"

    def clean(self):
        if self.bundle_id and self.item_id and self.bundle_id == self.item_id:
            raise ValidationError("Un bundle no puede contenerse a sí mismo.")

        if self.item and self.item.product_type == Product.ProductType.BUNDLE:
            raise ValidationError("Un bundle no puede contener otro bundle.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


    def __str__(self):
        return f"{self.bundle} contiene {self.item} x {self.quantity}"


class KardexMovement(models.Model):
    class MovementType(models.TextChoices):
        PURCHASE_IN = "PURCHASE_IN", "Compra ingreso"
        SALE_OUT = "SALE_OUT", "Venta salida"
        RETURN_IN = "RETURN_IN", "Devolución ingreso"
        MANUAL_IN = "MANUAL_IN", "Entrada manual"
        MANUAL_OUT = "MANUAL_OUT", "Salida manual"
        ADJUSTMENT = "ADJUSTMENT", "Ajuste"
        CORRECTION = "CORRECTION", "Corrección"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="kardex_movements",
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
    )
    quantity = models.PositiveIntegerField()
    previous_stock = models.PositiveIntegerField()
    new_stock = models.PositiveIntegerField()
    unit_cost_clp = models.PositiveIntegerField(default=0)
    unit_price_clp = models.PositiveIntegerField(default=0)
    reference_type = models.CharField(max_length=80, blank=True)
    reference_id = models.CharField(max_length=80, blank=True)
    reference_label = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kardex_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Movimiento Kardex"
        verbose_name_plural = "Movimientos Kardex"


    def __str__(self):
        return f"{self.product} - {self.get_movement_type_display()} x {self.quantity}"


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)
    rut = models.CharField(max_length=20, blank=True)
    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=80, blank=True)
    website = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"


    def __str__(self):
        return self.name


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        SENT = "SENT", "Enviada"
        RECEIVED = "RECEIVED", "Recibida"
        CANCELLED = "CANCELLED", "Cancelada"

    class PurchaseOrderType(models.TextChoices):
        SINGLES = "singles", "Singles"
        GENERAL = "general", "General"
        MIXED = "mixed", "Mixta"

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    order_number = models.CharField(max_length=50, unique=True)
    external_reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    source_store = models.CharField(max_length=120, blank=True)
    purchase_order_type = models.CharField(
        max_length=20,
        choices=PurchaseOrderType.choices,
        default=PurchaseOrderType.GENERAL,
    )
    original_currency = models.CharField(
        max_length=3,
        choices=(("CLP", "CLP"), ("USD", "USD")),
        default="CLP",
    )
    exchange_rate_snapshot_clp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=1,
    )
    subtotal_original = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    shipping_original = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    sales_tax_original = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    total_original = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    import_duties_clp = models.PositiveIntegerField(default=0)
    customs_fee_clp = models.PositiveIntegerField(default=0)
    handling_fee_clp = models.PositiveIntegerField(default=0)
    paypal_variation_clp = models.IntegerField(default=0)
    other_costs_clp = models.PositiveIntegerField(default=0)

    subtotal_clp = models.PositiveIntegerField(default=0)
    shipping_clp = models.PositiveIntegerField(default=0)
    sales_tax_clp = models.PositiveIntegerField(default=0)
    total_origin_clp = models.PositiveIntegerField(default=0)
    total_extra_costs_clp = models.PositiveIntegerField(default=0)
    grand_total_clp = models.PositiveIntegerField(default=0)

    tax_rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=19,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders_received",
    )
    update_prices_on_receive = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Orden de compra"
        verbose_name_plural = "Órdenes de compra"

    def __str__(self):
        return f"OC {self.order_number} - {self.supplier}"


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="purchase_order_items",
        null=True,
        blank=True,
    )
    raw_description = models.TextField(blank=True)
    normalized_card_name = models.CharField(max_length=255, blank=True)
    set_name_detected = models.CharField(max_length=255, blank=True)
    style_condition = models.CharField(max_length=5, default="NM")
    quantity_ordered = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        default=1,
    )
    quantity_received = models.PositiveIntegerField(default=0)
    unit_price_original = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    line_total_original = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    unit_price_clp = models.PositiveIntegerField(default=0)
    line_total_clp = models.PositiveIntegerField(default=0)
    allocated_extra_cost_clp = models.PositiveIntegerField(default=0)
    allocated_tax_clp = models.PositiveIntegerField(default=0)
    real_unit_cost_clp = models.PositiveIntegerField(default=0)
    margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=35,
    )
    suggested_sale_price_clp = models.PositiveIntegerField(default=0)
    sale_price_to_apply_clp = models.PositiveIntegerField(default=0)
    scryfall_id = models.CharField(max_length=64, blank=True)
    scryfall_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Producto de orden de compra"
        verbose_name_plural = "Productos de orden de compra"

    def save(self, *args, **kwargs):
        self.line_total_original = self.unit_price_original * self.quantity_ordered
        super().save(*args, **kwargs)


    def __str__(self):
        if self.product:
            return f"{self.product} x {self.quantity_ordered}"

        return f"{self.raw_description or self.normalized_card_name} x {self.quantity_ordered}"


class InventoryLot(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="lots",
    )
    purchase_order_item = models.ForeignKey(
        PurchaseOrderItem,
        on_delete=models.PROTECT,
        related_name="lots",
        null=True,
        blank=True,
    )
    quantity_initial = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )
    quantity_remaining = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
    )
    unit_cost_clp = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
    )
    received_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at", "id"]
        verbose_name = "Lote de inventario"
        verbose_name_plural = "Lotes de inventario"


    def __str__(self):
        return f"{self.product} - {self.quantity_remaining}/{self.quantity_initial} unidades"


class ExchangeRateConfig(models.Model):
    name = models.CharField(max_length=80, default="default")
    usd_to_clp = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración de dólar"
        verbose_name_plural = "Configuraciones de dólar"


    def __str__(self):
        return f"{self.name} - {self.usd_to_clp} CLP"


class ServiceFeeConfig(models.Model):
    name = models.CharField(max_length=80, default="default")
    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    flat_fee_clp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Configuración de comisión"
        verbose_name_plural = "Configuraciones de comisión"


    def __str__(self):
        return f"{self.name} - {self.percentage}%"


class ShippingConfig(models.Model):
    name = models.CharField(max_length=80, default="default")
    base_clp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    per_item_clp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Configuración de envío"
        verbose_name_plural = "Configuraciones de envío"


    def __str__(self):
        return self.name


class PricingSettings(models.Model):
    name = models.CharField(max_length=120, default="Configuración principal")
    usd_to_clp = models.DecimalField(
        max_digits=12, decimal_places=2, default=1000)
    usd_to_clp_real = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=1000,
    )
    usd_to_clp_store = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=1150,
    )
    default_margin = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1.30,
    )
    min_margin = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1.15,
    )
    import_factor = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.30,
    )
    risk_factor = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.10,
    )
    margin_factor = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.25,
    )
    vat_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=19,
    )
    rounding_to = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración de precios"
        verbose_name_plural = "Configuraciones de precios"


    def __str__(self):
        return self.name
