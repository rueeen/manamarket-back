from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0006_producttypeconfig_and_product_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorder",
            name="purchase_order_type",
            field=models.CharField(
                choices=[("singles", "Singles"), ("general", "General"), ("mixed", "Mixta")],
                default="general",
                max_length=20,
            ),
        ),
    ]
