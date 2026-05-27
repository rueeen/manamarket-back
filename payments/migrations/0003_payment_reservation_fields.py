from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_update_payment_status_choices"),
    ]

    operations = [
        migrations.AddField(model_name="paymenttransaction",name="stock_released_at",field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="paymenttransaction",name="stock_reservation_expires_at",field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="paymenttransaction",name="stock_reservation_status",field=models.CharField(choices=[('none','Sin reserva'),('reserved','Reservada'),('released','Liberada'),('consumed','Consumida')], default='none', max_length=20)),
        migrations.AddField(model_name="paymenttransaction",name="stock_reserved_at",field=models.DateTimeField(blank=True, null=True)),
    ]
