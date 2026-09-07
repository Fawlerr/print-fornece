from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("", views.ReportView.as_view(), name="index"),
    path("production/", views.ProductionReportView.as_view(), name="production"),
    path("producao/", views.ProductionReportView.as_view()),
    path("cash-register/", views.CashRegisterReportView.as_view(), name="cash_register"),
    path("cash-register/beta/", views.CashRegisterBetaView.as_view(), name="cash_register_beta"),
    path("fechamento-caixa/", views.CashRegisterReportView.as_view()),
    path("fechamento-caixa/beta/", views.CashRegisterBetaView.as_view()),
    path("caixa/", views.CashRegisterReportView.as_view()),
    path("materials/", views.MaterialReportView.as_view(), name="materials"),
    path("materiais/", views.MaterialReportView.as_view()),
    path("team-ranking/", views.TeamRankingReportView.as_view(), name="team_ranking"),
    path("equipe/", views.TeamRankingReportView.as_view()),
    path("customers-ranking/", views.CustomerRankingReportView.as_view(), name="customers_ranking"),
    path("clientes/", views.CustomerRankingReportView.as_view()),
]
