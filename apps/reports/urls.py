from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("", views.ReportView.as_view(), name="index"),
    path("production/", views.ProductionReportView.as_view(), name="production"),
    path("producao/", views.ProductionReportView.as_view()),
    path("cash-register/", views.CashRegisterReportView.as_view(), name="cash_register"),
    path("fechamento-caixa/", views.CashRegisterReportView.as_view()),
    path("caixa/", views.CashRegisterReportView.as_view()),
]
