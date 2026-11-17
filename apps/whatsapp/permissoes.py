"""Quem vê o quê no chat. Tudo é decidido aqui, no servidor, seja qual for o parâmetro enviado.

- Administrador/dev: vê todas as instâncias (perfil "Todas" ou um perfil por vendedora).
- Vendedora: vê as conversas das instâncias dela e das instâncias compartilhadas, se for do atendimento.
- Setor de produção: não acessa o chat.
"""
from __future__ import annotations

from django.db.models import Q, QuerySet

from .models import Conversa, Instancia


def eh_gestor(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_administrator or user.is_dev or user.is_superuser))


def pode_usar_chat(user) -> bool:
    if not (user and user.is_authenticated and user.is_active):
        return False
    if eh_gestor(user):
        return True
    return not user.is_prepress_production_only


def instancias_visiveis(user) -> QuerySet[Instancia]:
    qs = Instancia.objects.filter(ativa=True)
    if eh_gestor(user):
        return qs
    if not pode_usar_chat(user):
        return qs.none()
    return qs.filter(Q(vendedora=user) | Q(compartilhada=True))


def conversas_visiveis(user) -> QuerySet[Conversa]:
    return Conversa.objects.filter(instancia__in=instancias_visiveis(user))


def pode_ver_conversa(user, conversa: Conversa) -> bool:
    return instancias_visiveis(user).filter(pk=conversa.instancia_id).exists()


def pode_gerenciar_instancias(user) -> bool:
    return eh_gestor(user)
