from django.db import migrations


def drop_legacy_real_total_clp_column(apps, schema_editor):
    table_name = "products_purchaseorder"
    column_name = "real_total_clp"
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        columns = [
            col.name
            for col in connection.introspection.get_table_description(cursor, table_name)
        ]

    if column_name in columns:
        schema_editor.execute(
            f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("products", "0010_migrate_exchange_rate_config_to_pricing_settings"),
    ]

    operations = [
        migrations.RunPython(
            drop_legacy_real_total_clp_column,
            reverse_code=migrations.RunPython.noop,
        ),
    ]