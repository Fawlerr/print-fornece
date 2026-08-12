"""Adopt the existing calculator table and add durable receipt snapshots.

Some deployed databases already contain the calculator migration from an
earlier release, while the repository did not retain that migration file.  The
state/database split below safely adopts that table when it exists and creates
the same schema for clean installations.
"""
from django.conf import settings
from django.db import migrations, models
from django.db.models.fields import NOT_PROVIDED
import django.db.models.deletion


ORDER_FIELDS = (
    "payment_confirmed_at",
    "payment_confirmed_by",
    "receipt_client_name",
    "receipt_seller_name",
    "receipt_total_amount",
    "receipt_paid_amount",
    "receipt_payment_method",
    "receipt_generated_at",
)


def apply_calculator_receipt_schema(apps, schema_editor):
    connection = schema_editor.connection
    Order = apps.get_model("orders", "Order")
    OrderItem = apps.get_model("orders", "OrderItem")
    table_names = set(connection.introspection.table_names())

    if OrderItem._meta.db_table not in table_names:
        schema_editor.create_model(OrderItem)

    for field_name in ORDER_FIELDS:
        # SQLite rebuilds a table using the complete model definition when one
        # field is added, so re-read the columns after every operation.
        order_columns = {
            column.name
            for column in connection.introspection.get_table_description(connection.cursor(), Order._meta.db_table)
        }
        field = Order._meta.get_field(field_name)
        if field.column not in order_columns:
            # AddField normally serializes a one-off default for a required
            # CharField.  Do the same here instead of letting SQLite invent a
            # value while rebuilding a legacy table.
            original_default = field.default
            if not field.null and original_default is NOT_PROVIDED:
                field.default = ""
            try:
                schema_editor.add_field(Order, field)
            finally:
                field.default = original_default

    order_table = schema_editor.quote_name(Order._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {order_table} SET receipt_client_name = client_name "
            "WHERE (receipt_client_name IS NULL OR receipt_client_name = '' OR receipt_client_name = 'receipt_client_name')"
        )
        cursor.execute(
            f"UPDATE {order_table} SET receipt_seller_name = '' "
            "WHERE receipt_seller_name = 'receipt_seller_name'"
        )
        if connection.vendor == "sqlite":
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
        ("orders", "0002_order_quote_token_alter_order_stage_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="order",
                    name="payment_confirmed_at",
                    field=models.DateTimeField(blank=True, null=True, verbose_name="pagamento confirmado em"),
                ),
                migrations.AddField(
                    model_name="order",
                    name="payment_confirmed_by",
                    field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="confirmed_order_payments", to=settings.AUTH_USER_MODEL),
                ),
                migrations.AddField(
                    model_name="order",
                    name="receipt_client_name",
                    field=models.CharField(blank=True, max_length=150, verbose_name="cliente no comprovante"),
                ),
                migrations.AddField(
                    model_name="order",
                    name="receipt_seller_name",
                    field=models.CharField(blank=True, max_length=150, verbose_name="vendedor no comprovante"),
                ),
                migrations.AddField(
                    model_name="order",
                    name="receipt_total_amount",
                    field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name="total no comprovante"),
                ),
                migrations.AddField(
                    model_name="order",
                    name="receipt_paid_amount",
                    field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name="valor pago no comprovante"),
                ),
                migrations.AddField(
                    model_name="order",
                    name="receipt_payment_method",
                    field=models.CharField(blank=True, max_length=20, verbose_name="forma de pagamento no comprovante"),
                ),
                migrations.AddField(
                    model_name="order",
                    name="receipt_generated_at",
                    field=models.DateTimeField(blank=True, null=True, verbose_name="comprovante gerado em"),
                ),
                migrations.CreateModel(
                    name="OrderItem",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("position", models.PositiveSmallIntegerField(default=1)),
                        ("kind", models.CharField(choices=[("material", "Material"), ("ajuste", "Ajuste")], default="material", max_length=12)),
                        ("material_code", models.CharField(max_length=60)),
                        ("material_name", models.CharField(max_length=160)),
                        ("category", models.CharField(max_length=100)),
                        ("film_width_cm", models.PositiveSmallIntegerField(blank=True, null=True)),
                        ("art_width_cm", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                        ("art_height_cm", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                        ("art_quantity", models.PositiveIntegerField(blank=True, null=True)),
                        ("items_per_row", models.PositiveIntegerField(blank=True, null=True)),
                        ("rows", models.PositiveIntegerField(blank=True, null=True)),
                        ("used_length_cm", models.PositiveIntegerField(blank=True, null=True)),
                        ("charged_length_cm", models.PositiveIntegerField(blank=True, null=True)),
                        ("billing_quantity", models.DecimalField(decimal_places=2, max_digits=10)),
                        ("billing_unit", models.CharField(max_length=30)),
                        ("unit_price", models.DecimalField(decimal_places=2, max_digits=12)),
                        ("line_total", models.DecimalField(decimal_places=2, max_digits=12)),
                        ("pricing_rule", models.CharField(max_length=120)),
                        ("calculation_detail", models.CharField(blank=True, max_length=255)),
                        ("calculation_snapshot", models.JSONField(blank=True, default=dict)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="orders.order")),
                    ],
                    options={
                        "db_table": "pf_order_items",
                        "ordering": ["position", "pk"],
                        "indexes": [models.Index(fields=["order", "created_at"], name="pf_item_order_date")],
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(apply_calculator_receipt_schema, migrations.RunPython.noop),
    ]
