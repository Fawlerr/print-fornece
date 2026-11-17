from __future__ import annotations

import hmac
import json
import logging
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import services
from .evolution import EvolutionClient, EvolutionErro, nome_instancia_valido
from .provedores import ProvedorErro, ProvedorUmbler
from .telefone import com_ddi
from .umbler import ESTADOS_CANAL, UmblerClient, UmblerErro, campo
from .models import Conversa, Etiqueta, Instancia, Mensagem
from .permissoes import (
    conversas_visiveis,
    eh_gestor,
    instancias_visiveis,
    pode_gerenciar_instancias,
    pode_usar_chat,
    pode_ver_conversa,
)
from .telefone import formatar_telefone, telefone_canonico, telefone_valido

logger = logging.getLogger("whatsapp")

LIMITE_LISTA = 80
LIMITE_MENSAGENS = 60
SESSAO_PERFIL = "chat_perfil"


def _erro(mensagem: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "erro": mensagem}, status=status)


def chat_required(view):
    @login_required
    @wraps(view)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        if not pode_usar_chat(request.user):
            if request.path.startswith("/chat/api/"):
                return _erro("Sem permissão para o chat.", 403)
            return render(request, "errors/403.html", status=403)
        return view(request, *args, **kwargs)

    return _wrapped


def _conversa_ou_404(request: HttpRequest, pk: int) -> Conversa:
    conversa = get_object_or_404(Conversa.objects.select_related("instancia", "cliente"), pk=pk)
    if not pode_ver_conversa(request.user, conversa):
        raise Http404
    return conversa


def _mensagem_ou_404(request: HttpRequest, pk: int) -> Mensagem:
    msg = get_object_or_404(Mensagem.objects.select_related("conversa__instancia", "remetente", "pedido"), pk=pk)
    if not pode_ver_conversa(request.user, msg.conversa):
        raise Http404
    return msg


def _dados(request: HttpRequest) -> dict:
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
    return request.POST


# ---------------------------------------------------------------------------
# Serialização
# ---------------------------------------------------------------------------

def _hora_relativa(quando) -> str:
    if not quando:
        return ""
    agora, local = timezone.localtime(), timezone.localtime(quando)
    dias = (agora.date() - local.date()).days
    if dias <= 0:
        return local.strftime("%H:%M")
    if dias == 1:
        return "Ontem"
    if dias < 7:
        return ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")[local.weekday()]
    return local.strftime("%d/%m/%y")


def _iniciais(nome: str) -> str:
    partes = [p for p in (nome or "").split() if p[:1].isalnum()]
    if not partes:
        return "?"
    return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else partes[0][1:2])).upper()


def serializar_conversa(c: Conversa) -> dict:
    return {
        "id": c.pk,
        "nome": c.nome_exibicao,
        "telefone": formatar_telefone(c.telefone) if c.telefone else "Número oculto pelo WhatsApp",
        "iniciais": _iniciais(c.nome_exibicao),
        "previa": c.ultima_previa,
        "direcao": c.ultima_direcao,
        "hora": _hora_relativa(c.ultima_mensagem_em),
        "nao_lidas": c.nao_lidas,
        "arquivada": c.arquivada_em is not None,
        "cliente_id": c.cliente_id,
        "instancia": {"id": c.instancia_id, "nome": c.instancia.apelido, "cor": c.instancia.cor},
        "etiquetas": [{"id": e.pk, "nome": e.nome, "cor": e.cor} for e in c.etiquetas.all()],
    }


def serializar_mensagem(m: Mensagem, usuario) -> dict:
    local = timezone.localtime(m.criada_em)
    midia = ""
    if m.tem_midia and not m.revogada:
        midia = reverse("whatsapp:midia", args=[m.pk])
    return {
        "id": m.pk,
        "direcao": m.direcao,
        "tipo": m.tipo,
        "texto": "" if m.revogada else m.texto,
        "midia": midia,
        "arquivo_nome": m.arquivo_nome,
        "mimetype": m.mimetype,
        "status": m.status,
        "erro": m.erro,
        "origem": m.origem,
        "origem_label": m.get_origem_display(),
        "remetente": (m.remetente.name or m.remetente.email) if m.remetente_id else "",
        "pedido": m.pedido.number if m.pedido_id else "",
        "hora": local.strftime("%H:%M"),
        "dia": local.strftime("%d/%m/%Y"),
        "revogada": m.revogada,
        "opcoes": services.opcoes_apagar(m, usuario),
    }


def _estado_mensagem(m: Mensagem) -> dict:
    return {"id": m.pk, "status": m.status, "revogada": m.revogada, "ocultada": m.ocultada_em is not None}


# ---------------------------------------------------------------------------
# Lista de conversas e perfis
# ---------------------------------------------------------------------------

def _perfil(request: HttpRequest) -> Instancia | None:
    """Instância cujo perfil está aberto (None = todas as que a pessoa pode ver). Lembrado na sessão."""
    valor = request.GET.get("perfil")
    if valor is not None:
        request.session[SESSAO_PERFIL] = valor
    else:
        valor = request.session.get(SESSAO_PERFIL, "todas")
    if not str(valor).isdigit():
        return None
    return instancias_visiveis(request.user).filter(pk=int(valor)).first()


def _perfis(request: HttpRequest, ativo: Instancia | None) -> list[dict]:
    instancias = list(instancias_visiveis(request.user).select_related("vendedora"))
    nao_lidas = dict(
        Conversa.objects.filter(instancia__in=instancias, arquivada_em__isnull=True)
        .values("instancia").annotate(total=Sum("nao_lidas")).values_list("instancia", "total")
    )
    perfis = []
    if len(instancias) > 1:
        perfis.append({"id": "todas", "nome": "Todas", "iniciais": "", "cor": "", "nao_lidas": sum(nao_lidas.values()), "ativo": ativo is None})
    for inst in instancias:
        perfis.append({
            "id": inst.pk, "nome": inst.apelido, "iniciais": _iniciais(inst.apelido), "cor": inst.cor,
            "estado": inst.estado, "nao_lidas": nao_lidas.get(inst.pk, 0) or 0,
            "ativo": (ativo is not None and ativo.pk == inst.pk) or len(instancias) == 1,
        })
    return perfis


def _lista(request: HttpRequest) -> dict:
    perfil = _perfil(request)
    qs = conversas_visiveis(request.user).select_related("instancia", "cliente").prefetch_related("etiquetas")
    if perfil:
        qs = qs.filter(instancia=perfil)
    filtro = request.GET.get("filtro", "")
    if filtro == "arquivadas":
        qs = qs.filter(arquivada_em__isnull=False)
    else:
        qs = qs.filter(arquivada_em__isnull=True)
        if filtro == "nao_lidas":
            qs = qs.filter(nao_lidas__gt=0)
    etiqueta = request.GET.get("etiqueta", "")
    if etiqueta.isdigit():
        qs = qs.filter(etiquetas__pk=int(etiqueta))
    termo = (request.GET.get("q") or "").strip()
    if termo:
        digitos = "".join(ch for ch in termo if ch.isdigit())
        filtro_busca = Q(nome__icontains=termo) | Q(cliente__nome__icontains=termo)
        if len(digitos) >= 4:
            filtro_busca |= Q(telefone__contains=digitos)
        qs = qs.filter(filtro_busca)
    base = conversas_visiveis(request.user)
    if perfil:
        base = base.filter(instancia=perfil)
    return {
        "ok": True,
        "conversas": [serializar_conversa(c) for c in qs.distinct()[:LIMITE_LISTA]],
        "perfis": _perfis(request, perfil),
        "contadores": {
            "nao_lidas": base.filter(arquivada_em__isnull=True, nao_lidas__gt=0).count(),
            "arquivadas": base.filter(arquivada_em__isnull=False).count(),
        },
    }


def _etiquetas_do_usuario(user):
    qs = Etiqueta.objects.all()
    if not eh_gestor(user):
        qs = qs.filter(Q(vendedora__isnull=True) | Q(vendedora=user))
    return qs


@chat_required
@require_GET
def chat(request: HttpRequest) -> HttpResponse:
    conversa_id = request.GET.get("c", "")
    aberta = None
    if conversa_id.isdigit():
        aberta = conversas_visiveis(request.user).filter(pk=int(conversa_id)).first()
    contexto = {
        "page_title": "Chat WhatsApp",
        "dados_iniciais": {
            **_lista(request),
            "aberta": aberta.pk if aberta else None,
            "etiquetas": [{"id": e.pk, "nome": e.nome, "cor": e.cor} for e in _etiquetas_do_usuario(request.user)],
            "gestor": eh_gestor(request.user),
            "limite_mb": getattr(settings, "WHATSAPP_MAX_UPLOAD_MB", 16),
            "tem_instancia": instancias_visiveis(request.user).exists(),
        },
        "pode_gerenciar": pode_gerenciar_instancias(request.user),
    }
    return render(request, "whatsapp/chat.html", contexto)


@chat_required
@require_GET
def api_conversas(request: HttpRequest) -> JsonResponse:
    return JsonResponse(_lista(request))


@chat_required
@require_GET
def api_mensagens(request: HttpRequest, pk: int) -> JsonResponse:
    conversa = _conversa_ou_404(request, pk)
    qs = conversa.mensagens.filter(ocultada_em__isnull=True).select_related("remetente", "pedido")
    depois = request.GET.get("depois", "")
    antes = request.GET.get("antes", "")
    if depois.isdigit():
        novas = list(qs.filter(pk__gt=int(depois)).order_by("pk")[:200])
    elif antes.isdigit():
        novas = list(reversed(qs.filter(pk__lt=int(antes)).order_by("-pk")[:LIMITE_MENSAGENS]))
    else:
        novas = list(reversed(qs.order_by("-criada_em", "-pk")[:LIMITE_MENSAGENS]))
    # Estados das últimas mensagens (tique de leitura, revogação, "apagar para mim" feito por outra pessoa).
    recentes = conversa.mensagens.order_by("-pk")[:40]
    if request.GET.get("ler") != "0":
        services.marcar_lida(conversa)
    return JsonResponse({
        "ok": True,
        "conversa": serializar_conversa(conversa),
        "mensagens": [serializar_mensagem(m, request.user) for m in novas],
        "estados": [_estado_mensagem(m) for m in recentes],
        "tem_anteriores": bool(novas) and not depois.isdigit() and qs.filter(pk__lt=novas[0].pk).exists(),
    })


@chat_required
@require_POST
def api_enviar(request: HttpRequest, pk: int) -> JsonResponse:
    conversa = _conversa_ou_404(request, pk)
    try:
        msg = services.enviar_texto(conversa, str(_dados(request).get("texto", "")), usuario=request.user)
    except services.ChatErro as exc:
        return _erro(str(exc))
    return JsonResponse({"ok": True, "mensagem": serializar_mensagem(msg, request.user)})


@chat_required
@require_POST
def api_enviar_midia(request: HttpRequest, pk: int) -> JsonResponse:
    conversa = _conversa_ou_404(request, pk)
    upload = request.FILES.get("arquivo")
    if not upload:
        return _erro("Escolha um arquivo.")
    try:
        arquivo = services.ler_upload(upload)
        msg = services.enviar_midia(
            conversa, arquivo, legenda=request.POST.get("legenda", ""), usuario=request.user,
            forcar_documento=request.POST.get("como_documento") == "1",
        )
    except services.ChatErro as exc:
        return _erro(str(exc))
    return JsonResponse({"ok": True, "mensagem": serializar_mensagem(msg, request.user)})


@chat_required
@require_POST
def api_enviar_anexo_pedido(request: HttpRequest, pk: int) -> JsonResponse:
    """Envia um arquivo já anexado a um pedido do cliente (arte, nota, comprovante)."""
    from apps.orders.models import OrderAttachment

    conversa = _conversa_ou_404(request, pk)
    anexo_id = str(_dados(request).get("anexo", ""))
    if not anexo_id.isdigit():
        return _erro("Arquivo inválido.")
    anexo = OrderAttachment.objects.select_related("order").filter(pk=int(anexo_id), removed_at__isnull=True).first()
    if not anexo or anexo.order_id not in {p["id"] for p in _pedidos_da_conversa(conversa)}:
        return _erro("Este arquivo não pertence a um pedido deste cliente.", 403)
    try:
        with anexo.file.open("rb") as fh:
            conteudo = fh.read()
        arquivo = services.Arquivo(conteudo, anexo.original_name[:120], anexo.content_type)
        msg = services.enviar_midia(conversa, arquivo, legenda=f"Pedido #{anexo.order.number}", usuario=request.user,
                                    pedido=anexo.order, forcar_documento=True)
    except (services.ChatErro, FileNotFoundError, OSError) as exc:
        return _erro(str(exc) if isinstance(exc, services.ChatErro) else "Arquivo do pedido não encontrado no servidor.")
    return JsonResponse({"ok": True, "mensagem": serializar_mensagem(msg, request.user)})


@chat_required
@require_POST
def api_apagar(request: HttpRequest, pk: int) -> JsonResponse:
    msg = _mensagem_ou_404(request, pk)
    escopo = _dados(request).get("escopo")
    try:
        if escopo == "mim":
            services.apagar_para_mim(msg, request.user)
        elif escopo == "todos":
            services.apagar_para_todos(msg, request.user)
        else:
            return _erro("Escolha apagar para mim ou para todos.")
    except services.ChatErro as exc:
        return _erro(str(exc), 403 if "não pode" in str(exc) else 400)
    msg.refresh_from_db()
    return JsonResponse({"ok": True, "estado": _estado_mensagem(msg), "mensagem": serializar_mensagem(msg, request.user)})


@chat_required
@require_POST
def api_reenviar(request: HttpRequest, pk: int) -> JsonResponse:
    msg = _mensagem_ou_404(request, pk)
    if msg.remetente_id != request.user.pk and not eh_gestor(request.user):
        return _erro("Só quem enviou pode reenviar.", 403)
    try:
        nova = services.reenviar(msg, request.user)
    except services.ChatErro as exc:
        return _erro(str(exc))
    return JsonResponse({"ok": True, "removida": msg.pk, "mensagem": serializar_mensagem(nova, request.user)})


@chat_required
@require_GET
def midia(request: HttpRequest, pk: int) -> HttpResponse:
    msg = _mensagem_ou_404(request, pk)
    if msg.revogada or not msg.tem_midia:
        raise Http404
    try:
        services.garantir_midia(msg)
    except (EvolutionErro, ProvedorErro, services.ChatErro) as exc:
        return HttpResponse(str(exc), status=502, content_type="text/plain; charset=utf-8")
    resposta = FileResponse(msg.arquivo.open("rb"), content_type=msg.mimetype or "application/octet-stream")
    inline = msg.tipo in ("imagem", "audio", "video", "figurinha")
    nome = msg.arquivo_nome or "arquivo"
    resposta["Content-Disposition"] = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{_quote(nome)}"
    resposta["X-Content-Type-Options"] = "nosniff"
    resposta["Cache-Control"] = "private, max-age=3600"
    return resposta


def _quote(nome: str) -> str:
    from urllib.parse import quote

    return quote(nome, safe="")


# ---------------------------------------------------------------------------
# Painel lateral: cliente e pedidos
# ---------------------------------------------------------------------------

def _pedidos_da_conversa(conversa: Conversa, limite: int = 15) -> list[dict]:
    from apps.orders.models import Order
    from apps.payments.models import LinkPagamento

    chave = telefone_canonico(conversa.telefone)
    filtro = Q(pk__in=[])
    if conversa.cliente_id:
        filtro |= Q(cliente_id=conversa.cliente_id)
    if len(chave) >= 10:
        filtro |= Q(client_whatsapp__contains=chave[-4:])
    pedidos = []
    for p in Order.objects.filter(filtro).order_by("-created_at").prefetch_related("attachments")[:120]:
        if not (conversa.cliente_id and p.cliente_id == conversa.cliente_id) and telefone_canonico(p.client_whatsapp) != chave:
            continue
        link = LinkPagamento.objects.filter(order=p, status=LinkPagamento.Status.ATIVO).first()
        pedidos.append({
            "id": p.pk,
            "numero": p.number,
            "etapa": p.get_stage_display(),
            "etapa_codigo": p.stage,
            "total": f"{p.total_amount:.2f}",
            "pago": f"{p.paid_amount:.2f}",
            "saldo": f"{p.remaining_amount:.2f}",
            "status_pagamento": p.get_payment_status_display(),
            "quitado": p.payment_status == Order.PaymentStatus.PAID,
            "url": reverse("production:detail", args=[p.pk]),
            "url_link": reverse("payments:link_confirmar", args=[p.pk]) + f"?conversa={conversa.pk}",
            "link_ativo": {"url": link.url, "valor": f"{link.valor:.2f}"} if link else None,
            "anexos": [
                {"id": a.pk, "nome": a.original_name}
                for a in p.attachments.all() if a.removed_at is None
            ][:6],
        })
        if len(pedidos) >= limite:
            break
    return pedidos


@chat_required
@require_GET
def api_painel(request: HttpRequest, pk: int) -> JsonResponse:
    conversa = _conversa_ou_404(request, pk)
    cliente = conversa.cliente
    return JsonResponse({
        "ok": True,
        "cliente": {"id": cliente.pk, "nome": cliente.nome, "url": reverse("payments:customer_detail", args=[cliente.pk])} if cliente else None,
        "telefone": formatar_telefone(conversa.telefone),
        "instancia": conversa.instancia.apelido,
        "pedidos": _pedidos_da_conversa(conversa),
        "etiquetas": [e.pk for e in conversa.etiquetas.all()],
    })


@chat_required
@require_POST
def api_cliente(request: HttpRequest, pk: int) -> JsonResponse:
    conversa = _conversa_ou_404(request, pk)
    try:
        cliente = services.cadastrar_cliente(conversa, nome=str(_dados(request).get("nome", "")), usuario=request.user)
    except services.ChatErro as exc:
        return _erro(str(exc))
    return JsonResponse({"ok": True, "cliente": {"id": cliente.pk, "nome": cliente.nome}})


@chat_required
@require_POST
def api_etiquetas(request: HttpRequest, pk: int) -> JsonResponse:
    conversa = _conversa_ou_404(request, pk)
    dados = _dados(request)
    ids = dados.getlist("etiquetas") if hasattr(dados, "getlist") else dados.get("etiquetas", [])
    permitidas = _etiquetas_do_usuario(request.user).filter(pk__in=[int(i) for i in ids if str(i).isdigit()])
    conversa.etiquetas.set(permitidas)
    return JsonResponse({"ok": True, "conversa": serializar_conversa(conversa)})


@chat_required
@require_POST
def api_arquivar(request: HttpRequest, pk: int) -> JsonResponse:
    conversa = _conversa_ou_404(request, pk)
    conversa.arquivada_em = None if conversa.arquivada_em else timezone.now()
    conversa.save(update_fields=["arquivada_em"])
    return JsonResponse({"ok": True, "arquivada": conversa.arquivada_em is not None})


@chat_required
@require_POST
def api_nova_conversa(request: HttpRequest) -> JsonResponse:
    dados = _dados(request)
    telefone = str(dados.get("telefone", ""))
    if not telefone_valido(telefone):
        return _erro("Informe um celular com DDD.")
    instancia_id = str(dados.get("instancia", ""))
    instancias = instancias_visiveis(request.user)
    instancia = instancias.filter(pk=int(instancia_id)).first() if instancia_id.isdigit() else instancias.filter(vendedora=request.user).first() or instancias.first()
    if not instancia:
        return _erro("Nenhum número de WhatsApp disponível para você.", 403)
    conversa = services.obter_conversa(instancia, telefone=telefone, nome=str(dados.get("nome", ""))[:150])
    return JsonResponse({"ok": True, "conversa": serializar_conversa(conversa)})


@chat_required
def abrir_pedido(request: HttpRequest, order_id: int) -> HttpResponse:
    """Botão "Abrir conversa" do card e do detalhe do pedido."""
    from django.contrib import messages

    from apps.orders.models import Order

    from apps.orders.services import require_order_access

    order = get_object_or_404(Order, pk=order_id)
    require_order_access(request.user, order)
    conversa = services.conversa_do_pedido(order, request.user)
    if not conversa or not pode_ver_conversa(request.user, conversa):
        messages.error(request, "Não há número de WhatsApp seu conectado para falar com este cliente, ou o telefone do pedido é inválido.")
        return redirect("production:detail", pk=order.pk)
    return redirect(f"{reverse('whatsapp:chat')}?c={conversa.pk}")


@login_required
@require_GET
def api_resumo(request: HttpRequest) -> JsonResponse:
    if not pode_usar_chat(request.user):
        return JsonResponse({"nao_lidas": 0})
    total = conversas_visiveis(request.user).filter(arquivada_em__isnull=True).aggregate(t=Sum("nao_lidas"))["t"] or 0
    return JsonResponse({"nao_lidas": total})


# ---------------------------------------------------------------------------
# Instâncias (administradores)
# ---------------------------------------------------------------------------

def _admin_required(view):
    @login_required
    @wraps(view)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        if not pode_gerenciar_instancias(request.user):
            if request.headers.get("x-requested-with") == "fetch":
                return _erro("Acesso restrito a administradores.", 403)
            return render(request, "errors/403.html", status=403)
        return view(request, *args, **kwargs)

    return _wrapped


@_admin_required
def instancias(request: HttpRequest) -> HttpResponse:
    from django.contrib import messages

    from apps.accounts.models import User

    if request.method == "POST" and request.POST.get("acao") == "importar_umbler":
        return _importar_canais_umbler(request)
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip().lower()
        apelido = (request.POST.get("apelido") or "").strip()[:80]
        vendedora_id = request.POST.get("vendedora") or ""
        provedor = request.POST.get("provedor") or Instancia.Provedor.UMBLER
        telefone_canal = (request.POST.get("telefone_canal") or "").strip()
        if provedor not in Instancia.Provedor.values:
            messages.error(request, "Provedor inválido.")
        elif not nome_instancia_valido(nome):
            messages.error(request, "Identificador inválido: use letras minúsculas, números, hífen ou sublinhado.")
        elif Instancia.objects.filter(nome=nome).exists():
            messages.error(request, "Já existe um número com esse identificador.")
        elif provedor == Instancia.Provedor.UMBLER and not com_ddi(telefone_canal):
            messages.error(request, "Informe o telefone do canal da Umbler (com DDD).")
        else:
            vendedora = User.objects.filter(pk=vendedora_id, is_active=True).first() if vendedora_id.isdigit() else None
            Instancia.objects.create(
                nome=nome, apelido=apelido or nome, vendedora=vendedora, provedor=provedor,
                canal_id=(request.POST.get("canal_id") or "").strip()[:40],
                telefone_canal=f"+{com_ddi(telefone_canal)}" if telefone_canal else "",
                compartilhada=request.POST.get("compartilhada") == "1",
                padrao_automaticas=request.POST.get("padrao_automaticas") == "1",
                cor=(request.POST.get("cor") or "#3BA776")[:7],
            )
            if provedor == Instancia.Provedor.UMBLER:
                messages.success(request, "Número cadastrado. A conexão do WhatsApp é feita no painel da Umbler.")
            else:
                messages.success(request, "Instância cadastrada. Agora conecte o WhatsApp pelo QR Code.")
        return redirect("whatsapp:instancias")
    contexto = {
        "page_title": "Números de WhatsApp",
        "instancias": Instancia.objects.select_related("vendedora").order_by("-ativa", "apelido"),
        "usuarios": User.objects.filter(is_active=True).order_by("name"),
        "configurado": EvolutionClient().configurado,
        "webhook_configurado": bool(getattr(settings, "EVOLUTION_WEBHOOK_SECRET", "") and getattr(settings, "EVOLUTION_WEBHOOK_BASE_URL", "")),
        "umbler_configurado": UmblerClient().configurado,
        "umbler_webhook_url": _url_webhook_umbler(request),
        "provedores": Instancia.Provedor.choices,
        "provedor_padrao": getattr(settings, "WHATSAPP_PROVEDOR", Instancia.Provedor.UMBLER),
    }
    return render(request, "whatsapp/instancias.html", contexto)


def _url_webhook_umbler(request: HttpRequest) -> str:
    """URL para colar em Configurações > Webhooks no painel da Umbler (só administradores veem)."""
    segredo = getattr(settings, "UMBLER_WEBHOOK_SECRET", "") or ""
    if not segredo:
        return ""
    base = (getattr(settings, "WHATSAPP_WEBHOOK_BASE_URL", "") or request.build_absolute_uri("/")).rstrip("/")
    return f"{base}{reverse('whatsapp:webhook_umbler', args=[segredo])}"


def _importar_canais_umbler(request: HttpRequest) -> HttpResponse:
    """Cria (ou atualiza) um número do Print para cada canal de WhatsApp da organização na Umbler."""
    from django.contrib import messages

    try:
        canais = UmblerClient().canais()
    except UmblerErro as exc:
        messages.error(request, str(exc))
        return redirect("whatsapp:instancias")
    novos = atualizados = 0
    for canal in canais:
        canal_id = str(campo(canal, "id") or "")
        telefone = com_ddi(str(campo(canal, "phoneNumber") or ""))
        if not canal_id or not telefone:
            continue  # Instagram, site e outros canais sem telefone ficam de fora
        estado = ESTADOS_CANAL.get(str(campo(canal, "state") or "").lower(), "close")
        inst = Instancia.objects.filter(provedor=Instancia.Provedor.UMBLER, canal_id=canal_id).first()
        if inst:
            inst.telefone_canal, inst.estado, inst.numero_conectado = f"+{telefone}", estado, telefone
            inst.estado_verificado_em = timezone.now()
            inst.save(update_fields=["telefone_canal", "estado", "numero_conectado", "estado_verificado_em"])
            atualizados += 1
            continue
        base = f"umbler_{telefone[-8:]}"
        nome, n = base, 1
        while Instancia.objects.filter(nome=nome).exists():
            n += 1
            nome = f"{base}_{n}"
        Instancia.objects.create(
            nome=nome, apelido=str(campo(canal, "name") or telefone)[:80], provedor=Instancia.Provedor.UMBLER,
            canal_id=canal_id, telefone_canal=f"+{telefone}", estado=estado, numero_conectado=telefone,
            estado_verificado_em=timezone.now(),
        )
        novos += 1
    messages.success(request, f"Canais da Umbler: {novos} novo(s), {atualizados} atualizado(s). Defina a vendedora de cada número.")
    return redirect("whatsapp:instancias")


@_admin_required
@require_POST
def instancia_acao(request: HttpRequest, pk: int, acao: str) -> JsonResponse:
    inst = get_object_or_404(Instancia, pk=pk)
    if acao == "vendedora":
        from apps.accounts.models import User

        valor = request.POST.get("vendedora") or ""
        inst.vendedora = User.objects.filter(pk=valor, is_active=True).first() if valor.isdigit() else None
        inst.save(update_fields=["vendedora"])
        return JsonResponse({"ok": True})
    if inst.provedor == Instancia.Provedor.UMBLER:
        return _acao_umbler(inst, acao)
    cli = EvolutionClient()
    try:
        if acao == "conectar":
            dados = cli.conectar(inst.nome)
            try:
                cli.configurar_webhook(inst.nome)
            except EvolutionErro:
                logger.warning("Webhook da instância %s não pôde ser configurado agora", inst.nome)
        elif acao == "estado":
            dados = cli.estado(inst.nome)
        elif acao == "reiniciar":
            dados = {"ok": cli.reiniciar(inst.nome).ok}
        elif acao == "desconectar":
            dados = {"ok": cli.desconectar(inst.nome).ok, "estado": "close"}
        elif acao == "webhook":
            dados = {"ok": cli.configurar_webhook(inst.nome).ok}
        elif acao == "ativar":
            inst.ativa = not inst.ativa
            inst.save(update_fields=["ativa"])
            return JsonResponse({"ok": True, "ativa": inst.ativa})
        else:
            return _erro("Ação desconhecida.")
    except EvolutionErro as exc:
        return _erro(str(exc), 502)
    estado = dados.get("estado")
    if estado is not None:
        inst.estado = estado[:12]
        if dados.get("numero"):
            inst.numero_conectado = str(dados["numero"])[:20]
        inst.estado_verificado_em = timezone.now()
        inst.save(update_fields=["estado", "numero_conectado", "estado_verificado_em"])
    return JsonResponse({"ok": True, **{k: v for k, v in dados.items() if k in {"estado", "qrcode", "numero", "codigo_pareamento", "ok"}}})


def _acao_umbler(inst: Instancia, acao: str) -> JsonResponse:
    if acao == "ativar":
        inst.ativa = not inst.ativa
        inst.save(update_fields=["ativa"])
        return JsonResponse({"ok": True, "ativa": inst.ativa})
    if acao != "estado":
        return _erro("Na Umbler, a conexão do número é feita no painel da Umbler Talk.")
    try:
        dados = ProvedorUmbler(inst).estado_canal()
    except ProvedorErro as exc:
        return _erro(str(exc), 502)
    inst.estado = dados["estado"][:12]
    inst.numero_conectado = dados["numero"][:20] or inst.numero_conectado
    inst.estado_verificado_em = timezone.now()
    inst.save(update_fields=["estado", "numero_conectado", "estado_verificado_em"])
    return JsonResponse({"ok": True, "estado": inst.estado, "numero": inst.numero_conectado})


# ---------------------------------------------------------------------------
# Webhooks (Umbler Talk e Evolution)
# ---------------------------------------------------------------------------

LIMITE_WEBHOOK_BYTES = 5 * 1024 * 1024


@csrf_exempt
@require_POST
def webhook_evolution(request: HttpRequest, token: str) -> JsonResponse:
    """Valida o segredo, aplica os eventos e responde 200 rápido (mídia é baixada depois, sob demanda)."""
    segredo = getattr(settings, "EVOLUTION_WEBHOOK_SECRET", "") or ""
    recebido = token or request.headers.get("X-Webhook-Token", "")
    if not segredo or not hmac.compare_digest(recebido.encode(), segredo.encode()):
        logger.warning("Webhook da Evolution recusado: segredo inválido (IP %s)", request.META.get("REMOTE_ADDR", "?"))
        return JsonResponse({"ok": False}, status=403)
    if len(request.body) > LIMITE_WEBHOOK_BYTES:
        return JsonResponse({"ok": False}, status=413)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "erro": "json"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "erro": "json"}, status=400)
    nome = str(payload.get("instance") or "").strip()
    instancia = Instancia.objects.filter(nome=nome, ativa=True).first()
    if not instancia:
        logger.warning("Webhook da Evolution para instância não cadastrada: %r", nome[:60])
        return JsonResponse({"ok": True, "ignorado": True})
    processados = services.processar_webhook(instancia, payload)
    return JsonResponse({"ok": True, "processados": processados})


AVISOS_PEDIDO = {
    "orcamento": ("quote_message", "Orçamento"),
    "pronto": ("ready_message", "Aviso de pronto para retirada"),
    "entregue": ("delivered_message", "Aviso de material entregue"),
}


@chat_required
@require_POST
def enviar_aviso(request: HttpRequest, order_id: int, tipo: str) -> HttpResponse:
    """Envia pelo serviço único as mensagens prontas do pedido (o texto continua o mesmo, sem emojis)."""
    from django.contrib import messages

    from apps.notifications.whatsapp import get_whatsapp_share_links
    from apps.orders.models import Order
    from apps.orders.services import require_order_access

    order = get_object_or_404(Order, pk=order_id)
    require_order_access(request.user, order)
    if tipo not in AVISOS_PEDIDO:
        raise Http404
    chave, descricao = AVISOS_PEDIDO[tipo]
    host = request.build_absolute_uri("/")[:-1]
    texto = get_whatsapp_share_links(order, host=host).get(chave, "")
    try:
        msg = services.enviar_mensagem_do_pedido(order, texto, usuario=request.user, descricao=descricao)
    except services.ChatErro as exc:
        messages.error(request, str(exc))
        return redirect("production:detail", pk=order.pk)
    if msg.status == Mensagem.Status.FALHOU:
        messages.error(request, msg.erro or "O WhatsApp não aceitou a mensagem. Use o botão verde para enviar pelo aparelho.")
    else:
        order.notified_whatsapp = True
        order.notified_whatsapp_at = timezone.now()
        order.notified_whatsapp_by = request.user
        order.save(update_fields=["notified_whatsapp", "notified_whatsapp_at", "notified_whatsapp_by", "updated_at"])
        messages.success(request, f"{descricao} enviado ao cliente pelo WhatsApp.")
    return redirect("production:detail", pk=order.pk)


@csrf_exempt
@require_POST
def webhook_umbler(request: HttpRequest, token: str) -> JsonResponse:
    """Webhook da Umbler Talk: responde em bem menos de 5 s (limite da Umbler); mídia é baixada depois, sob demanda.

    A Umbler não assina o webhook: a origem é validada pelo segredo na URL (cadastrada no painel da Umbler).
    """
    segredo = getattr(settings, "UMBLER_WEBHOOK_SECRET", "") or ""
    if not segredo or not hmac.compare_digest((token or "").encode(), segredo.encode()):
        logger.warning("Webhook da Umbler recusado: segredo inválido (IP %s)", request.META.get("REMOTE_ADDR", "?"))
        return JsonResponse({"ok": False}, status=403)
    if len(request.body) > LIMITE_WEBHOOK_BYTES:
        return JsonResponse({"ok": False}, status=413)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "erro": "json"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "erro": "json"}, status=400)
    resultado = services.processar_webhook_umbler(payload)
    return JsonResponse({"ok": True, **resultado})
