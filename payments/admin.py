from django.contrib import admin

from .models import PaymentTransaction, SalesReceipt


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'user', 'amount_clp', 'status', 'authorization_code', 'created_at')
    list_filter = ('status', 'provider', 'created_at')
    search_fields = ('id', 'token', 'buy_order', 'user__username')


@admin.register(SalesReceipt)
class SalesReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'document_number', 'document_type', 'total_amount_clp', 'issued_at')
