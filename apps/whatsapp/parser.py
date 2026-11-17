"""Interpretação dos eventos de webhook da Evolution API (v1.8 e v2.x).

Adaptado do chat da Casa das Óticas, que já tratava @lid, fromMe, revogações e mensagens
"embrulhadas" (temporárias, visualização única). Correções: vídeo e figurinha agora têm tipo
próprio e mídia baixável.
"""
from __future__ import annotations

import logging
from typing import Any

from .telefone import com_ddi, digitos_do_jid

logger = logging.getLogger("whatsapp")

# Embrulhos que o WhatsApp põe em volta do conteúdo real.
_EMBRULHOS = (
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
    "documentWithCaptionMessage",
    "editedMessage",
)
_CHAVES_TECNICAS = {"messageContextInfo", "senderKeyDistributionMessage", "deviceSentMessage"}
_IGNORADOS = {"reactionMessage", "pollUpdateMessage", "keepInChatMessage", "encReactionMessage", "call"}
_MIDIA = {"imagem", "audio", "video", "documento", "figurinha"}

_STATUS = {
    "SERVER_ACK": "enviada",
    "DELIVERY_ACK": "entregue",
    "READ": "lida",
    "PLAYED": "lida",
    "2": "enviada",
    "3": "entregue",
    "4": "lida",
    "5": "lida",
}


def nome_evento(payload: dict[str, Any]) -> str:
    return str(payload.get("event") or "").lower().strip().replace("_", ".")


def _desembrulhar(conteudo: dict[str, Any]) -> dict[str, Any]:
    for _ in range(4):
        if not isinstance(conteudo, dict):
            return {}
        for embrulho in _EMBRULHOS:
            interno = conteudo.get(embrulho)
            if isinstance(interno, dict) and isinstance(interno.get("message"), dict):
                conteudo = interno["message"]
                break
        else:
            return conteudo
    return conteudo


def _conteudo(c: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """(tipo, texto, dados da mídia). Tipo vazio = não vira mensagem no chat."""
    if "conversation" in c:
        return "texto", str(c.get("conversation") or ""), {}
    if "extendedTextMessage" in c:
        return "texto", str((c.get("extendedTextMessage") or {}).get("text") or ""), {}
    if "imageMessage" in c:
        m = c.get("imageMessage") or {}
        return "imagem", str(m.get("caption") or ""), m
    if "audioMessage" in c:
        return "audio", "", c.get("audioMessage") or {}
    if "documentMessage" in c:
        m = c.get("documentMessage") or {}
        return "documento", str(m.get("caption") or ""), m
    if "videoMessage" in c or "ptvMessage" in c:
        m = c.get("videoMessage") or c.get("ptvMessage") or {}
        return "video", str(m.get("caption") or ""), m
    if "stickerMessage" in c:
        return "figurinha", "", c.get("stickerMessage") or {}
    if "locationMessage" in c or "liveLocationMessage" in c:
        loc = c.get("locationMessage") or c.get("liveLocationMessage") or {}
        lat, lng = loc.get("degreesLatitude"), loc.get("degreesLongitude")
        rotulo = " - ".join(str(v) for v in (loc.get("name"), loc.get("address")) if v)
        link = f" https://maps.google.com/?q={lat},{lng}" if lat is not None and lng is not None else ""
        return "localizacao", f"Localização {rotulo}{link}".strip(), {}
    if "contactMessage" in c:
        return "texto", f"[Contato] {(c.get('contactMessage') or {}).get('displayName') or ''}".strip(), {}
    if "contactsArrayMessage" in c:
        total = len((c.get("contactsArrayMessage") or {}).get("contacts") or [])
        return "texto", f"[{total} contatos compartilhados]", {}
    for chave in ("pollCreationMessage", "pollCreationMessageV2", "pollCreationMessageV3"):
        if chave in c:
            return "texto", f"[Enquete] {(c.get(chave) or {}).get('name') or ''}".strip(), {}
    for chave, campo in (
        ("buttonsResponseMessage", "selectedDisplayText"),
        ("templateButtonReplyMessage", "selectedDisplayText"),
        ("listResponseMessage", "title"),
    ):
        if chave in c:
            return "texto", str((c.get(chave) or {}).get(campo) or "[Resposta de botão]"), {}

    tipos = [k for k in c if k not in _CHAVES_TECNICAS]
    if not tipos or any(k in _IGNORADOS for k in tipos):
        return "", "", {}
    logger.warning("Tipo de mensagem do WhatsApp não reconhecido: %s", tipos[:3])
    return "texto", f"[Mensagem do tipo {tipos[0]}: abra no celular para ver]", {}


def identificar_contato(key: dict[str, Any], item: dict[str, Any]) -> tuple[str, str]:
    """(telefone com DDI, lid) do contato. Em mensagens fromMe, `senderPn` é o número da própria vendedora."""
    remote_jid = str(key.get("remoteJid") or "")
    if key.get("fromMe"):
        alternativo = str(key.get("remoteJidAlt") or "")
    else:
        alternativo = str(
            key.get("remoteJidAlt") or key.get("senderPn") or item.get("senderPn") or key.get("senderLid") or ""
        )
    telefone, lid = "", ""
    if remote_jid.endswith("@lid"):
        lid = digitos_do_jid(remote_jid)
        if alternativo and "@lid" not in alternativo:
            telefone = digitos_do_jid(alternativo)
    else:
        telefone = digitos_do_jid(remote_jid)
        if alternativo.endswith("@lid"):
            lid = digitos_do_jid(alternativo)
    return (com_ddi(telefone) if telefone else ""), lid


def interpretar_mensagem(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    key = item.get("key") or {}
    remote_jid = str(key.get("remoteJid") or "")
    msg_id = str(key.get("id") or "")
    if "@g.us" in remote_jid or "broadcast" in remote_jid or "@newsletter" in remote_jid:
        return None
    bruto = item.get("message") or {}
    protocolo = bruto.get("protocolMessage") or {}
    if protocolo:
        if str(protocolo.get("type", "")).upper() in ("REVOKE", "0"):
            revogada = str((protocolo.get("key") or {}).get("id") or "")
            if revogada:
                return {"tipo_evento": "revogacao", "id": revogada}
        return None

    telefone, lid = identificar_contato(key, item)
    if not telefone and not lid:
        logger.warning("Mensagem %s descartada: contato sem número reconhecível", msg_id)
        return None

    tipo, texto, midia = _conteudo(_desembrulhar(bruto))
    if not tipo:
        return None
    try:
        timestamp = int(item.get("messageTimestamp") or 0)
    except (TypeError, ValueError):
        timestamp = 0

    de_mim = key.get("fromMe") is True
    return {
        "tipo_evento": "mensagem",
        "id": msg_id,
        "telefone": telefone,
        "lid": lid,
        "de_mim": de_mim,
        "nome": "" if de_mim else str(item.get("pushName") or "").strip(),
        "tipo": tipo,
        "texto": texto,
        "timestamp": timestamp,
        "remote_jid": remote_jid,
        "mimetype": str(midia.get("mimetype") or "") if midia else "",
        "arquivo_nome": str(midia.get("fileName") or "") if midia else "",
        # Só o necessário para pedir a mídia à Evolution depois (getBase64FromMediaMessage).
        "midia": {"key": key, "message": bruto} if tipo in _MIDIA else None,
    }


def interpretar(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Converte o payload em uma lista de eventos internos."""
    eventos: list[dict[str, Any]] = []
    evento = nome_evento(payload)
    dados = payload.get("data")
    if not dados:
        return eventos
    itens = dados if isinstance(dados, list) else [dados]
    if isinstance(dados, dict) and isinstance(dados.get("messages"), list):
        itens = dados["messages"]

    if evento in ("messages.upsert", "messages.set"):
        for item in itens:
            ev = interpretar_mensagem(item)
            if ev:
                eventos.append(ev)

    elif evento == "messages.update":
        for item in itens:
            if not isinstance(item, dict):
                continue
            msg_id = str(item.get("keyId") or (item.get("key") or {}).get("id") or item.get("id") or "")
            bruto = str(item.get("status") or (item.get("update") or {}).get("status") or "").upper()
            if msg_id and bruto == "DELETED":
                eventos.append({"tipo_evento": "revogacao", "id": msg_id})
            elif msg_id and bruto in _STATUS:
                eventos.append({"tipo_evento": "status", "id": msg_id, "status": _STATUS[bruto]})

    elif evento == "messages.delete":
        for item in itens:
            if isinstance(item, dict):
                msg_id = str(item.get("id") or item.get("keyId") or (item.get("key") or {}).get("id") or "")
                if msg_id:
                    eventos.append({"tipo_evento": "revogacao", "id": msg_id})

    elif evento in ("contacts.upsert", "contacts.update", "chats.upsert", "chats.update"):
        for item in itens:
            if not isinstance(item, dict):
                continue
            jids = [str(item.get(k) or "") for k in ("remoteJid", "id", "jid", "lid", "remoteJidAlt", "phoneNumber")]
            jids = [j for j in jids if j and "@g.us" not in j and "broadcast" not in j]
            lid = next((digitos_do_jid(j) for j in jids if j.endswith("@lid")), "")
            telefone = next((digitos_do_jid(j) for j in jids if j.endswith("@s.whatsapp.net")), "")
            nome = str(item.get("pushName") or item.get("name") or item.get("notify") or "").strip()
            if lid or telefone:
                eventos.append({"tipo_evento": "contato", "telefone": com_ddi(telefone) if telefone else "", "lid": lid, "nome": nome})

    elif evento == "connection.update":
        estado = str((dados if isinstance(dados, dict) else {}).get("state") or "")
        if estado:
            eventos.append({"tipo_evento": "conexao", "estado": estado})

    return eventos
