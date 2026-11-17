from django.contrib import admin

from .models import Conversa, Etiqueta, Instancia


@admin.register(Instancia)
class InstanciaAdmin(admin.ModelAdmin):
    list_display = ("apelido", "nome", "vendedora", "compartilhada", "padrao_automaticas", "estado", "ativa")
    list_filter = ("ativa", "compartilhada")


@admin.register(Etiqueta)
class EtiquetaAdmin(admin.ModelAdmin):
    list_display = ("nome", "cor", "vendedora")


@admin.register(Conversa)
class ConversaAdmin(admin.ModelAdmin):
    list_display = ("nome", "telefone", "instancia", "cliente", "nao_lidas", "ultima_mensagem_em")
    list_filter = ("instancia",)
    search_fields = ("nome", "telefone")
    raw_id_fields = ("cliente",)
    readonly_fields = ("telefone", "lid", "instancia")
