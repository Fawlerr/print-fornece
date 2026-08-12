from django.db import migrations


def repair_legacy_snapshot_values(apps, schema_editor):
    """Repair placeholder defaults created by an interrupted legacy migration."""
    Order = apps.get_model("orders", "Order")
    order_table = schema_editor.quote_name(Order._meta.db_table)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {order_table} SET receipt_client_name = client_name "
            "WHERE (receipt_client_name IS NULL OR receipt_client_name = '' OR receipt_client_name = 'receipt_client_name')"
        )
        cursor.execute(
            f"UPDATE {order_table} SET receipt_seller_name = '' "
            "WHERE receipt_seller_name = 'receipt_seller_name'"
        )
        if schema_editor.connection.vendor == "sqlite":
            cursor.execute(
                f"UPDATE {order_table} SET receipt_total_amount = total_amount "
                "WHERE receipt_total_amount IS NULL OR CAST(receipt_total_amount AS TEXT) = 'receipt_total_amount' OR TYPEOF(receipt_total_amount) = 'text'"
            )
            cursor.execute(
                f"UPDATE {order_table} SET receipt_paid_amount = paid_amount "
                "WHERE receipt_paid_amount IS NULL OR CAST(receipt_paid_amount AS TEXT) = 'receipt_paid_amount' OR TYPEOF(receipt_paid_amount) = 'text'"
            )
        else:
            cursor.execute(
                f"UPDATE {order_table} SET receipt_total_amount = total_amount "
                "WHERE receipt_total_amount IS NULL OR CAST(receipt_total_amount AS CHAR) = 'receipt_total_amount' OR receipt_total_amount = 0"
            )
            cursor.execute(
                f"UPDATE {order_table} SET receipt_paid_amount = paid_amount "
                "WHERE receipt_paid_amount IS NULL OR CAST(receipt_paid_amount AS CHAR) = 'receipt_paid_amount'"
            )
        cursor.execute(
            f"UPDATE {order_table} SET receipt_payment_method = COALESCE(payment_method, '') "
            "WHERE (receipt_payment_method IS NULL OR receipt_payment_method = '' OR receipt_payment_method = 'receipt_payment_method')"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("orders", "0004_calculator_items_and_receipt_snapshots"),
    ]

    operations = [
        migrations.RunPython(repair_legacy_snapshot_values, migrations.RunPython.noop),
    ]
