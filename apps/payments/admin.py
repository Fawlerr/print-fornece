from django.contrib import admin

from .models import Charge, Cliente, Pagamento, MetodoPagamento


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "cpf_cnpj", "email", "telefone", "stone_customer_id", "created_at")
    search_fields = ("nome", "cpf_cnpj", "email", "telefone", "stone_customer_id")
    list_filter = ("created_at",)


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ("id", "cliente", "valor", "metodo", "status", "parcelas", "pedido_referencia", "created_at")
    list_filter = ("metodo", "status", "created_at")
    search_fields = ("cliente__nome", "stone_payment_id", "pedido_referencia__number")


@admin.register(MetodoPagamento)
class MetodoPagamentoAdmin(admin.ModelAdmin):
    list_display = ("cliente", "bandeira", "ultimos_4", "validade", "ativo", "created_at")
    list_filter = ("ativo", "bandeira", "created_at")
    search_fields = ("cliente__nome", "ultimos_4", "stone_token_id")


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = ("order", "provider", "type", "amount", "status", "created_at")
    list_filter = ("provider", "type", "status")


