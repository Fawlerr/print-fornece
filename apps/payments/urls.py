from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("clientes/", views.ClienteListView.as_view(), name="customer_list"),
    path("clientes/novo/", views.ClienteCreateView.as_view(), name="customer_create"),
    path("clientes/<int:pk>/", views.ClienteDetailView.as_view(), name="customer_detail"),
    path("clientes/<int:pk>/editar/", views.ClienteUpdateView.as_view(), name="customer_edit"),
    path("clientes/<int:pk>/arquivos/adicionar/", views.cliente_add_arquivo, name="customer_add_arquivo"),
    path("clientes/<int:pk>/credito/adicionar/", views.cliente_add_credito, name="customer_add_credito"),
    path("clientes/api/search/", views.api_clientes_search, name="api_customer_search"),
    path("stone/webhook/", views.stone_webhook, name="stone_webhook"),
]
