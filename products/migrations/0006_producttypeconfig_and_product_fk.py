from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0005_category_hierarchy_sort_and_product_type_expansion'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductTypeConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, unique=True)),
                ('slug', models.SlugField(unique=True)),
                ('description', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('uses_scryfall', models.BooleanField(default=False)),
                ('requires_condition', models.BooleanField(default=False)),
                ('requires_language', models.BooleanField(default=False)),
                ('requires_foil', models.BooleanField(default=False)),
                ('manages_stock', models.BooleanField(default=True)),
                ('is_sealed', models.BooleanField(default=False)),
                ('is_bundle', models.BooleanField(default=False)),
                ('is_service', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'Tipo de producto', 'verbose_name_plural': 'Tipos de producto', 'ordering': ['sort_order', 'name']},
        ),
        migrations.AddField(
            model_name='product',
            name='product_type_config',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='products', to='products.producttypeconfig'),
        ),
    ]
