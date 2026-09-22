"""URLs para o módulo Stone / Pagar.me V5 (Sandbox & Diagnósticos)."""
from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="stone_dashboard"),
    path("cobranca/", views.cobranca, name="stone_cobranca"),
    path("pedido/novo/", views.criar_pedido, name="stone_criar_pedido"),
    path("testes/", views.testes_integracao, name="stone_testes"),
    path("configuracao/", views.configuracao, name="stone_configuracao"),
    path("pagamentos/", views.pagamentos, name="stone_pagamentos"),
    path("pagamentos/<int:pk>/", views.pagamento_detalhe, name="stone_pagamento_detalhe"),
    path("pagamentos/<int:pk>/atualizar/", views.atualizar_pagamento, name="stone_atualizar_pagamento"),
    path("pagamentos/<int:pk>/pix-qr.png", views.pix_qr, name="stone_pix_qr"),
    path("webhook/", views.webhook_stone, name="stone_webhook_endpoint"),

    # APIs de Telemetria e Diagnóstico
    path("api/logs/", views.api_logs, name="stone_api_logs"),
    path("api/logs/limpar/", views.api_limpar_logs, name="stone_api_limpar_logs"),
    path("api/logs/exportar/", views.api_exportar_logs, name="stone_api_exportar_logs"),
    path("api/pedidos/testar/", views.api_testar_pedido, name="stone_api_testar_pedido"),
    path("api/testes/executar/", views.api_executar_suite_testes, name="stone_api_executar_suite_testes"),
    path("api/configuracao/", views.api_configuracao, name="stone_api_configuracao"),
]
