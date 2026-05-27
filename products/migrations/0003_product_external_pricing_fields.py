from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0002_alter_bundleitem_options_alter_category_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="exchange_rate_usd_clp",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0.0000"),
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="price_external_usd",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
            ),
        ),
    ]
