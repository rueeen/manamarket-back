from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_salesreceipt_payment_transaction_nullable"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="paymenttransaction",
            name="stock_reservation_status",
        ),
    ]
