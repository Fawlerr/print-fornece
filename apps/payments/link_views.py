from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.orders.models import Order

from . import links
from .models import LinkPagamento
from .stone.services.stone import StoneConfigurationError


def _conversa(request: HttpRequest):
    """Conversa de origem (quando o link é gerado de dentro do chat), só se o usuário puder vê-la."""
    from apps.whatsapp.models import Conversa
    from apps.whatsapp.permissoes import pode_ver_conversa

    valor = request.GET.get("conversa") or request.POST.get("conversa") or ""
    if not str(valor).isdigit():
        return None
    conversa = Conversa.objects.select_related("instancia").filter(pk=int(valor)).first()
    return conversa if conversa and pode_ver_conversa(request.user, conversa) else None


@login_required
def confirmar(request: HttpRequest, order_id: int) -> HttpResponse:
    order = get_object_or_404(Order.objects.select_related("cliente", "responsible"), pk=order_id)
    if not links.pode_gerar(request.user):
        raise PermissionDenied
    conversa = _conversa(request)
    erro = ""
    calculo = None
    try:
        calculo = links.calcular(order)
    except links.LinkErro as exc:
        erro = str(exc)

    if request.method == "POST" and calculo is not None:
        try:
            valor = int(request.POST.get("valor_centavos", ""))
        except ValueError:
            valor = -1
        try:
            link, reaproveitado = links.gerar(order, request.user, valor_confirmado_centavos=valor)
        except (links.LinkErro, StoneConfigurationError) as exc:
            messages.error(request, str(exc))
            return redirect(request.get_full_path())
        if reaproveitado:
            messages.info(request, "Já existia um link ativo com este mesmo valor. Ele foi mantido.")
        else:
            messages.success(request, "Link de pagamento gerado.")
        destino = reverse("payments:link_detalhe", args=[link.pk])
        return redirect(f"{destino}?conversa={conversa.pk}" if conversa else destino)

    return render(request, "payments/link_confirmar.html", {
        "page_title": f"Link de pagamento - pedido #{order.number}",
        "order": order,
        "calculo": calculo,
        "erro": erro,
        "ativo": links.link_ativo(order),
        "historico": LinkPagamento.objects.filter(order=order).select_related("criado_por", "cancelado_por")[:20],
        "conversa": conversa,
        "formatar": links.formatar,
    })


def _link_ou_404(request: HttpRequest, pk: int) -> LinkPagamento:
    link = get_object_or_404(LinkPagamento.objects.select_related("order", "criado_por", "cancelado_por"), pk=pk)
    if not links.pode_gerar(request.user):
        raise PermissionDenied
    return link


@login_required
def detalhe(request: HttpRequest, pk: int) -> HttpResponse:
    link = _link_ou_404(request, pk)
    conversa = _conversa(request)
    return render(request, "payments/link_detalhe.html", {
        "page_title": f"Link {link.order_code}",
        "link": link,
        "order": link.order,
        "mensagem": links.mensagem_padrao(link) if link.url else "",
        "conversa": conversa,
        "pode_cancelar": links.pode_cancelar(request.user, link) and link.status == LinkPagamento.Status.ATIVO,
    })


@login_required
@require_POST
def enviar(request: HttpRequest, pk: int) -> HttpResponse:
    link = _link_ou_404(request, pk)
    conversa = _conversa(request)
    try:
        links.enviar_pelo_chat(link, request.user, request.POST.get("mensagem", ""), conversa=conversa)
    except links.LinkErro as exc:
        messages.error(request, str(exc))
        return redirect(f"{reverse('payments:link_detalhe', args=[link.pk])}?conversa={conversa.pk if conversa else ''}")
    messages.success(request, "Link enviado ao cliente pelo WhatsApp.")
    if conversa:
        return redirect(f"{reverse('whatsapp:chat')}?c={conversa.pk}")
    return redirect(reverse("payments:link_detalhe", args=[link.pk]))


@login_required
@require_POST
def cancelar(request: HttpRequest, pk: int) -> HttpResponse:
    link = _link_ou_404(request, pk)
    if not links.pode_cancelar(request.user, link):
        raise PermissionDenied
    try:
        links.cancelar(link, request.user, request.POST.get("motivo", "") or "Cancelado pela equipe")
    except (links.LinkErro, StoneConfigurationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Link cancelado. O cliente não consegue mais pagar por ele.")
    return redirect(reverse("payments:link_confirmar", args=[link.order_id]))
