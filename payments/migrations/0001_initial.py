from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('orders', '0003_update_order_statuses'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('webpay', 'Webpay')], default='webpay', max_length=20)),
                ('status', models.CharField(choices=[('created', 'Creada'), ('pending', 'Pendiente'), ('authorized', 'Autorizada'), ('failed', 'Fallida'), ('cancelled', 'Cancelada'), ('reversed', 'Revertida')], default='created', max_length=20)),
                ('amount_clp', models.PositiveIntegerField()),
                ('buy_order', models.CharField(max_length=64)),
                ('session_id', models.CharField(max_length=64)),
                ('token', models.CharField(max_length=128, unique=True)),
                ('authorization_code', models.CharField(blank=True, max_length=32)),
                ('payment_type_code', models.CharField(blank=True, max_length=8)),
                ('response_code', models.IntegerField(blank=True, null=True)),
                ('installments_number', models.PositiveIntegerField(default=0)),
                ('card_last_digits', models.CharField(blank=True, max_length=4)),
                ('transaction_date', models.DateTimeField(blank=True, null=True)),
                ('raw_request', models.JSONField(blank=True, default=dict)),
                ('raw_response', models.JSONField(blank=True, default=dict)),
                ('accounting_status', models.CharField(choices=[('pending', 'Pendiente'), ('registered', 'Registrado'), ('error', 'Error')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payment_transactions', to='orders.order')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payment_transactions', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='SalesReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_type', models.CharField(choices=[('internal_receipt', 'Comprobante interno'), ('boleta', 'Boleta'), ('factura', 'Factura')], default='internal_receipt', max_length=20)),
                ('document_number', models.CharField(max_length=64, unique=True)),
                ('net_amount_clp', models.PositiveIntegerField()),
                ('tax_amount_clp', models.PositiveIntegerField()),
                ('total_amount_clp', models.PositiveIntegerField()),
                ('status', models.CharField(choices=[('issued', 'Emitido'), ('void', 'Anulado')], default='issued', max_length=10)),
                ('issued_at', models.DateTimeField(auto_now_add=True)),
                ('raw_data', models.JSONField(blank=True, default=dict)),
                ('order', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='sales_receipt', to='orders.order')),
                ('payment_transaction', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='sales_receipt', to='payments.paymenttransaction')),
            ],
        ),
    ]
