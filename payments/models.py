from django.conf import settings
from django.db import models

from orders.models import Order


class PaymentTransaction(models.Model):
    class Provider(models.TextChoices):
        WEBPAY = 'webpay', 'Webpay'

    class Status(models.TextChoices):
        CREATED = 'created', 'Creada'
        PENDING = 'pending', 'Pendiente'
        AUTHORIZED = 'authorized', 'Autorizada'
        FAILED = 'failed', 'Fallida'
        REJECTED = 'rejected', 'Rechazada'
        CANCELLED = 'cancelled', 'Cancelada'
        ERROR = 'error', 'Error'
        REVERSED = 'reversed', 'Revertida'

    class AccountingStatus(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        REGISTERED = 'registered', 'Registrado'
        ERROR = 'error', 'Error'
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payment_transactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payment_transactions')
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.WEBPAY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    amount_clp = models.PositiveIntegerField()
    buy_order = models.CharField(max_length=64)
    session_id = models.CharField(max_length=64)
    token = models.CharField(max_length=128, unique=True)
    authorization_code = models.CharField(max_length=32, blank=True)
    payment_type_code = models.CharField(max_length=8, blank=True)
    response_code = models.IntegerField(null=True, blank=True)
    installments_number = models.PositiveIntegerField(default=0)
    card_last_digits = models.CharField(max_length=4, blank=True)
    transaction_date = models.DateTimeField(null=True, blank=True)
    raw_request = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    accounting_status = models.CharField(max_length=20, choices=AccountingStatus.choices, default=AccountingStatus.PENDING)
    stock_reserved_at = models.DateTimeField(null=True, blank=True)
    stock_reservation_expires_at = models.DateTimeField(null=True, blank=True)
    stock_released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SalesReceipt(models.Model):
    class DocumentType(models.TextChoices):
        INTERNAL_RECEIPT = 'internal_receipt', 'Comprobante interno'
        BOLETA = 'boleta', 'Boleta'
        FACTURA = 'factura', 'Factura'

    class Status(models.TextChoices):
        ISSUED = 'issued', 'Emitido'
        VOID = 'void', 'Anulado'

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='sales_receipt')
    payment_transaction = models.OneToOneField(PaymentTransaction, on_delete=models.CASCADE, related_name='sales_receipt', null=True, blank=True)
    document_type = models.CharField(max_length=20, choices=DocumentType.choices, default=DocumentType.INTERNAL_RECEIPT)
    document_number = models.CharField(max_length=64, unique=True)
    net_amount_clp = models.PositiveIntegerField()
    tax_amount_clp = models.PositiveIntegerField()
    total_amount_clp = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    issued_at = models.DateTimeField(auto_now_add=True)
    raw_data = models.JSONField(default=dict, blank=True)
