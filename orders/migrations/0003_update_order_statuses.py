from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_alter_assistedpurchaseitem_options_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='status',
            field=models.CharField(choices=[('pending_payment', 'Pendiente de pago'), ('payment_started', 'Pago iniciado'), ('paid', 'Pagado'), ('processing', 'Procesando'), ('shipped', 'Enviado'), ('delivered', 'Entregado'), ('payment_failed', 'Pago rechazado'), ('canceled', 'Cancelado'), ('completed', 'Completada')], db_index=True, default='pending_payment', max_length=20),
        ),
    ]
