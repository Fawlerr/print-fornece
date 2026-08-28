from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("", views.ReportView.as_view(), name="index"),
    path("producao/", views.ProductionReportView.as_view(), name="production"),
    path("fechamento-caixa/", views.CashRegisterReportView.as_view(), name="cash_register"),
]
