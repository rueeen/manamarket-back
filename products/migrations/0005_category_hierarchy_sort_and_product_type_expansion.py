from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0004_replace_suggested_price_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="parent",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="children", to="products.category"),
        ),
        migrations.AddField(
            model_name="category",
            name="sort_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="product",
            name="product_type",
            field=models.CharField(choices=[('single', 'Carta individual'), ('sealed', 'Producto sellado'), ('bundle', 'Bundle'), ('accessory', 'Accesorio'), ('service', 'Servicio / encargo'), ('other', 'Otro')], db_index=True, default='single', max_length=20),
        ),
        migrations.AlterModelOptions(
            name="category",
            options={"ordering": ["sort_order", "name"], "verbose_name": "Categoría", "verbose_name_plural": "Categorías"},
        ),
    ]
