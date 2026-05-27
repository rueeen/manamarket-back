from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paymenttransaction',
            name='status',
            field=models.CharField(
                choices=[
                    ('created', 'Creada'),
                    ('pending', 'Pendiente'),
                    ('authorized', 'Autorizada'),
                    ('failed', 'Fallida'),
                    ('rejected', 'Rechazada'),
                    ('cancelled', 'Cancelada'),
                    ('error', 'Error'),
                    ('reversed', 'Revertida'),
                ],
                default='created',
                max_length=20,
            ),
        ),
    ]
