from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_shipmenttracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="recipient_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="order",
            name="recipient_phone",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="order",
            name="shipping_commune",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="order",
            name="shipping_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="order",
            name="shipping_number",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="order",
            name="shipping_region",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="order",
            name="shipping_street",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
