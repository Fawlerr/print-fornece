"""Webhook da Umbler Talk -> eventos internos do chat (o mesmo formato que o parser da Evolution produz).

Formato oficial (https://help.umbler.com/hc/pt-br/articles/14023563758861):
    {"Type": "Message", "EventDate": "...", "EventId": "ZcPPcWpimiD3EiER",
     "Payload": {"Type": "Chat", "Content": <BasicChatModel>}}
- ``Message``: mensagem nova do contato ou de um membro, em ``Content.LastMessage``.
- ``EventId`` se repete nas re-tentativas (até 2, cabeçalho ``x-attempt``): é a chave de idempotência.
- A Umbler ainda não manda eventos de status (entregue/lida); eles vêm do comando ``whatsapp_atualizar_status``.
- O webhook não é assinado: a origem é validada pelo segredo na URL.
As chaves são lidas sem diferenciar maiúsculas (o webhook usa PascalCase; a API, camelCase).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .telefone import com_ddi
from .umbler import campo

logger = logging.getLogger("whatsapp")

_TIPOS = {
    "text": "texto",
    "url": "texto",
    "image": "imagem",
    "video": "video",
    "gif": "video",
    "audio": "audio",
    "sticker": "figurinha",
    "file": "documento",
    "location": "localizacao",
}
_MIDIA = {"imagem", "video", "audio", "figurinha", "documento"}
# Tipos de contato que não são atendimento de cliente (grupos, conversas internas, IA, testes).
_CONTATOS_IGNORADOS = {"group", "membergroup", "privatemembergroup", "memberdirectmessage", "aiassistant", "sandbox"}
_ORIGENS_DA_EQUIPE = {"member", "bot", "external"}


def _timestamp(valor: Any) -> int:
    if not valor:
        return 0
    try:
        return int(datetime.fromisoformat(str(valor).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def _texto(mensagem: dict[str, Any], tipo_bruto: str, tipo: str) -> str:
    texto = str(campo(mensagem, "content") or "").strip()
    arquivo = campo(mensagem, "file") or {}
    if not texto and isinstance(arquivo, dict):
        texto = str(campo(arquivo, "caption") or "").strip()
    if tipo == "localizacao":
        loc = campo(mensagem, "location") or {}
        lat, lng = campo(loc, "latitude"), campo(loc, "longitude")
        if lat is not None and lng is not None:
            texto = f"Localização https://maps.google.com/?q={lat},{lng}"
    if not texto and tipo == "texto":
        if tipo_bruto == "contact":
            nomes = [str(campo(c, "name") or "") for c in (campo(mensagem, "contacts") or []) if isinstance(c, dict)]
            texto = f"[Contato] {', '.join(n for n in nomes if n)}".strip()
        elif tipo_bruto not in ("text", "url", ""):
            texto = f"[Mensagem do tipo {tipo_bruto}: abra na Umbler para ver]"
    return texto


def interpretar_umbler(payload: dict[str, Any]) -> dict[str, Any]:
    """Devolve {evento_id, tipo, canal_id, canal_telefone, eventos}. ``eventos`` vazio = nada a gravar."""
    resultado: dict[str, Any] = {
        "evento_id": str(campo(payload, "eventId") or ""),
        "tipo": str(campo(payload, "type") or ""),
        "canal_id": "",
        "canal_telefone": "",
        "eventos": [],
    }
    corpo = campo(payload, "payload") or {}
    chat = campo(corpo, "content") or {}
    if not isinstance(chat, dict):
        return resultado
    canal = campo(chat, "channel") or {}
    resultado["canal_id"] = str(campo(canal, "id") or "")
    resultado["canal_telefone"] = com_ddi(str(campo(canal, "phoneNumber") or ""))

    if resultado["tipo"].lower() != "message":
        return resultado  # transferências, fechamento de chat etc. não mudam o histórico do Print
    mensagem = campo(chat, "lastMessage") or {}
    contato = campo(chat, "contact") or {}
    if not isinstance(mensagem, dict) or not isinstance(contato, dict):
        return resultado
    if campo(mensagem, "isPrivate") is True:
        return resultado  # nota interna da Umbler: o cliente não vê, não entra no chat do Print
    if str(campo(contato, "contactType") or "").lower() in _CONTATOS_IGNORADOS:
        return resultado

    msg_id = str(campo(mensagem, "id") or "")
    telefone = com_ddi(str(campo(contato, "phoneNumber") or ""))
    lid = "".join(ch for ch in str(campo(contato, "lid") or "").split("@")[0] if ch.isdigit())
    if not msg_id or not (telefone or lid):
        logger.warning("Webhook da Umbler sem id de mensagem ou sem contato identificável (evento %s)", resultado["evento_id"])
        return resultado

    tipo_bruto = str(campo(mensagem, "messageType") or "text").lower()
    if tipo_bruto == "reaction":
        return resultado
    tipo = _TIPOS.get(tipo_bruto, "texto")
    arquivo = campo(mensagem, "file") or {}
    de_mim = str(campo(mensagem, "source") or "").lower() in _ORIGENS_DA_EQUIPE
    estado = str(campo(mensagem, "messageState") or "").lower()

    resultado["eventos"].append({
        "tipo_evento": "mensagem",
        "id": msg_id,
        "telefone": telefone,
        "lid": lid,
        "de_mim": de_mim,
        "nome": str(campo(contato, "name") or "").strip(),
        "tipo": tipo,
        "texto": _texto(mensagem, tipo_bruto, tipo),
        "timestamp": _timestamp(campo(mensagem, "eventAtUTC") or campo(mensagem, "createdAtUTC")),
        "remote_jid": "",
        "mimetype": str(campo(arquivo, "contentType") or "") if isinstance(arquivo, dict) else "",
        "arquivo_nome": str(campo(arquivo, "originalName") or "") if isinstance(arquivo, dict) else "",
        # A mídia é baixada sob demanda pela API (GET /v1/messages/{id}), nunca pela URL do webhook.
        "midia": {"umbler_id": msg_id} if tipo in _MIDIA else None,
    })
    if estado == "deleted":
        resultado["eventos"].append({"tipo_evento": "revogacao", "id": msg_id})
    return resultado
