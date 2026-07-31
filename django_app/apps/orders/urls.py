from django.urls import path

from . import views

app_name = "orders"
urlpatterns = [
    path("new/", views.OrderCreateView.as_view(), name="create"),
    path("<int:pk>/edit/", views.OrderUpdateView.as_view(), name="edit"),
    path("<int:order_pk>/attachments/<int:pk>/download/", views.download_attachment, name="download_attachment"),
]

