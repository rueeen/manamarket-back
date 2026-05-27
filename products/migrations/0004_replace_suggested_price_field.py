from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0003_product_external_pricing_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="product",
            name="price_clp_suggested",
        ),
        migrations.AddField(
            model_name="product",
            name="price_clp_reference",
            field=models.DecimalField(
                max_digits=12,
                decimal_places=2,
                null=True,
                blank=True,
            ),
        ),
    ]
