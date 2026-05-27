from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0004_order_stock_reservation_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShipmentTracking",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("carrier", models.CharField(default="chilexpress", max_length=40)),
                ("tracking_number", models.CharField(blank=True, max_length=120)),
                ("label_url", models.CharField(blank=True, max_length=500)),
                ("status", models.CharField(choices=[("created", "Creado"), ("in_transit", "En tránsito"), ("delivered", "Entregado"), ("failed", "Fallido")], default="created", max_length=20)),
                ("raw_request", models.JSONField(blank=True, default=dict)),
                ("raw_response", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("order", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="shipment", to="orders.order")),
            ],
            options={
                "verbose_name": "Seguimiento de envío",
            },
        ),
    ]
