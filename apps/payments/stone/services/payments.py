"""Domain service for safely persisting Stone/Pagar.me payment state."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.payments.models import (
    Cliente,
    StoneEventoPagamento as EventoPagamento,
    StoneMetodoPagamento as MetodoPagamento,
    StonePagamento as Pagamento,
)

from .stone import (
    StoneAPIError,
    StoneIdempotencyExpiredError,
    StoneInProgressError,
    StoneService,
    StoneValidationError,
    provider_error_summary,
    stone_response_summary,
)

logger = logging.getLogger("pagamentos")


REMOTE_STATUS_MAP = {
    "paid": Pagamento.Status.PAID,
    "captured": Pagamento.Status.PAID,
    "partial_capture": Pagamento.Status.PAID,
    "pending": Pagamento.Status.PENDING,
    "processing": Pagamento.Status.PENDING,
    "waiting_payment": Pagamento.Status.PENDING,
    "authorized_pending_capture": Pagamento.Status.PENDING,
    "waiting_capture": Pagamento.Status.PENDING,
    "pending_refund": Pagamento.Status.PENDING,
    "waiting_cancellation": Pagamento.Status.PENDING,
    "failed": Pagamento.Status.FAILED,
    "not_authorized": Pagamento.Status.FAILED,
    "with_error": Pagamento.Status.FAILED,
    "chargedback": Pagamento.Status.FAILED,
    "canceled": Pagamento.Status.CANCELED,
    "cancelled": Pagamento.Status.CANCELED,
    "voided": Pagamento.Status.CANCELED,
    "partial_void": Pagamento.Status.CANCELED,
    "refunded": Pagamento.Status.REFUNDED,
    "partial_refunded": Pagamento.Status.REFUNDED,
}


def record_event(*, tipo: str, descricao: str, pagamento: Pagamento | None = None, cliente: Cliente | None = None, dados: dict | None = None) -> EventoPagamento:
    """Persist a small, non-sensitive audit record."""
    return EventoPagamento.objects.create(
        pagamento=pagamento,
        cliente=cliente or (pagamento.cliente if pagamento else None),
        tipo=tipo,
        descricao=descricao,
        dados=dados or {},
    )


def sync_customer(
    customer: Cliente,
    *,
    service: StoneService | None = None,
    update_existing: bool = False,
) -> Cliente:
    """Create a remote customer, or explicitly synchronize a local edit."""
    service = service or StoneService()
    if customer.stone_customer_id:
        if not update_existing:
            return customer
        response = service.update_customer(customer)
        remote_id = str(response.get("id") or customer.stone_customer_id)
        if remote_id != customer.stone_customer_id:
            raise StoneAPIError("A Stone retornou um identificador inesperado ao atualizar o cliente.")
        with transaction.atomic():
            locked = Cliente.objects.select_for_update().get(pk=customer.pk)
            record_event(
                tipo="cliente_atualizado_stone",
                descricao="Cliente atualizado na Stone.",
                cliente=locked,
                dados={"stone_customer_id": remote_id},
            )
            return locked

    response = service.create_customer(customer)
    remote_id = str(response.get("id") or "")
    if not remote_id:
        raise StoneAPIError("A Stone não retornou o identificador do cliente.")
    with transaction.atomic():
        locked = Cliente.objects.select_for_update().get(pk=customer.pk)
        conflicting_customer = (
            Cliente.objects.select_for_update().filter(stone_customer_id=remote_id).exclude(pk=locked.pk).first()
        )
        if conflicting_customer:
            raise StoneValidationError("O identificador Stone retornado já está vinculado a outro cliente local.")
        if locked.stone_customer_id and locked.stone_customer_id != remote_id:
            raise StoneAPIError("O cliente foi sincronizado concorrentemente com outro identificador Stone.")
        if not locked.stone_customer_id:
            locked.stone_customer_id = remote_id
            locked.save(update_fields=["stone_customer_id", "updated_at"])
            record_event(
                tipo="cliente_sincronizado",
                descricao="Cliente sincronizado com a Stone.",
                cliente=locked,
                dados={"stone_customer_id": remote_id},
            )
        return locked


def _pick_charge(response: dict[str, Any]) -> dict[str, Any]:
    charges = response.get("charges")
    if isinstance(charges, list) and charges and isinstance(charges[0], dict):
        return charges[0]
    # GET /charges/{id} returns the charge itself.
    if response.get("id") and (response.get("payment_method") or response.get("last_transaction")):
        return response
    raise StoneAPIError("A Stone não retornou os dados da cobrança criada.")


def _pick_transaction(charge: dict[str, Any]) -> dict[str, Any]:
    transaction_data = charge.get("last_transaction")
    return transaction_data if isinstance(transaction_data, dict) else {}


def _status_from_response(charge: dict[str, Any], transaction_data: dict[str, Any]) -> str:
    remote_status = str(transaction_data.get("status") or charge.get("status") or "pending").lower()
    return REMOTE_STATUS_MAP.get(remote_status, Pagamento.Status.PENDING)


def _parse_remote_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    return parse_datetime(value)


def _safe_response_summary(response: dict[str, Any], charge: dict[str, Any], transaction_data: dict[str, Any]) -> dict[str, Any]:
    """Store technical identifiers/statuses only, never card or customer data."""
    return stone_response_summary(response)


def sync_saved_card_data(customer: Cliente, card: dict[str, Any]) -> None:
    """Persist only provider wallet metadata after a successful card response."""
    remote_id = str(card.get("id") or "")
    if not remote_id:
        return
    existing = MetodoPagamento.objects.filter(stone_payment_method_id=remote_id).exclude(cliente=customer).first()
    if existing:
        raise StoneValidationError("O card_id retornado pela Stone já está vinculado a outro cliente local.")
    last_four = str(card.get("last_four_digits") or card.get("last_four") or "")[-4:]
    MetodoPagamento.objects.update_or_create(
        stone_payment_method_id=remote_id,
        defaults={
            "cliente": customer,
            "tipo": MetodoPagamento.Tipo.CARTAO,
            "bandeira": str(card.get("brand") or "")[:30],
            "ultimos_4": last_four,
            "validade_mes": card.get("exp_month") if isinstance(card.get("exp_month"), int) else None,
            "validade_ano": card.get("exp_year") if isinstance(card.get("exp_year"), int) else None,
            "ativo": True,
        },
    )


def _sync_saved_card(customer: Cliente | None, transaction_data: dict[str, Any]) -> None:
    if not customer:
        return
    card = transaction_data.get("card")
    if isinstance(card, dict):
        sync_saved_card_data(customer, card)


def _pix_transaction_is_ready(payment: Pagamento, transaction_data: dict[str, Any]) -> bool:
    """A PIX is usable only after Stone returns both a transaction and QR data."""
    return bool(transaction_data.get("id") and (transaction_data.get("qr_code") or payment.pix_qr_code))


def _pix_event_data(
    *,
    payment: Pagamento,
    status: str,
    previous_status: str,
    transaction_data: dict[str, Any],
    provider_error: dict[str, str],
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status_anterior": previous_status,
        "status_atual": status,
        "stone_order_id": payment.stone_order_id or None,
        "stone_charge_id": payment.stone_payment_id or None,
        "stone_transaction_id": payment.stone_transaction_id or None,
        "pix_qr_code_recebido": bool(transaction_data.get("qr_code")),
    }
    if provider_error:
        data["provider_error"] = provider_error
    return data


def _record_pix_events(
    *,
    payment: Pagamento,
    status: str,
    previous_status: str,
    transaction_data: dict[str, Any],
    provider_error: dict[str, str],
    event_type: str,
) -> None:
    """Audit the distinct order, PIX transaction and QR-code milestones."""
    details = _pix_event_data(
        payment=payment,
        status=status,
        previous_status=previous_status,
        transaction_data=transaction_data,
        provider_error=provider_error,
    )
    if payment.stone_payment_id and not payment.eventos.filter(tipo="cobranca_criada_stone").exists():
        record_event(
            tipo="cobranca_criada_stone",
            descricao="Cobrança criada na Stone.",
            pagamento=payment,
            dados=details,
        )

    if status == Pagamento.Status.FAILED:
        if not payment.eventos.filter(tipo="pix_falhou").exists() or previous_status != status:
            record_event(
                tipo="pix_falhou",
                descricao="Falha ao gerar a transação PIX na Stone.",
                pagamento=payment,
                dados=details,
            )
        if payment.eventos.filter(tipo="pix_gerado").exists() and not payment.eventos.filter(
            tipo="auditoria_pix_corrigida"
        ).exists():
            record_event(
                tipo="auditoria_pix_corrigida",
                descricao="Correção de auditoria: a Stone confirmou falha na transação PIX; nenhum QR Code foi gerado.",
                pagamento=payment,
                dados=details,
            )
        return

    if _pix_transaction_is_ready(payment, transaction_data):
        if event_type == "pix_criacao" and not payment.eventos.filter(tipo="pix_gerado").exists():
            record_event(
                tipo="pix_gerado",
                descricao="Transação PIX e QR Code gerados pela Stone.",
                pagamento=payment,
                dados=details,
            )
        elif previous_status != status:
            record_event(
                tipo="status_atualizado_stone",
                descricao=f"Status PIX atualizado de {previous_status} para {status} pela Stone.",
                pagamento=payment,
                dados=details,
            )
        elif event_type == "status_consultado":
            record_event(
                tipo="status_consultado",
                descricao="Status PIX consultado na Stone sem alteração.",
                pagamento=payment,
                dados=details,
            )
        return

    if event_type == "pix_criacao" or previous_status != status or not payment.eventos.filter(
        tipo="pix_aguardando_dados"
    ).exists():
        record_event(
            tipo="pix_aguardando_dados",
            descricao="Cobrança PIX criada, mas a Stone ainda não retornou transação e QR Code utilizáveis.",
            pagamento=payment,
            dados=details,
        )


def apply_stone_response(payment_id: int, response: dict[str, Any], *, event_type: str = "stone_atualizado") -> Pagamento:
    """Atomically copy the safe, provider-authoritative response into a payment."""
    charge = _pick_charge(response)
    transaction_data = _pick_transaction(charge)
    status = _status_from_response(charge, transaction_data)
    paid_at = _parse_remote_datetime(charge.get("paid_at") or transaction_data.get("paid_at"))
    response_summary = _safe_response_summary(response, charge, transaction_data)
    provider_error = provider_error_summary(transaction_data)

    with transaction.atomic():
        payment = Pagamento.objects.select_for_update().select_related("cliente").get(pk=payment_id)
        previous_status = payment.status
        if response_summary.get("order_id"):
            payment.stone_order_id = str(response_summary["order_id"])
        payment.stone_payment_id = str(charge.get("id") or payment.stone_payment_id or "")
        payment.stone_transaction_id = str(transaction_data.get("id") or payment.stone_transaction_id or "")
        payment.status = status
        payment.response_data = response_summary
        if status == Pagamento.Status.FAILED:
            payment.last_error_message = provider_error.get(
                "message", "A Stone retornou status de falha para esta transação."
            )
        else:
            payment.last_error_message = ""
        payment.submission_started_at = None
        if payment.is_pix:
            payment.pix_qr_code = str(transaction_data.get("qr_code") or payment.pix_qr_code or "")
            payment.pix_qr_code_url = str(transaction_data.get("qr_code_url") or payment.pix_qr_code_url or "")
        if status == Pagamento.Status.PAID and not payment.paid_at:
            payment.paid_at = paid_at or timezone.now()
        payment.save()
        _sync_saved_card(payment.cliente, transaction_data)
        if payment.is_pix:
            _record_pix_events(
                payment=payment,
                status=status,
                previous_status=previous_status,
                transaction_data=transaction_data,
                provider_error=provider_error,
                event_type=event_type,
            )
            return payment
        details = {"status_anterior": previous_status, "status_atual": status}
        if event_type == "pix_gerado":
            description = "PIX gerado pela Stone."
        elif previous_status != status:
            description = f"Status atualizado de {previous_status} para {status} pela Stone."
        else:
            description = "Status consultado na Stone sem alteração."
        record_event(tipo=event_type, descricao=description, pagamento=payment, dados=details)
        return payment


def _record_stone_error(payment_id: int, error: StoneAPIError) -> None:
    """Retain a generic error; no remote body, card token or personal data."""
    with transaction.atomic():
        payment = Pagamento.objects.select_for_update().get(pk=payment_id)
        payment.last_error_message = error.user_message[:255]
        error_details = {
            "tipo_erro": type(error).__name__,
            "http_status": getattr(error, "http_status", None),
            "error_code": getattr(error, "error_code", ""),
            "error_type": getattr(error, "error_type", ""),
            "error_parameter": getattr(error, "error_parameter", ""),
            "trace_id": getattr(error, "trace_id", ""),
            "detailed_errors": getattr(error, "detailed_errors", []),
            "response_json": getattr(error, "response_json", {}),
        }
        if not payment.response_data:
            payment.response_data = {}
        payment.response_data["last_error"] = error_details

        if isinstance(error, StoneValidationError) and not payment.stone_payment_id:
            payment.status = Pagamento.Status.FAILED
            payment.submission_started_at = None
        payment.save(update_fields=["status", "last_error_message", "response_data", "submission_started_at", "updated_at"])
        record_event(
            tipo="erro_stone",
            descricao=error.user_message,
            pagamento=payment,
            dados=error_details,
        )


def create_payment(
    *,
    customer: Cliente,
    amount,
    reference: str,
    method: str,
    installments: int,
    idempotency_key,
    card_token: str | None = None,
    saved_method: MetodoPagamento | None = None,
    service: StoneService | None = None,
) -> Pagamento:
    """Create a local payment once and submit it to Stone with that same key."""
    service = service or StoneService()
    service.require_server_credentials()
    card_account_type = ""
    if method == Pagamento.Metodo.CARTAO:
        if bool(card_token) == bool(saved_method):
            raise StoneValidationError("Informe exatamente um token de cartão ou um método salvo.")
        if saved_method and (saved_method.cliente_id != customer.pk or not saved_method.ativo):
            raise StoneValidationError("O método de pagamento salvo não pertence a este cliente ou está inativo.")
        card_account_type = service.require_card_account_type()

    now = timezone.now()
    idempotency_expires_at = now + timedelta(seconds=settings.STONE_IDEMPOTENCY_TTL_SECONDS)
    with transaction.atomic():
        payment, created = Pagamento.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "cliente": customer,
                "cliente_nome": customer.nome,
                "cliente_documento": customer.cpf_cnpj or "",
                "cliente_email": customer.email or "",
                "cliente_telefone": customer.telefone or "",
                "valor": amount,
                "metodo": method,
                "parcelas": installments,
                "referencia": reference,
                "attempted_at": now,
            },
        )
        payment = Pagamento.objects.select_for_update().get(pk=payment.pk)
        if not created:
            if payment.cliente_id != customer.pk or payment.valor != amount or payment.metodo != method:
                raise StoneValidationError("A chave de idempotência já pertence a outra cobrança.")
            if payment.stone_payment_id:
                return payment
            if payment.status == Pagamento.Status.FAILED:
                raise StoneValidationError("Esta tentativa já foi rejeitada. Gere uma nova cobrança após corrigir os dados.")
            if payment.idempotency_expires_at and payment.idempotency_expires_at <= now:
                record_event(
                    tipo="idempotencia_expirada",
                    descricao="A janela de idempotência expirou; tentativa bloqueada para evitar cobrança duplicada.",
                    pagamento=payment,
                )
                raise StoneIdempotencyExpiredError()
            if payment.submission_started_at:
                record_event(
                    tipo="tentativa_em_processamento",
                    descricao="Novo envio bloqueado enquanto a tentativa original ainda está em processamento.",
                    pagamento=payment,
                )
                raise StoneInProgressError()
            record_event(tipo="tentativa_reprocessada", descricao="Cobrança pendente reenviada com a mesma chave de idempotência.", pagamento=payment)
        else:
            record_event(tipo="pagamento_criado", descricao="Cobrança criada localmente e aguardando envio à Stone.", pagamento=payment)
        payment.attempted_at = now
        payment.submission_started_at = now
        payment.idempotency_expires_at = idempotency_expires_at
        payment.save(update_fields=["attempted_at", "submission_started_at", "idempotency_expires_at", "updated_at"])

    try:
        customer = sync_customer(customer, service=service)
        order_code = f"PFST-{payment.idempotency_key.hex}"[:52]
        if method == Pagamento.Metodo.PIX:
            response = service.create_pix_payment(
                customer=customer,
                amount=amount,
                reference=reference,
                order_code=order_code,
                idempotency_key=str(payment.idempotency_key),
            )
            return apply_stone_response(payment.pk, response, event_type="pix_criacao")
        if method == Pagamento.Metodo.CARTAO:
            card_id = saved_method.stone_payment_method_id if saved_method else None
            if card_token and card_account_type == "psp":
                wallet_card = service.create_customer_card(
                    customer=customer,
                    card_token=card_token,
                    idempotency_key=str(payment.idempotency_key),
                )
                card_id = str(wallet_card.get("id") or "")
                if not card_id:
                    raise StoneAPIError("A Stone não retornou card_id ao registrar o cartão na wallet.")
                sync_saved_card_data(customer, wallet_card)
            response = service.create_card_payment(
                customer=customer,
                amount=amount,
                reference=reference,
                order_code=order_code,
                idempotency_key=str(payment.idempotency_key),
                installments=installments,
                card_token=card_token if card_account_type == "gateway" else None,
                card_id=card_id,
            )
            return apply_stone_response(payment.pk, response, event_type="pagamento_cartao_criado")
        raise StoneValidationError("Método de pagamento não suportado.")
    except StoneAPIError as error:
        _record_stone_error(payment.pk, error)
        raise


def refresh_payment(payment: Pagamento, *, service: StoneService | None = None) -> Pagamento:
    service = service or StoneService()
    service.require_server_credentials()
    response = service.get_payment(payment.stone_payment_id)
    return apply_stone_response(payment.pk, response, event_type="status_consultado")
