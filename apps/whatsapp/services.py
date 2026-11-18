"""Serviço único de WhatsApp: o chat, as mensagens automáticas dos pedidos e o link de pagamento
usam estas funções. O provedor (Umbler Talk por padrão, ou Evolution) fica atrás de ``provedores``.
"""
from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from . import provedores
from .models import Conversa, EventoWebhook, Instancia, Mensagem
from .parser import interpretar
from .provedores import ProvedorErro
from .telefone import telefone_canonico
from .umbler_parser import interpretar_umbler

logger = logging.getLogger("whatsapp")

MENSAGEM_APAGADA = "Mensagem apagada"
_ORDEM_STATUS = {Mensagem.Status.PENDENTE: 0, Mensagem.Status.ENVIADA: 1, Mensagem.Status.ENTREGUE: 2, Mensagem.Status.LIDA: 3}
_PREVIA_MIDIA = {
    "imagem": "Foto", "audio": "Áudio", "video": "Vídeo", "documento": "Documento",
    "figurinha": "Figurinha", "localizacao": "Localização",
}

TIPOS_PERMITIDOS = {
    "imagem": {"image/jpeg", "image/png", "image/webp", "image/gif"},
    "video": {"video/mp4", "video/3gpp", "video/quicktime"},
    "audio": {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/aac", "audio/webm", "audio/wav", "audio/x-wav"},
    "documento": {
        "application/pdf", "application/zip", "text/plain", "text/csv",
        "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/postscript", "image/vnd.adobe.photoshop", "application/illustrator", "image/svg+xml", "image/tiff",
        "application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.spreadsheet",
    },
}


class ChatErro(Exception):
    """Erro de regra do chat com mensagem pronta para a equipe."""


def provedor(instancia: Instancia):
    return provedores.provedor_para(instancia)


def limite_upload_bytes() -> int:
    return int(getattr(settings, "WHATSAPP_MAX_UPLOAD_MB", 16)) * 1024 * 1024


def janela_revogacao() -> timedelta:
    return timedelta(hours=int(getattr(settings, "WHATSAPP_REVOGAR_ATE_HORAS", 48)))


def previa(texto: str, tipo: str) -> str:
    base = (texto or "").replace("\n", " ").strip()
    if tipo != Mensagem.Tipo.TEXTO:
        rotulo = _PREVIA_MIDIA.get(tipo, "Anexo")
        base = f"{rotulo}: {base}" if base else rotulo
    return base[:160]


# ---------------------------------------------------------------------------
# Contatos, conversas e clientes
# ---------------------------------------------------------------------------

def buscar_cliente_por_telefone(telefone: str):
    from apps.payments.models import Cliente

    chave = telefone_canonico(telefone)
    if len(chave) < 10:
        return None
    for candidato in Cliente.objects.filter(telefone__contains=chave[-4:]).order_by("-updated_at")[:50]:
        if telefone_canonico(candidato.telefone) == chave:
            return candidato
    return None


def _localizar(instancia: Instancia, telefone: str, lid: str) -> Conversa | None:
    qs = Conversa.objects.filter(instancia=instancia)
    if lid:
        conversa = qs.filter(lid=lid).first()
        if conversa:
            return conversa
    if telefone:
        return qs.filter(telefone=telefone_canonico(telefone)).first()
    return None


def obter_conversa(instancia: Instancia, *, telefone: str = "", lid: str = "", nome: str = "", criar: bool = True) -> Conversa | None:
    """Acha (ou cria) a conversa sem duplicar contatos que aparecem ora pelo número, ora pelo LID."""
    telefone = telefone_canonico(telefone) if telefone else ""
    conversa = _localizar(instancia, telefone, lid)
    if conversa:
        campos = []
        if lid and not conversa.lid:
            conversa.lid = lid
            campos.append("lid")
        if telefone and not conversa.telefone and not Conversa.objects.filter(instancia=instancia, telefone=telefone).exists():
            conversa.telefone = telefone
            campos.append("telefone")
        if nome and not conversa.nome:
            conversa.nome = nome[:150]
            campos.append("nome")
        if not conversa.cliente_id and (conversa.telefone or telefone):
            encontrado = buscar_cliente_por_telefone(conversa.telefone or telefone)
            if encontrado:
                conversa.cliente = encontrado
                campos.append("cliente")
        if campos:
            conversa.save(update_fields=campos)
        return conversa
    if not criar or not (telefone or lid):
        return None
    try:
        with transaction.atomic():
            return Conversa.objects.create(
                instancia=instancia, telefone=telefone or None, lid=lid or None, nome=nome[:150],
                cliente=buscar_cliente_por_telefone(telefone) if telefone else None,
            )
    except IntegrityError:
        # Outro processo (webhook paralelo) criou a mesma conversa ao mesmo tempo.
        return _localizar(instancia, telefone, lid)


def atualizar_contato(instancia: Instancia, *, telefone: str = "", lid: str = "", nome: str = "") -> Conversa | None:
    """contacts/chats.upsert: só enriquece conversas existentes (não cria uma por contato da agenda)."""
    conversa = _localizar(instancia, telefone_canonico(telefone) if telefone else "", lid)
    if not conversa and lid and telefone:
        conversa = _localizar(instancia, telefone_canonico(telefone), "")
    if conversa:
        return obter_conversa(instancia, telefone=telefone, lid=lid, nome=nome)
    return None


def vincular_cliente(conversa: Conversa, cliente_obj) -> None:
    conversa.cliente = cliente_obj
    conversa.save(update_fields=["cliente"])


def cadastrar_cliente(conversa: Conversa, *, nome: str, usuario) -> Any:
    from apps.payments.models import Cliente

    if conversa.cliente_id:
        raise ChatErro("Esta conversa já está vinculada a um cliente.")
    if not conversa.telefone:
        raise ChatErro("O WhatsApp ainda não informou o número deste contato.")
    nome = (nome or "").strip()
    if len(nome) < 2:
        raise ChatErro("Informe o nome do cliente.")
    existente = buscar_cliente_por_telefone(conversa.telefone)
    if existente:
        vincular_cliente(conversa, existente)
        return existente
    novo = Cliente.objects.create(nome=nome[:200], telefone=conversa.telefone, observacoes="Cadastro criado pelo chat do WhatsApp.")
    vincular_cliente(conversa, novo)
    try:
        from apps.audit.services import record_audit

        record_audit(usuario, "cliente_criado_pelo_chat", "cliente", novo.pk, after={"nome": novo.nome})
    except Exception:  # auditoria nunca impede o cadastro
        logger.exception("Falha ao registrar auditoria do cadastro de cliente pelo chat")
    return novo


def _tocar_conversa(conversa: Conversa, msg: Mensagem, *, recebida: bool) -> None:
    """Atualiza prévia/ordem da lista (só se a mensagem for a mais recente)."""
    if msg.criada_em < conversa.ultima_mensagem_em and conversa.ultima_previa:
        return
    conversa.ultima_mensagem_em = msg.criada_em
    conversa.ultima_previa = previa(msg.texto, msg.tipo)
    conversa.ultima_direcao = msg.direcao
    campos = ["ultima_mensagem_em", "ultima_previa", "ultima_direcao"]
    if recebida and conversa.arquivada_em:
        conversa.arquivada_em = None
        campos.append("arquivada_em")
    conversa.save(update_fields=campos)


def atualizar_previa(conversa: Conversa) -> None:
    ultima = conversa.mensagens.filter(ocultada_em__isnull=True).order_by("-criada_em", "-pk").first()
    if not ultima:
        conversa.ultima_previa = ""
    elif ultima.revogada:
        conversa.ultima_previa = MENSAGEM_APAGADA
    else:
        conversa.ultima_previa = previa(ultima.texto, ultima.tipo)
    conversa.save(update_fields=["ultima_previa"])


def _hora(timestamp: int | None) -> datetime:
    if timestamp:
        try:
            return datetime.fromtimestamp(int(timestamp), tz=UTC)
        except (OverflowError, OSError, ValueError):
            pass
    return timezone.now()


# ---------------------------------------------------------------------------
# Recebimento (webhook)
# ---------------------------------------------------------------------------

def _notificar_nova_mensagem(conversa: Conversa) -> None:
    from apps.notifications.services import notify_user

    destinatarios = []
    if conversa.instancia.vendedora_id:
        destinatarios = [conversa.instancia.vendedora]
    else:
        from apps.accounts.models import User

        destinatarios = list(User.objects.filter(is_active=True, role__in=[User.Role.ADMINISTRATOR]))
        if conversa.instancia.compartilhada:
            destinatarios += list(User.objects.filter(is_active=True, role=User.Role.EMPLOYEE, sector=User.Sector.ATENDIMENTO))
    link = f"/chat/?c={conversa.pk}"
    for usuario in {u.pk: u for u in destinatarios}.values():
        notify_user(usuario, "Nova mensagem no WhatsApp", f"{conversa.nome_exibicao} enviou uma mensagem.", link)


@transaction.atomic
def registrar_mensagem_recebida(instancia: Instancia, ev: dict[str, Any]) -> Mensagem | None:
    conversa = obter_conversa(instancia, telefone=ev.get("telefone", ""), lid=ev.get("lid", ""), nome=ev.get("nome", ""))
    if not conversa:
        return None
    if ev.get("id"):
        existente = conversa.mensagens.filter(id_externo=ev["id"]).first()
        if existente:
            return existente
    msg = Mensagem.objects.create(
        conversa=conversa, direcao=Mensagem.Direcao.RECEBIDA, tipo=ev.get("tipo", "texto"),
        texto=ev.get("texto", ""), id_externo=ev.get("id") or None, remote_jid=ev.get("remote_jid", ""),
        mimetype=ev.get("mimetype", ""), arquivo_nome=(ev.get("arquivo_nome") or "")[:160],
        midia_pendente=ev.get("midia"), status=Mensagem.Status.ENTREGUE, origem=Mensagem.Origem.CLIENTE,
        criada_em=_hora(ev.get("timestamp")),
    )
    estava_lida = conversa.nao_lidas == 0
    Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=F("nao_lidas") + 1)
    conversa.refresh_from_db(fields=["nao_lidas"])
    _tocar_conversa(conversa, msg, recebida=True)
    if estava_lida:
        transaction.on_commit(lambda: _notificar_nova_mensagem(conversa))
    return msg


@transaction.atomic
def registrar_mensagem_do_celular(instancia: Instancia, ev: dict[str, Any]) -> Mensagem | None:
    """fromMe: enviada pelo app do WhatsApp no celular — ou o eco de uma enviada pelo sistema."""
    conversa = obter_conversa(instancia, telefone=ev.get("telefone", ""), lid=ev.get("lid", ""))
    if not conversa:
        return None
    msg_id = ev.get("id", "")
    if msg_id:
        existente = conversa.mensagens.filter(id_externo=msg_id).first()
        if existente:
            return existente
    # O eco pode chegar antes de o envio pelo sistema gravar o id: casa pelo texto entre as pendentes recentes.
    quando = _hora(ev.get("timestamp"))
    pendentes = conversa.mensagens.select_for_update().filter(
        direcao=Mensagem.Direcao.ENVIADA, id_externo__isnull=True, criada_em__gte=quando - timedelta(minutes=3),
    ).exclude(status=Mensagem.Status.FALHOU).order_by("-criada_em")[:10]
    for candidata in pendentes:
        if candidata.tipo == ev.get("tipo") and (candidata.texto or "").strip() == (ev.get("texto") or "").strip():
            candidata.id_externo = msg_id or None
            candidata.remote_jid = candidata.remote_jid or ev.get("remote_jid", "")
            if candidata.status == Mensagem.Status.PENDENTE:
                candidata.status = Mensagem.Status.ENVIADA
            candidata.save(update_fields=["id_externo", "remote_jid", "status"])
            return candidata
    msg = Mensagem.objects.create(
        conversa=conversa, direcao=Mensagem.Direcao.ENVIADA, tipo=ev.get("tipo", "texto"), texto=ev.get("texto", ""),
        id_externo=msg_id or None, remote_jid=ev.get("remote_jid", ""), mimetype=ev.get("mimetype", ""),
        arquivo_nome=(ev.get("arquivo_nome") or "")[:160], midia_pendente=ev.get("midia"),
        status=Mensagem.Status.ENVIADA, origem=Mensagem.Origem.CELULAR, remetente=instancia.vendedora, criada_em=quando,
    )
    if conversa.nao_lidas:
        Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=0)
        conversa.nao_lidas = 0
    _tocar_conversa(conversa, msg, recebida=False)
    return msg


def aplicar_status(instancia: Instancia, id_externo: str, status: str) -> None:
    """Só avança (enviada -> entregue -> lida); eventos atrasados não fazem o tique voltar."""
    for msg in Mensagem.objects.filter(conversa__instancia=instancia, id_externo=id_externo, direcao=Mensagem.Direcao.ENVIADA):
        if _ORDEM_STATUS.get(status, -1) > _ORDEM_STATUS.get(msg.status, -1):
            msg.status = status
            msg.save(update_fields=["status"])


def aplicar_revogacao(instancia: Instancia, id_externo: str) -> Mensagem | None:
    msg = Mensagem.objects.filter(conversa__instancia=instancia, id_externo=id_externo).select_related("conversa").first()
    if not msg or msg.revogada:
        return msg
    msg.revogada_em = timezone.now()
    msg.save(update_fields=["revogada_em"])
    atualizar_previa(msg.conversa)
    return msg


def _chave_evento(ev: dict[str, Any]) -> str:
    tipo = ev.get("tipo_evento")
    if tipo == "status":
        return f"{ev.get('id')}:{ev.get('status')}"
    return str(ev.get("id") or "")


def processar_webhook(instancia: Instancia, payload: dict[str, Any]) -> int:
    """Webhook da Evolution (cada mensagem/status tem seu próprio id)."""
    return aplicar_eventos(instancia, interpretar(payload))


def instancia_do_canal_umbler(canal_id: str, canal_telefone: str) -> Instancia | None:
    qs = Instancia.objects.filter(ativa=True, provedor=Instancia.Provedor.UMBLER)
    if canal_id:
        inst = qs.filter(canal_id=canal_id).first()
        if inst:
            return inst
    if canal_telefone:
        alvo = telefone_canonico(canal_telefone)
        for inst in qs.exclude(telefone_canal=""):
            if telefone_canonico(inst.telefone_canal) == alvo:
                return inst
    return None


def processar_webhook_umbler(payload: dict[str, Any]) -> dict[str, Any]:
    """Webhook da Umbler Talk. O ``EventId`` se repete nas re-tentativas, então é a chave de idempotência."""
    dados = interpretar_umbler(payload)
    instancia = instancia_do_canal_umbler(dados["canal_id"], dados["canal_telefone"])
    if instancia is None:
        if dados["eventos"]:
            logger.warning("Webhook da Umbler para canal não cadastrado (%s)", dados["canal_id"] or "sem id")
        return {"ignorado": True, "processados": 0}
    if not dados["eventos"]:
        return {"ignorado": False, "processados": 0}
    registro = None
    if dados["evento_id"]:
        try:
            with transaction.atomic():
                registro = EventoWebhook.objects.create(instancia=instancia.nome, tipo="umbler", chave=dados["evento_id"][:140])
        except IntegrityError:
            return {"ignorado": False, "processados": 0, "repetido": True}
    processados = aplicar_eventos(instancia, dados["eventos"])
    if registro:
        if processados == len(dados["eventos"]):
            EventoWebhook.objects.filter(pk=registro.pk).update(processado_em=timezone.now())
        else:
            # Falhou algo: libera o EventId para a re-tentativa da Umbler (a mensagem não duplica pelo id).
            EventoWebhook.objects.filter(pk=registro.pk).delete()
    return {"ignorado": False, "processados": processados}


def aplicar_eventos(instancia: Instancia, eventos: list[dict[str, Any]]) -> int:
    """Aplica cada evento isoladamente: um erro não derruba os outros do mesmo lote."""
    processados = 0
    for ev in eventos:
        tipo = ev["tipo_evento"]
        registro = None
        chave = _chave_evento(ev)
        if tipo in ("mensagem", "status", "revogacao") and chave:
            try:
                with transaction.atomic():
                    registro = EventoWebhook.objects.create(instancia=instancia.nome, tipo=tipo, chave=chave[:140])
            except IntegrityError:
                continue  # evento repetido: já aplicado
        try:
            with transaction.atomic():
                if tipo == "mensagem":
                    if ev.get("de_mim"):
                        registrar_mensagem_do_celular(instancia, ev)
                    else:
                        registrar_mensagem_recebida(instancia, ev)
                elif tipo == "status":
                    aplicar_status(instancia, ev["id"], ev["status"])
                elif tipo == "revogacao":
                    aplicar_revogacao(instancia, ev["id"])
                elif tipo == "contato":
                    atualizar_contato(instancia, telefone=ev.get("telefone", ""), lid=ev.get("lid", ""), nome=ev.get("nome", ""))
                elif tipo == "conexao":
                    Instancia.objects.filter(pk=instancia.pk).update(estado=ev["estado"][:12], estado_verificado_em=timezone.now())
            processados += 1
            if registro:
                EventoWebhook.objects.filter(pk=registro.pk).update(processado_em=timezone.now())
        except Exception:
            logger.exception("Erro ao aplicar evento %s da instância %s", tipo, instancia.nome)
            if registro:
                # Libera para reprocessar quando o provedor reenviar o mesmo evento.
                EventoWebhook.objects.filter(pk=registro.pk, processado_em__isnull=True).delete()
    return processados


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------

def _finalizar_envio(msg: Mensagem, resultado: provedores.Envio) -> Mensagem:
    if resultado.ok:
        # Na Umbler um 200 só quer dizer "na fila": fica "pendente" até o estado real ser consultado.
        msg.status = resultado.status if resultado.status in (Mensagem.Status.PENDENTE, Mensagem.Status.ENVIADA) else Mensagem.Status.ENVIADA
        msg.id_externo = resultado.id_mensagem or msg.id_externo or None
        msg.remote_jid = resultado.remote_jid or msg.remote_jid
        msg.erro = ""
    else:
        msg.status = Mensagem.Status.FALHOU
        msg.erro = (resultado.erro or "O WhatsApp não aceitou a mensagem.")[:200] + " Confira se o número está conectado e tente de novo."
    try:
        with transaction.atomic():
            msg.save(update_fields=["status", "id_externo", "remote_jid", "erro"])
    except IntegrityError:
        # O eco do webhook gravou a mesma mensagem em outra linha antes de nós: fica a do webhook, com nossos dados.
        eco = Mensagem.objects.get(conversa=msg.conversa, id_externo=msg.id_externo)
        eco.remetente, eco.origem, eco.pedido = msg.remetente, msg.origem, msg.pedido
        eco.save(update_fields=["remetente", "origem", "pedido"])
        Mensagem.objects.filter(pk=msg.pk).delete()
        return eco
    return msg


def enviar_texto(conversa: Conversa, texto: str, *, usuario=None, origem: str = Mensagem.Origem.CHAT, pedido=None) -> Mensagem:
    texto = (texto or "").strip()
    if not texto:
        raise ChatErro("Digite uma mensagem.")
    if len(texto) > 4096:
        raise ChatErro("Mensagem muito longa (máximo de 4096 caracteres).")
    if not conversa.destino:
        raise ChatErro("Este contato ainda não tem número conhecido.")
    msg = Mensagem.objects.create(
        conversa=conversa, direcao=Mensagem.Direcao.ENVIADA, tipo=Mensagem.Tipo.TEXTO, texto=texto,
        status=Mensagem.Status.PENDENTE, origem=origem, remetente=usuario, pedido=pedido,
    )
    try:
        resultado = provedor(conversa.instancia).enviar_texto(conversa.destino, texto, nome_contato=conversa.nome)
    except ProvedorErro as exc:
        msg.status, msg.erro = Mensagem.Status.FALHOU, str(exc)[:255]
        msg.save(update_fields=["status", "erro"])
        _tocar_conversa(conversa, msg, recebida=False)
        return msg
    msg = _finalizar_envio(msg, resultado)
    if conversa.nao_lidas:
        Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=0)
    _tocar_conversa(conversa, msg, recebida=False)
    return msg


def tipo_por_mimetype(mimetype: str, nome: str = "") -> str | None:
    mimetype = (mimetype or "").lower() or (mimetypes.guess_type(nome)[0] or "")
    for tipo, permitidos in TIPOS_PERMITIDOS.items():
        if mimetype in permitidos:
            return tipo
    return None


@dataclass
class Arquivo:
    conteudo: bytes
    nome: str
    mimetype: str


def ler_upload(upload) -> Arquivo:
    if upload.size > limite_upload_bytes():
        raise ChatErro(f"Arquivo maior que {getattr(settings, 'WHATSAPP_MAX_UPLOAD_MB', 16)} MB.")
    nome = os.path.basename(upload.name or "arquivo")[:120]
    mimetype = (getattr(upload, "content_type", "") or mimetypes.guess_type(nome)[0] or "").split(";")[0].strip().lower()
    return Arquivo(upload.read(), nome, mimetype)


def enviar_midia(conversa: Conversa, arquivo: Arquivo, *, legenda: str = "", usuario=None, pedido=None,
                 origem: str = Mensagem.Origem.CHAT, forcar_documento: bool = False) -> Mensagem:
    if len(arquivo.conteudo) > limite_upload_bytes():
        raise ChatErro(f"Arquivo maior que {getattr(settings, 'WHATSAPP_MAX_UPLOAD_MB', 16)} MB.")
    tipo = tipo_por_mimetype(arquivo.mimetype, arquivo.nome)
    if not tipo:
        raise ChatErro("Tipo de arquivo não permitido no chat.")
    if forcar_documento and tipo in ("imagem", "video"):
        tipo = "documento"  # arte vai sem compressão do WhatsApp
    if not conversa.destino:
        raise ChatErro("Este contato ainda não tem número conhecido.")
    legenda = (legenda or "").strip()[:1024]
    msg = Mensagem(
        conversa=conversa, direcao=Mensagem.Direcao.ENVIADA, tipo=tipo, texto=legenda, status=Mensagem.Status.PENDENTE,
        origem=origem, remetente=usuario, pedido=pedido, mimetype=arquivo.mimetype, arquivo_nome=arquivo.nome,
        tamanho=len(arquivo.conteudo),
    )
    msg.arquivo.save(arquivo.nome, ContentFile(arquivo.conteudo), save=False)
    msg.save()
    try:
        resultado = provedor(conversa.instancia).enviar_midia(
            conversa.destino, tipo=tipo, conteudo=arquivo.conteudo,
            mimetype=arquivo.mimetype, nome_arquivo=arquivo.nome, legenda=legenda,
        )
    except ProvedorErro as exc:
        msg.status, msg.erro = Mensagem.Status.FALHOU, str(exc)[:255]
        msg.save(update_fields=["status", "erro"])
        _tocar_conversa(conversa, msg, recebida=False)
        return msg
    msg = _finalizar_envio(msg, resultado)
    _tocar_conversa(conversa, msg, recebida=False)
    return msg


def reenviar(msg: Mensagem, usuario) -> Mensagem:
    if msg.status != Mensagem.Status.FALHOU or msg.direcao != Mensagem.Direcao.ENVIADA:
        raise ChatErro("Só mensagens que falharam podem ser reenviadas.")
    conversa = msg.conversa
    if msg.tipo == Mensagem.Tipo.TEXTO:
        novo = enviar_texto(conversa, msg.texto, usuario=usuario, origem=msg.origem, pedido=msg.pedido)
    else:
        with msg.arquivo.open("rb") as fh:
            conteudo = fh.read()
        novo = enviar_midia(conversa, Arquivo(conteudo, msg.arquivo_nome, msg.mimetype), legenda=msg.texto,
                            usuario=usuario, pedido=msg.pedido, origem=msg.origem)
    msg.ocultada_em, msg.ocultada_por = timezone.now(), usuario
    msg.save(update_fields=["ocultada_em", "ocultada_por"])
    return novo


# ---------------------------------------------------------------------------
# Apagar
# ---------------------------------------------------------------------------

def opcoes_apagar(msg: Mensagem, usuario) -> dict[str, Any]:
    from .permissoes import eh_gestor

    autor = bool(usuario and msg.remetente_id == usuario.pk)
    gestor = eh_gestor(usuario)
    if msg.ocultada_em or msg.revogada:
        return {"para_mim": False, "para_todos": "nao", "motivo": ""}
    para_mim = msg.direcao == Mensagem.Direcao.ENVIADA and (autor or gestor) or (msg.direcao == Mensagem.Direcao.RECEBIDA and gestor)
    resultado = {"para_mim": bool(para_mim), "para_todos": "nao", "motivo": ""}
    if msg.direcao != Mensagem.Direcao.ENVIADA or not (autor or gestor):
        return resultado
    if msg.status in (Mensagem.Status.FALHOU, Mensagem.Status.PENDENTE) or not msg.id_externo:
        resultado.update(para_todos="indisponivel", motivo="A mensagem não chegou ao cliente; apague só no sistema.")
    elif timezone.now() - msg.criada_em > janela_revogacao():
        horas = int(janela_revogacao().total_seconds() // 3600)
        resultado.update(para_todos="expirado", motivo=f"O WhatsApp só permite apagar para todos até {horas} horas depois do envio.")
    else:
        resultado["para_todos"] = "sim"
    return resultado


def apagar_para_mim(msg: Mensagem, usuario) -> Mensagem:
    if not opcoes_apagar(msg, usuario)["para_mim"]:
        raise ChatErro("Você não pode apagar esta mensagem.")
    msg.ocultada_em, msg.ocultada_por = timezone.now(), usuario
    msg.save(update_fields=["ocultada_em", "ocultada_por"])
    atualizar_previa(msg.conversa)
    return msg


def apagar_para_todos(msg: Mensagem, usuario) -> Mensagem:
    opcoes = opcoes_apagar(msg, usuario)
    if opcoes["para_todos"] != "sim":
        raise ChatErro(opcoes["motivo"] or "Esta mensagem não pode ser apagada para todos.")
    remote_jid = msg.remote_jid or (f"{msg.conversa.telefone}@s.whatsapp.net" if msg.conversa.telefone else f"{msg.conversa.lid}@lid")
    try:
        apagou = provedor(msg.conversa.instancia).apagar_para_todos(id_mensagem=msg.id_externo, remote_jid=remote_jid)
    except ProvedorErro as exc:
        raise ChatErro(str(exc)) from exc
    if not apagou:
        raise ChatErro("O WhatsApp não confirmou a exclusão. Verifique a conexão e tente de novo.")
    msg.revogada_em, msg.revogada_por = timezone.now(), usuario
    msg.save(update_fields=["revogada_em", "revogada_por"])
    atualizar_previa(msg.conversa)
    return msg


# ---------------------------------------------------------------------------
# Mídia recebida (baixada sob demanda)
# ---------------------------------------------------------------------------

_EXTENSOES = {"imagem": ".jpg", "audio": ".ogg", "video": ".mp4", "documento": ".bin", "figurinha": ".webp"}


def garantir_midia(msg: Mensagem) -> Mensagem:
    if msg.arquivo or not msg.midia_pendente:
        return msg
    try:
        conteudo, mimetype, nome_original = provedor(msg.conversa.instancia).baixar_midia(msg.midia_pendente)
    except ProvedorErro as exc:
        raise ChatErro(str(exc)) from exc
    if nome_original and not msg.arquivo_nome:
        msg.arquivo_nome = os.path.basename(nome_original)[:160]
    if len(conteudo) > limite_upload_bytes() * 4:
        raise ChatErro("Mídia grande demais para guardar no sistema.")
    mimetype = (mimetype or msg.mimetype or "application/octet-stream").split(";")[0]
    nome = msg.arquivo_nome or f"whatsapp_{msg.pk}{mimetypes.guess_extension(mimetype) or _EXTENSOES.get(msg.tipo, '.bin')}"
    msg.arquivo.save(os.path.basename(nome)[:120], ContentFile(conteudo), save=False)
    msg.mimetype, msg.tamanho, msg.midia_pendente = mimetype, len(conteudo), None
    msg.arquivo_nome = msg.arquivo_nome or os.path.basename(nome)[:160]
    msg.save(update_fields=["arquivo", "mimetype", "tamanho", "midia_pendente", "arquivo_nome"])
    return msg


def atualizar_status_enviadas(*, horas: int = 24, limite: int = 200) -> dict[str, int]:
    """A Umbler não manda webhook de status: consulta o estado das enviadas recentes que ainda podem mudar."""
    from collections import Counter

    resumo: Counter[str] = Counter()
    desde = timezone.now() - timedelta(hours=horas)
    pendentes = (
        Mensagem.objects.select_related("conversa__instancia")
        .filter(direcao=Mensagem.Direcao.ENVIADA, criada_em__gte=desde, id_externo__isnull=False, revogada_em__isnull=True,
                conversa__instancia__provedor=Instancia.Provedor.UMBLER)
        .exclude(status__in=[Mensagem.Status.LIDA, Mensagem.Status.FALHOU])
        .order_by("-criada_em")[:limite]
    )
    for msg in pendentes:
        novo = provedor(msg.conversa.instancia).status_mensagem(msg.id_externo)
        if novo == "revogada":
            aplicar_revogacao(msg.conversa.instancia, msg.id_externo)
            resumo["revogada"] += 1
        elif novo == Mensagem.Status.FALHOU and msg.status != Mensagem.Status.FALHOU:
            Mensagem.objects.filter(pk=msg.pk).update(status=novo, erro="A Umbler não conseguiu entregar a mensagem.")
            resumo["falhou"] += 1
        elif novo and _ORDEM_STATUS.get(novo, -1) > _ORDEM_STATUS.get(msg.status, -1):
            Mensagem.objects.filter(pk=msg.pk).update(status=novo)
            resumo[novo] += 1
        else:
            resumo["sem_alteracao"] += 1
    return dict(resumo)


def marcar_lida(conversa: Conversa) -> None:
    if conversa.nao_lidas:
        Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=0)
        conversa.nao_lidas = 0


# ---------------------------------------------------------------------------
# Pedidos
# ---------------------------------------------------------------------------

def instancia_para_pedido(order, usuario=None) -> Instancia | None:
    """Número que fala com o cliente do pedido: o de quem está agindo, o do responsável, ou o da empresa."""
    for pessoa in (usuario, getattr(order, "responsible", None)):
        if pessoa is not None:
            inst = Instancia.objects.filter(ativa=True, vendedora=pessoa).first()
            if inst:
                return inst
    return Instancia.objects.filter(ativa=True, padrao_automaticas=True).first()


def conversa_do_pedido(order, usuario=None, *, criar: bool = True) -> Conversa | None:
    instancia = instancia_para_pedido(order, usuario)
    if not instancia or not telefone_canonico(order.client_whatsapp):
        return None
    conversa = obter_conversa(instancia, telefone=order.client_whatsapp, nome=order.client_name, criar=criar)
    if conversa and not conversa.cliente_id and order.cliente_id:
        vincular_cliente(conversa, order.cliente)
    return conversa


def enviar_mensagem_do_pedido(order, texto: str, *, usuario, descricao: str) -> Mensagem:
    """Mensagem automática do pedido (orçamento, pronto, entregue, link de pagamento) pelo serviço único."""
    from apps.orders.models import OrderHistory

    conversa = conversa_do_pedido(order, usuario)
    if not conversa:
        raise ChatErro("Nenhum número de WhatsApp conectado para este pedido, ou o telefone do cliente é inválido.")
    msg = enviar_texto(conversa, texto, usuario=usuario, origem=Mensagem.Origem.AUTOMATICA, pedido=order)
    if msg.status != Mensagem.Status.FALHOU:
        OrderHistory.objects.create(order=order, user=usuario, action="whatsapp_enviado", description=f"{descricao} enviado pelo WhatsApp do sistema.")
    return msg
