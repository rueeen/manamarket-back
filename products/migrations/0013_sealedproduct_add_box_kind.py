from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0012_inventorylot_unit_cost_min_zero"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sealedproduct",
            name="sealed_kind",
            field=models.CharField(
                choices=[
                    ("precon", "Precon"),
                    ("booster", "Booster"),
                    ("bundle", "Bundle"),
                    ("box", "Display / Box"),
                    ("other", "Otro"),
                ],
                default="other",
                max_length=20,
            ),
        ),
    ]
