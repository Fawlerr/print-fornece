from django.urls import path

from . import views

app_name = "whatsapp"

urlpatterns = [
    path("", views.chat, name="chat"),
    path("pedido/<int:order_id>/", views.abrir_pedido, name="abrir_pedido"),
    path("pedido/<int:order_id>/aviso/<slug:tipo>/", views.enviar_aviso, name="enviar_aviso"),
    path("mensagens/<int:pk>/midia/", views.midia, name="midia"),
    path("api/resumo/", views.api_resumo, name="api_resumo"),
    path("api/conversas/", views.api_conversas, name="api_conversas"),
    path("api/conversas/nova/", views.api_nova_conversa, name="api_nova_conversa"),
    path("api/conversas/<int:pk>/mensagens/", views.api_mensagens, name="api_mensagens"),
    path("api/conversas/<int:pk>/enviar/", views.api_enviar, name="api_enviar"),
    path("api/conversas/<int:pk>/midia/", views.api_enviar_midia, name="api_enviar_midia"),
    path("api/conversas/<int:pk>/anexo-pedido/", views.api_enviar_anexo_pedido, name="api_enviar_anexo_pedido"),
    path("api/conversas/<int:pk>/painel/", views.api_painel, name="api_painel"),
    path("api/conversas/<int:pk>/cliente/", views.api_cliente, name="api_cliente"),
    path("api/conversas/<int:pk>/etiquetas/", views.api_etiquetas, name="api_etiquetas"),
    path("api/conversas/<int:pk>/arquivar/", views.api_arquivar, name="api_arquivar"),
    path("api/mensagens/<int:pk>/apagar/", views.api_apagar, name="api_apagar"),
    path("api/mensagens/<int:pk>/reenviar/", views.api_reenviar, name="api_reenviar"),
    path("instancias/", views.instancias, name="instancias"),
    path("instancias/<int:pk>/<slug:acao>/", views.instancia_acao, name="instancia_acao"),
    path("webhook/evolution/<str:token>/", views.webhook_evolution, name="webhook_evolution"),
    path("webhook/umbler/<str:token>/", views.webhook_umbler, name="webhook_umbler"),
]
