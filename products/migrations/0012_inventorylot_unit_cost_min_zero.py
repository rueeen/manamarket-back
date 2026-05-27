from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0011_drop_legacy_real_total_clp_column'),
    ]

    operations = [
        migrations.AlterField(
            model_name='inventorylot',
            name='unit_cost_clp',
            field=models.PositiveIntegerField(validators=[MinValueValidator(0)]),
        ),
    ]
