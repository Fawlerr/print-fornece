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
    path("<int:pk>/art-preview/", views.art_preview_view, name="art_preview"),
    path("quote/<str:token>/", views.public_quote_view, name="public_quote"),
    path("quote/<str:token>/approve/", views.approve_quote_action, name="approve_quote"),
]
