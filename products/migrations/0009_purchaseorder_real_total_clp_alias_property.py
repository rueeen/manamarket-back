from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0008_product_stock_reserved"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(
                    model_name="purchaseorder",
                    name="real_total_clp",
                ),
            ],
        ),
    ]
