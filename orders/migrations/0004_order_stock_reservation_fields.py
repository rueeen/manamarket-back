from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0003_update_order_statuses"),
    ]

    operations = [
        migrations.AddField(model_name="order",name="stock_released_at",field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="order",name="stock_reservation_expires_at",field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="order",name="stock_reservation_status",field=models.CharField(choices=[('none','Sin reserva'),('reserved','Reservada'),('released','Liberada'),('consumed','Consumida')], default='none', max_length=20)),
        migrations.AddField(model_name="order",name="stock_reserved_at",field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(
            model_name='order',
            name='status',
            field=models.CharField(choices=[('pending_payment','Pendiente de pago'),('payment_started','Pago iniciado'),('paid','Pagado'),('processing','Procesando'),('shipped','Enviado'),('delivered','Entregado'),('payment_failed','Pago rechazado'),('canceled','Cancelado'),('completed','Completada'),('expired','Expirada'),('manual_review','Revisión manual')], db_index=True, default='pending_payment', max_length=20),
        ),
    ]
