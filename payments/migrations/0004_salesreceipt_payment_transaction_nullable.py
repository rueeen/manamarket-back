from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_payment_reservation_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='salesreceipt',
            name='payment_transaction',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sales_receipt', to='payments.paymenttransaction'),
        ),
    ]
