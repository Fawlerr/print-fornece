from django.urls import path

from . import views

app_name = "integracoes"

urlpatterns = [
    path("", views.ChavesView.as_view(), name="chaves"),
]
