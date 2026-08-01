from django.urls import path

from . import views

app_name = "payments"
urlpatterns = [path("stone/webhook/", views.stone_webhook, name="stone_webhook")]

