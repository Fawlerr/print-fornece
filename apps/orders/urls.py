from django.urls import path

from . import views

app_name = "orders"
urlpatterns = [
    path("new/", views.OrderCreateView.as_view(), name="create"),
    path("calculate/", views.calculate_order_quote, name="calculate_quote"),
    path("<int:pk>/edit/", views.OrderUpdateView.as_view(), name="edit"),
    path("<int:pk>/download-file/", views.download_primary_attachment, name="download_primary_attachment"),
    path("<int:order_pk>/attachments/<int:pk>/download/", views.download_attachment, name="download_attachment"),
    path("<int:pk>/receipt/pdf/", views.download_receipt_pdf, name="download_receipt"),
    path("<int:pk>/register-payment/", views.register_payment, name="register_payment"),
    path("<int:pk>/payments/<int:payment_id>/update-method/", views.update_order_payment_method, name="update_payment_method"),
    path("<int:pk>/mark-as-paid/", views.mark_order_as_paid, name="mark_as_paid"),
    path("<int:pk>/art-preview/", views.art_preview_view, name="art_preview"),
    path("quote/<str:token>/", views.public_quote_view, name="public_quote"),
    path("quote/<str:token>/approve/", views.approve_quote_action, name="approve_quote"),
    path("fatura-agrupada/", views.grouped_invoice_view, name="grouped_invoice"),

    # Integração Stone no Pedido
    path("<int:pk>/stone/charge/", views.order_stone_create_charge, name="stone_create_charge"),
    path("<int:pk>/stone/status/", views.order_stone_check_status, name="stone_check_status"),
    path("<int:pk>/stone/dev/logs/", views.order_stone_dev_logs, name="stone_dev_logs"),
    path("<int:pk>/stone/dev/force-approve/", views.order_stone_dev_force_approve, name="stone_dev_force_approve"),
    path("<int:pk>/stone/dev/force-fail/", views.order_stone_dev_force_fail, name="stone_dev_force_fail"),
    path("<int:pk>/stone/dev/reprocess/", views.order_stone_dev_reprocess_webhook, name="stone_dev_reprocess"),
    path("<int:pk>/stone/dev/ping/", views.order_stone_dev_ping, name="stone_dev_ping"),
]
