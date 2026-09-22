"""Views para o módulo Stone / Pagar.me V5 (Ambiente de Testes / Sandbox)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, time
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.payments.models import (
    Cliente,
    StoneEventoPagamento,
    StoneLogIntegracao,
    StoneMetodoPagamento as MetodoPagamento,
    StonePagamento as Pagamento,
)
from .forms import StoneClienteForm as ClienteForm, StoneCobrancaForm as CobrancaForm
from .services.normalizers import only_digits
from .services.payments import create_payment, record_event, refresh_payment, sync_customer
from .services.stone import StoneAPIError, StoneConfigurationError, StoneService

logger = logging.getLogger("pagamentos")

SENSITIVE_CARD_POST_FIELDS = {
    "card_number",
    "numero_cartao",
    "card_cvv",
    "cvv",
    "card_holder",
    "card_holder_name",
    "card_expiry",
    "card_expiration",
}


from functools import wraps
from django.core.exceptions import PermissionDenied


def dev_or_admin_required(view_func):
    """Restringe o acesso exclusivamente a Desenvolvedores e Administradores."""

    @wraps(view_func)
    @login_required
    def _wrapped_view(request: HttpRequest, *args, **kwargs):
        if not (getattr(request.user, "is_dev", False) or getattr(request.user, "is_administrator", False)):
            raise PermissionDenied("Acesso restrito a desenvolvedores e administradores.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def _base_context() -> dict:
    from .services.logger import mask_secret

    total_logs = StoneLogIntegracao.objects.count()
    error_logs = StoneLogIntegracao.objects.filter(nivel="ERROR").count()
    last_log = StoneLogIntegracao.objects.first()

    return {
        "stone_environment": getattr(settings, "STONE_ENVIRONMENT", "TEST").upper(),
        "stone_is_sandbox": getattr(settings, "STONE_ENVIRONMENT", "test").lower() == "test",
        "stone_public_key": getattr(settings, "STONE_PUBLIC_KEY", ""),
        "stone_public_key_masked": mask_secret(getattr(settings, "STONE_PUBLIC_KEY", "")),
        "stone_server_configured": bool(getattr(settings, "STONE_SECRET_KEY", "")),
        "stone_secret_key_masked": mask_secret(getattr(settings, "STONE_SECRET_KEY", "")),
        "stone_account_id_masked": mask_secret(getattr(settings, "STONE_ACCOUNT_ID", "")),
        "stone_account_type": getattr(settings, "STONE_ACCOUNT_TYPE", ""),
        "stone_api_base_url": getattr(settings, "STONE_API_BASE_URL", "https://api.pagar.me/core/v5"),
        "stone_pix_expires_in": getattr(settings, "STONE_PIX_EXPIRES_IN", 86400),
        "stone_idempotency_ttl": getattr(settings, "STONE_IDEMPOTENCY_TTL_SECONDS", 300),
        "stone_timeout_seconds": getattr(settings, "STONE_TIMEOUT_SECONDS", 15),
        "total_logs": total_logs,
        "error_logs": error_logs,
        "last_log": last_log,
    }



def _customer_search(query: str):
    normalized = only_digits(query)
    criteria = Q(nome__icontains=query) | Q(email__icontains=query)
    if normalized:
        criteria |= Q(cpf_cnpj__icontains=normalized) | Q(telefone__icontains=normalized)
    return Cliente.objects.filter(criteria)


def _selected_customer(raw_id: str | None) -> Cliente | None:
    if not raw_id:
        return None
    try:
        return Cliente.objects.get(pk=int(raw_id))
    except (Cliente.DoesNotExist, TypeError, ValueError):
        return None


@dev_or_admin_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, time.min))
    end = timezone.make_aware(datetime.combine(today, time.max))
    today_payments = Pagamento.objects.filter(created_at__range=(start, end))
    paid_today = Pagamento.objects.filter(status=Pagamento.Status.PAID, paid_at__range=(start, end))
    context = {
        **_base_context(),
        "total_clientes": Cliente.objects.count(),
        "cobrancas_hoje": today_payments.count(),
        "valor_recebido_hoje": paid_today.aggregate(total=Sum("valor"))["total"] or 0,
        "pix_pendentes": Pagamento.objects.filter(metodo=Pagamento.Metodo.PIX, status=Pagamento.Status.PENDING).count(),
        "pagamentos_aprovados": Pagamento.objects.filter(status=Pagamento.Status.PAID).count(),
        "pagamentos_recusados": Pagamento.objects.filter(status=Pagamento.Status.FAILED).count(),
        "ultimos_pagamentos": Pagamento.objects.select_related("cliente")[:8],
    }
    return render(request, "payments/stone/dashboard.html", context)


@dev_or_admin_required
def cobranca(request: HttpRequest) -> HttpResponse:
    def _charge_context(*, form: CobrancaForm, selected_customer: Cliente | None, query: str = "") -> dict:
        found = _customer_search(query)[:10] if query else Cliente.objects.none()
        return {
            **_base_context(),
            "form": form,
            "selected_cliente": selected_customer,
            "clientes_encontrados": found,
            "query": query,
            "saved_methods": selected_customer.stone_metodos_pagamento.filter(ativo=True) if selected_customer else MetodoPagamento.objects.none(),
        }

    if request.method == "POST":
        if any(request.POST.get(name) for name in SENSITIVE_CARD_POST_FIELDS):
            messages.error(request, "Dados brutos do cartão não podem chegar ao servidor. Tokenize o cartão diretamente na Stone.")
            selected = _selected_customer(request.POST.get("cliente_id"))
            form = CobrancaForm(initial={"cliente_id": selected.pk if selected else "", "idempotency_key": uuid.uuid4()})
            return render(request, "payments/stone/cobranca.html", _charge_context(form=form, selected_customer=selected))

        form = CobrancaForm(request.POST)
        if form.is_valid():
            selected = form.cliente
            saved_method = None
            if form.cleaned_data.get("saved_method_id"):
                saved_method = get_object_or_404(
                    MetodoPagamento,
                    pk=form.cleaned_data["saved_method_id"],
                    cliente=selected,
                    ativo=True,
                )
            try:
                payment = create_payment(
                    customer=selected,
                    amount=form.cleaned_data["valor"],
                    reference=form.cleaned_data["referencia"],
                    method=form.cleaned_data["metodo"],
                    installments=form.cleaned_data["parcelas"],
                    idempotency_key=form.cleaned_data["idempotency_key"],
                    card_token=form.cleaned_data.get("card_token") or None,
                    saved_method=saved_method,
                )
            except StoneAPIError as error:
                existing_payment = Pagamento.objects.filter(idempotency_key=form.cleaned_data["idempotency_key"]).first()
                if existing_payment:
                    messages.error(request, f"{error.user_message} Consulte o histórico desta tentativa antes de criar outra cobrança.")
                    return redirect("payments:stone_pagamento_detalhe", pk=existing_payment.pk)
                messages.error(request, error.user_message)
            else:
                if payment.status == Pagamento.Status.FAILED:
                    messages.error(
                        request,
                        "A Stone registrou falha na transação. Consulte os detalhes técnicos antes de criar outra cobrança.",
                    )
                elif payment.metodo == Pagamento.Metodo.PIX and not payment.pix_qr_code:
                    messages.warning(
                        request,
                        "A cobrança foi criada, mas a Stone ainda não retornou um QR Code PIX utilizável. Consulte os detalhes.",
                    )
                else:
                    messages.success(request, "Cobrança enviada para a Stone Sandbox. Consulte o status na tela de detalhes.")
                return redirect("payments:stone_pagamento_detalhe", pk=payment.pk)
        selected = _selected_customer(request.POST.get("cliente_id"))
        return render(request, "payments/stone/cobranca.html", _charge_context(form=form, selected_customer=selected))

    query = request.GET.get("q", "").strip()
    selected = _selected_customer(request.GET.get("cliente"))
    if not selected and query:
        matches = _customer_search(query)
        if matches.count() == 1:
            selected = matches.first()
    initial = {"idempotency_key": uuid.uuid4()}
    if selected:
        initial["cliente_id"] = selected.pk
    form = CobrancaForm(initial=initial, cliente=selected)
    return render(request, "payments/stone/cobranca.html", _charge_context(form=form, selected_customer=selected, query=query))


@dev_or_admin_required
@require_GET
def pagamentos(request: HttpRequest) -> HttpResponse:
    queryset = Pagamento.objects.select_related("cliente")
    metodo = request.GET.get("metodo", "").strip()
    status = request.GET.get("status", "").strip()
    data_inicio = request.GET.get("data_inicio", "").strip()
    data_fim = request.GET.get("data_fim", "").strip()
    busca = request.GET.get("q", "").strip()

    if metodo in Pagamento.Metodo.values:
        queryset = queryset.filter(metodo=metodo)
    if status in Pagamento.Status.values:
        queryset = queryset.filter(status=status)
    if data_inicio:
        parsed = parse_date(data_inicio)
        if parsed:
            start = timezone.make_aware(datetime.combine(parsed, time.min))
            queryset = queryset.filter(created_at__gte=start)
    if data_fim:
        parsed = parse_date(data_fim)
        if parsed:
            end = timezone.make_aware(datetime.combine(parsed, time.max))
            queryset = queryset.filter(created_at__lte=end)
    if busca:
        digits = only_digits(busca)
        criteria = (
            Q(referencia__icontains=busca)
            | Q(cliente__nome__icontains=busca)
            | Q(cliente__email__icontains=busca)
            | Q(stone_order_id__icontains=busca)
            | Q(stone_payment_id__icontains=busca)
            | Q(stone_transaction_id__icontains=busca)
        )
        if digits:
            criteria |= Q(cliente__cpf_cnpj__icontains=digits) | Q(cliente__telefone__icontains=digits)
        try:
            criteria |= Q(idempotency_key=uuid.UUID(busca))
        except ValueError:
            pass
        queryset = queryset.filter(criteria)

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    context = {
        **_base_context(),
        "page_obj": page_obj,
        "filtro_metodo": metodo,
        "filtro_status": status,
        "filtro_data_inicio": data_inicio,
        "filtro_data_fim": data_fim,
        "filtro_busca": busca,
        "metodos": Pagamento.Metodo.choices,
        "status_list": Pagamento.Status.choices,
    }
    return render(request, "payments/stone/pagamentos.html", context)


@dev_or_admin_required
@require_GET
def pagamento_detalhe(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Pagamento.objects.select_related("cliente"), pk=pk)
    context = {
        **_base_context(),
        "pagamento": payment,
        "eventos": payment.eventos.order_by("-created_at"),
        "raw_response": payment.response_data or {},
    }
    return render(request, "payments/stone/pagamento_detalhe.html", context)


@dev_or_admin_required
@require_POST
def atualizar_pagamento(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Pagamento, pk=pk)
    if not payment.stone_payment_id:
        messages.error(request, "Esta cobrança não possui identificador Stone para consulta.")
        return redirect("payments:stone_pagamento_detalhe", pk=payment.pk)
    try:
        updated = refresh_payment(payment)
    except StoneAPIError as error:
        messages.error(request, error.user_message)
    else:
        messages.success(request, f"Status atualizado na Stone: {updated.get_status_display()}.")
    return redirect("payments:stone_pagamento_detalhe", pk=payment.pk)


@dev_or_admin_required
@require_GET
def pix_qr(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Pagamento, pk=pk)
    if not payment.pix_qr_code:
        raise Http404("QR Code não disponível para esta cobrança.")
    try:
        import qrcode
        image = qrcode.make(payment.pix_qr_code)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return HttpResponse(buffer.getvalue(), content_type="image/png")
    except Exception as exc:
        logger.error("Erro ao gerar imagem QR Code: %s", exc)
        raise Http404("Falha ao renderizar imagem QR Code.") from exc


@dev_or_admin_required
def criar_pedido(request: HttpRequest) -> HttpResponse:
    """Interface técnica de criação interativa de POST /orders."""
    clientes_recentes = Cliente.objects.all().order_by("-created_at")[:10]
    return render(request, "payments/stone/criar_pedido.html", {**_base_context(), "clientes_recentes": clientes_recentes})


@dev_or_admin_required
def testes_integracao(request: HttpRequest) -> HttpResponse:
    """Painel de testes automatizados da integração Stone."""
    return render(request, "payments/stone/testes_integracao.html", _base_context())


@dev_or_admin_required
def configuracao(request: HttpRequest) -> HttpResponse:
    """Painel de diagnósticos das credenciais Sandbox."""
    return render(request, "payments/stone/configuracao.html", _base_context())


@dev_or_admin_required
@require_GET
def api_logs(request: HttpRequest) -> JsonResponse:
    nivel = request.GET.get("nivel", "").strip().upper()
    busca = request.GET.get("busca", "").strip()
    limite = min(int(request.GET.get("limite", 100)), 300)

    qs = StoneLogIntegracao.objects.all()
    if nivel in dict(StoneLogIntegracao.Nivel.choices):
        qs = qs.filter(nivel=nivel)

    if busca:
        qs = qs.filter(
            Q(mensagem__icontains=busca)
            | Q(order_id__icontains=busca)
            | Q(charge_id__icontains=busca)
            | Q(transaction_id__icontains=busca)
            | Q(trace_id__icontains=busca)
            | Q(error_code__icontains=busca)
            | Q(error_message__icontains=busca)
            | Q(endpoint__icontains=busca)
        )

    logs_data = []
    for log in qs[:limite]:
        logs_data.append({
            "id": log.pk,
            "trace_id": log.trace_id,
            "timestamp": log.timestamp.strftime("%H:%M:%S"),
            "data_completa": log.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
            "nivel": log.nivel,
            "tipo_evento": log.tipo_evento,
            "mensagem": log.mensagem,
            "endpoint": log.endpoint,
            "metodo_http": log.metodo_http,
            "http_status": log.http_status,
            "duracao_ms": log.duracao_ms,
            "order_id": log.order_id,
            "charge_id": log.charge_id,
            "transaction_id": log.transaction_id,
            "error_code": log.error_code,
            "error_type": log.error_type,
            "error_message": log.error_message,
            "error_parameter": log.error_parameter,
            "request_headers": log.request_headers,
            "request_body": log.request_body,
            "response_headers": log.response_headers,
            "response_body": log.response_body,
            "detalhes_extras": log.detalhes_extras,
        })

    return JsonResponse({"logs": logs_data, "total": qs.count()})


@dev_or_admin_required
@csrf_exempt
@require_POST
def api_limpar_logs(request: HttpRequest) -> JsonResponse:
    from .services.logger import IntegrationLogger

    total_deletados, _ = StoneLogIntegracao.objects.all().delete()
    IntegrationLogger.record(
        nivel="INFO",
        tipo_evento="logs_limpos",
        mensagem=f"Logs de integração limpos com sucesso. {total_deletados} registros removidos.",
    )
    return JsonResponse({"status": "ok", "total_deletados": total_deletados})


@dev_or_admin_required
@require_GET
def api_exportar_logs(request: HttpRequest) -> HttpResponse:
    formato = request.GET.get("format", "json").lower()
    logs = StoneLogIntegracao.objects.all()[:500]

    if formato == "txt":
        linhas = []
        for l in logs:
            linhas.append(
                f"[{l.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] [{l.nivel}] {l.tipo_evento}\n"
                f"Mensagem: {l.mensagem}\n"
                f"Trace ID: {l.trace_id} | Status: {l.http_status or 'N/A'} | Duração: {l.duracao_ms or 0}ms\n"
                f"Order ID: {l.order_id or 'N/A'} | Charge ID: {l.charge_id or 'N/A'}\n"
                f"Endpoint: {l.metodo_http} {l.endpoint}\n"
                f"{'-'*60}\n"
            )
        response = HttpResponse("\n".join(linhas), content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="stone_logs.txt"'
        return response

    dados = []
    for l in logs:
        dados.append({
            "trace_id": l.trace_id,
            "timestamp": l.timestamp.isoformat(),
            "nivel": l.nivel,
            "tipo_evento": l.tipo_evento,
            "mensagem": l.mensagem,
            "endpoint": l.endpoint,
            "metodo_http": l.metodo_http,
            "http_status": l.http_status,
            "duracao_ms": l.duracao_ms,
            "order_id": l.order_id,
            "charge_id": l.charge_id,
            "transaction_id": l.transaction_id,
            "error_code": l.error_code,
            "error_type": l.error_type,
            "error_message": l.error_message,
            "error_parameter": l.error_parameter,
            "request_headers": l.request_headers,
            "request_body": l.request_body,
            "response_headers": l.response_headers,
            "response_body": l.response_body,
        })
    response = HttpResponse(json.dumps(dados, indent=2, ensure_ascii=False), content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="stone_logs.json"'
    return response


@dev_or_admin_required
@csrf_exempt
@require_POST
def api_testar_pedido(request: HttpRequest) -> JsonResponse:
    from .services.logger import generate_trace_id, IntegrationLogger
    from .services.stone import StoneService, StoneAPIError

    trace_id = generate_trace_id()
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return JsonResponse({"sucesso": False, "mensagem": "JSON da requisição inválido."}, status=400)

    order_payload = data.get("payload")
    if not order_payload or not isinstance(order_payload, dict):
        return JsonResponse({"sucesso": False, "mensagem": "O campo 'payload' com a estrutura do pedido é obrigatório."}, status=400)

    idempotency_key = str(data.get("idempotency_key") or uuid.uuid4())

    IntegrationLogger.record(
        trace_id=trace_id,
        nivel="INFO",
        tipo_evento="teste_pedido_iniciado",
        mensagem="Iniciando teste de criação de pedido pela ferramenta de diagnóstico Stone.",
        request_body=order_payload,
    )

    service = StoneService()
    try:
        service.require_server_credentials()
        response = service.create_generic_order(
            order_payload=order_payload,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )
    except StoneAPIError as exc:
        order_id = ""
        charge_id = ""
        if isinstance(exc.response_json, dict):
            order_id = str(exc.response_json.get("id") or "")
            charges = exc.response_json.get("charges")
            if isinstance(charges, list) and charges and isinstance(charges[0], dict):
                charge_id = str(charges[0].get("id") or "")

        return JsonResponse({
            "sucesso": False,
            "trace_id": trace_id,
            "http_status": exc.http_status or 500,
            "duracao_ms": exc.duracao_ms,
            "erro": {
                "tipo": exc.error_type or type(exc).__name__,
                "codigo": exc.error_code,
                "parametro": exc.error_parameter,
                "mensagem": exc.user_message,
                "detalhes": exc.detailed_errors,
            },
            "response_body": exc.response_json,
            "request_payload": exc.request_payload,
        }, status=exc.http_status if exc.http_status and 400 <= exc.http_status <= 599 else 400)
    except Exception as exc:
        IntegrationLogger.record(
            trace_id=trace_id,
            nivel="ERROR",
            tipo_evento="erro_inesperado_backend",
            mensagem=f"Erro interno não tratado no backend: {type(exc).__name__} - {exc}",
            error_message=str(exc),
        )
        return JsonResponse({
            "sucesso": False,
            "trace_id": trace_id,
            "http_status": 500,
            "erro": {
                "tipo": "UnhandledBackendError",
                "mensagem": f"Erro interno: {exc}",
            },
        }, status=500)

    order_id = str(response.get("id") or "")
    charge_id = ""
    transaction_id = ""
    charges = response.get("charges")
    pix_qr_code = ""
    pix_qr_url = ""
    if isinstance(charges, list) and charges and isinstance(charges[0], dict):
        charge_id = str(charges[0].get("id") or "")
        last_tx = charges[0].get("last_transaction")
        if isinstance(last_tx, dict):
            transaction_id = str(last_tx.get("id") or "")
            pix_qr_code = str(last_tx.get("qr_code") or "")
            pix_qr_url = str(last_tx.get("qr_code_url") or "")

    return JsonResponse({
        "sucesso": True,
        "trace_id": trace_id,
        "http_status": response.get("_stone_http_status", 200),
        "duracao_ms": response.get("_stone_duracao_ms", 0),
        "order_id": order_id,
        "charge_id": charge_id,
        "transaction_id": transaction_id,
        "status_pedido": response.get("status"),
        "pix_qr_code": pix_qr_code,
        "pix_qr_url": pix_qr_url,
        "response_body": response,
        "request_payload": order_payload,
    })


@dev_or_admin_required
@csrf_exempt
@require_POST
def api_executar_suite_testes(request: HttpRequest) -> JsonResponse:
    """Executa a suíte de testes de sanidade da integração contra o Pagar.me V5."""
    import time
    from .services.logger import generate_trace_id
    from .services.stone import StoneService, StoneAPIError

    suite_trace = generate_trace_id()
    service = StoneService()
    testes_resultados = []

    # Teste 1: Backend acessível
    testes_resultados.append({
        "id": "backend_online",
        "nome": "Backend Django acessível",
        "status": "PASS",
        "detalhes": "O servidor local Django está respondendo adequadamente.",
        "tempo_ms": 1,
    })

    # Teste 2: Ambiente identificado como Sandbox
    is_sandbox = getattr(settings, "STONE_ENVIRONMENT", "test").lower() == "test"
    testes_resultados.append({
        "id": "ambiente_sandbox",
        "nome": "Ambiente identificado como Sandbox",
        "status": "PASS" if is_sandbox else "FAIL",
        "detalhes": f"STONE_ENVIRONMENT configurado como '{getattr(settings, 'STONE_ENVIRONMENT', 'test')}'. Trava de segurança ativa.",
        "tempo_ms": 1,
    })

    # Teste 3: Credencial Stone Secreta Configurada
    has_secret = bool(getattr(settings, "STONE_SECRET_KEY", ""))
    testes_resultados.append({
        "id": "credencial_secreta",
        "nome": "STONE_SECRET_KEY presente",
        "status": "PASS" if has_secret else "FAIL",
        "detalhes": "Chave secreta configurada no settings." if has_secret else "STONE_SECRET_KEY ausente.",
        "tempo_ms": 1,
    })

    # Teste 4: Chave pública presente
    has_public = bool(getattr(settings, "STONE_PUBLIC_KEY", ""))
    testes_resultados.append({
        "id": "credencial_publica",
        "nome": "STONE_PUBLIC_KEY configurada para tokenização",
        "status": "PASS" if has_public else "WARNING",
        "detalhes": "Chave pública configurada para o navegador." if has_public else "Chave pública ausente.",
        "tempo_ms": 1,
    })

    # Teste 5: Endpoint Pagar.me V5 Acessível e Autenticação
    if not has_secret:
        testes_resultados.append({
            "id": "autenticacao_api",
            "nome": "Autenticação e Conexão Pagar.me V5",
            "status": "SKIPPED",
            "detalhes": "Pulado: STONE_SECRET_KEY não está configurada.",
            "tempo_ms": 0,
        })
    else:
        t0 = time.perf_counter()
        try:
            res = service.test_connectivity(trace_id=suite_trace)
            duracao = int((time.perf_counter() - t0) * 1000)
            testes_resultados.append({
                "id": "autenticacao_api",
                "nome": "Autenticação e Conexão Pagar.me V5 (GET /orders)",
                "status": "PASS",
                "detalhes": f"Comunicação com a API V5 autenticada com sucesso em {duracao}ms.",
                "tempo_ms": duracao,
                "http_status": res.get("_stone_http_status", 200),
            })
        except StoneAPIError as exc:
            duracao = int((time.perf_counter() - t0) * 1000)
            testes_resultados.append({
                "id": "autenticacao_api",
                "nome": "Autenticação e Conexão Pagar.me V5 (GET /orders)",
                "status": "FAIL",
                "detalhes": f"Falha na comunicação: HTTP {exc.http_status} - {exc.user_message}",
                "tempo_ms": duracao,
                "http_status": exc.http_status,
                "erro": exc.response_json,
            })
        except Exception as exc:
            duracao = int((time.perf_counter() - t0) * 1000)
            testes_resultados.append({
                "id": "autenticacao_api",
                "nome": "Autenticação e Conexão Pagar.me V5",
                "status": "FAIL",
                "detalhes": f"Erro inesperado: {exc}",
                "tempo_ms": duracao,
            })

    # Teste 6: Tratamento de Erro 400/422 Documentado (Simulação com payload inválido)
    if has_secret:
        t0 = time.perf_counter()
        try:
            service.create_generic_order(
                order_payload={"code": "TEST-ERROR-VALIDATION"},
                idempotency_key=str(uuid.uuid4()),
                trace_id=suite_trace,
            )
            duracao = int((time.perf_counter() - t0) * 1000)
            testes_resultados.append({
                "id": "validacao_erros_api",
                "nome": "Tratamento de Erros da API V5 (400 invalid_parameter)",
                "status": "FAIL",
                "detalhes": "A API aceitou um payload propositalmente inválido.",
                "tempo_ms": duracao,
            })
        except StoneAPIError as exc:
            duracao = int((time.perf_counter() - t0) * 1000)
            if exc.http_status in {400, 422}:
                testes_resultados.append({
                    "id": "validacao_erros_api",
                    "nome": "Tratamento de Erros da API V5 (400 invalid_parameter)",
                    "status": "PASS",
                    "detalhes": f"API retornou erro 400/422 esperado com detalhes: {exc.user_message}",
                    "tempo_ms": duracao,
                    "http_status": exc.http_status,
                })
            else:
                testes_resultados.append({
                    "id": "validacao_erros_api",
                    "nome": "Tratamento de Erros da API V5 (400 invalid_parameter)",
                    "status": "FAIL",
                    "detalhes": f"API retornou status inesperado: HTTP {exc.http_status} - {exc.user_message}",
                    "tempo_ms": duracao,
                    "http_status": exc.http_status,
                })
    else:
        testes_resultados.append({
            "id": "validacao_erros_api",
            "nome": "Tratamento de Erros da API V5",
            "status": "SKIPPED",
            "detalhes": "Pulado: sem credenciais configuradas.",
            "tempo_ms": 0,
        })

    return JsonResponse({
        "trace_id": suite_trace,
        "testes": testes_resultados,
        "total_testes": len(testes_resultados),
        "passou": all(t["status"] in ["PASS", "WARNING"] for t in testes_resultados),
    })


@dev_or_admin_required
@require_GET
def api_configuracao(request: HttpRequest) -> JsonResponse:
    return JsonResponse(_base_context())


@csrf_exempt
def webhook_stone(request: HttpRequest) -> JsonResponse:
    """Endpoint reservado de webhook Stone V5."""
    return JsonResponse({"error": "Webhook Stone em ambiente de homologação."}, status=503)
