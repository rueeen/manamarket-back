from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0007_purchaseorder_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="stock_reserved",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
