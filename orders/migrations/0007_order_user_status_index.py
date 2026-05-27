from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_order_shipping_fields"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["user", "status"], name="orders_orde_user_id_f154a0_idx"),
        ),
    ]
