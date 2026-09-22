"""Single, security-focused adapter for the official Pagar.me (Stone) V5 API.

Views must never make HTTP calls to Stone directly. The adapter uses only the
server-side secret key for authenticated calls; the public key is intentionally
reserved for the browser's direct card-tokenization request.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .normalizers import amount_to_cents, document_type, stone_phone

logger = logging.getLogger("pagamentos")


_SECRETISH_VALUE = re.compile(r"\b(?:sk|pk|acc|tok|card)_(?:test_|live_)?[A-Za-z0-9_-]+\b", re.IGNORECASE)
_EMAIL_VALUE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_LONG_NUMBER_VALUE = re.compile(r"\b\d{8,}\b")


def _safe_text(value: Any, *, limit: int = 255) -> str | None:
    """Keep a small provider diagnostic while removing likely sensitive data."""
    if not isinstance(value, (str, int, float)):
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    text = _SECRETISH_VALUE.sub("[redacted]", text)
    text = _EMAIL_VALUE.sub("[email redacted]", text)
    text = _LONG_NUMBER_VALUE.sub("[numeric value redacted]", text)
    return text[:limit]


def provider_error_summary(transaction_data: dict[str, Any]) -> dict[str, str]:
    """Extract only safe, documented diagnostic fields from a transaction."""
    gateway_response = transaction_data.get("gateway_response")
    gateway_response = gateway_response if isinstance(gateway_response, dict) else {}

    summary: dict[str, str] = {}
    for source in (gateway_response, transaction_data):
        if "code" not in summary:
            code = _safe_text(source.get("code") or source.get("error_code") or source.get("return_code"), limit=80)
            if code:
                summary["code"] = code
        if "type" not in summary:
            error_type = _safe_text(source.get("type") or source.get("error_type"), limit=80)
            if error_type:
                summary["type"] = error_type

    error_candidates: list[Any] = []
    for source in (gateway_response, transaction_data):
        for key in ("errors", "error"):
            candidate = source.get(key)
            if isinstance(candidate, list):
                error_candidates.extend(candidate)
            elif candidate is not None:
                error_candidates.append(candidate)
        for key in ("message", "error_message", "return_message", "reason", "description"):
            if source.get(key) is not None:
                error_candidates.append({"message": source.get(key)})

    for candidate in error_candidates:
        if isinstance(candidate, dict):
            if "type" not in summary:
                error_type = _safe_text(candidate.get("type") or candidate.get("error_type"), limit=80)
                if error_type:
                    summary["type"] = error_type
            message = _safe_text(
                candidate.get("message")
                or candidate.get("error_message")
                or candidate.get("reason")
                or candidate.get("description")
            )
        else:
            message = _safe_text(candidate)
        if message:
            summary["message"] = message
            break
    return summary


def _response_parts(response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return the order, charge and transaction objects without trusting shape."""
    order: dict[str, Any] = {}
    charge: dict[str, Any] = {}
    charges = response.get("charges")
    if isinstance(charges, list) and charges and isinstance(charges[0], dict):
        order = response
        charge = charges[0]
    elif isinstance(response.get("order"), dict):
        order = response["order"]
        charge = response
    elif response.get("payment_method") or response.get("last_transaction"):
        charge = response
    transaction_data = charge.get("last_transaction")
    return order, charge, transaction_data if isinstance(transaction_data, dict) else {}


def stone_response_summary(response: dict[str, Any]) -> dict[str, Any]:
    """Build an allowlisted response summary safe for logs and local storage."""
    order, charge, transaction_data = _response_parts(response)
    summary: dict[str, Any] = {
        "http_status": response.get("_stone_http_status") if isinstance(response.get("_stone_http_status"), int) else None,
        "order_id": _safe_text(order.get("id"), limit=100),
        "order_code": _safe_text(order.get("code"), limit=100),
        "order_status": _safe_text(order.get("status"), limit=80),
        "charge_id": _safe_text(charge.get("id"), limit=100),
        "charge_code": _safe_text(charge.get("code"), limit=100),
        "charge_status": _safe_text(charge.get("status"), limit=80),
        "transaction_id": _safe_text(transaction_data.get("id"), limit=100),
        "transaction_status": _safe_text(transaction_data.get("status"), limit=80),
        "transaction_type": _safe_text(transaction_data.get("transaction_type"), limit=80),
        "transaction_success": transaction_data.get("success") if isinstance(transaction_data.get("success"), bool) else None,
        "pix_qr_code_received": bool(transaction_data.get("qr_code")),
        "pix_qr_code_url_received": bool(transaction_data.get("qr_code_url")),
        "expires_at": _safe_text(transaction_data.get("expires_at"), limit=80),
    }
    # Business failures can be nested in last_transaction.gateway_response
    # even with HTTP 2xx, while validation/auth failures can be top-level HTTP
    # error bodies. Support both shapes without retaining the raw body.
    provider_error = provider_error_summary(transaction_data) or provider_error_summary(response)
    if provider_error:
        summary["provider_error"] = provider_error
    return summary


def _is_pix_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    payments = payload.get("payments")
    return isinstance(payments, list) and any(
        isinstance(payment, dict) and str(payment.get("payment_method", "")).lower() == "pix"
        for payment in payments
    )


def _is_pix_response(response: dict[str, Any]) -> bool:
    _, charge, transaction_data = _response_parts(response)
    return (
        str(charge.get("payment_method", "")).lower() == "pix"
        or str(transaction_data.get("transaction_type", "")).lower() == "pix"
    )


def _safe_pix_request_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Log request structure and validation-relevant facts, never customer values."""
    if not isinstance(payload, dict):
        return {}
    customer = payload.get("customer")
    customer = customer if isinstance(customer, dict) else {}
    phones = customer.get("phones")
    phones = phones if isinstance(phones, dict) else {}
    items = payload.get("items")
    safe_items: list[dict[str, Any]] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                safe_items.append(
                    {
                        "amount": item.get("amount") if isinstance(item.get("amount"), int) else None,
                        "quantity": item.get("quantity") if isinstance(item.get("quantity"), int) else None,
                        "description_present": bool(item.get("description")),
                    }
                )
    payments = payload.get("payments")
    safe_payments: list[dict[str, Any]] = []
    if isinstance(payments, list):
        for payment in payments:
            if not isinstance(payment, dict):
                continue
            pix = payment.get("pix")
            pix = pix if isinstance(pix, dict) else {}
            safe_payments.append(
                {
                    "payment_method": _safe_text(payment.get("payment_method"), limit=40),
                    "pix": {
                        "expires_in": pix.get("expires_in") if isinstance(pix.get("expires_in"), int) else None,
                        "expires_at_present": bool(pix.get("expires_at")),
                    },
                }
            )
    metadata = payload.get("metadata")
    return {
        "code": _safe_text(payload.get("code"), limit=100),
        "items": safe_items,
        "customer": {
            "present": bool(customer),
            "name_present": bool(customer.get("name")),
            "email_present": bool(customer.get("email")),
            "document_type": _safe_text(customer.get("document_type"), limit=40),
            "document_digits": len(re.sub(r"\D", "", str(customer.get("document") or ""))),
            "phone_kinds": sorted(str(key) for key in phones.keys()),
        },
        "payments": safe_payments,
        "metadata_keys": sorted(str(key) for key in metadata.keys()) if isinstance(metadata, dict) else [],
    }


class StoneAPIError(RuntimeError):
    """An API error with full diagnostic and telemetry information for debugging."""

    user_message = "Não foi possível concluir a comunicação com a Stone."

    def __init__(
        self,
        message: str | None = None,
        *,
        http_status: int | None = None,
        response_json: dict[str, Any] | None = None,
        request_payload: dict[str, Any] | None = None,
        endpoint: str = "",
        method: str = "",
        duracao_ms: int | None = None,
        trace_id: str = "",
    ):
        super().__init__(message or self.user_message)
        self.user_message = message or self.user_message
        self.http_status = http_status
        self.response_json = response_json or {}
        self.request_payload = request_payload or {}
        self.endpoint = endpoint
        self.method = method
        self.duracao_ms = duracao_ms
        self.trace_id = trace_id

        # Extrair detalhes ricos retornados pela API V5 do Pagar.me
        self.error_code = ""
        self.error_type = ""
        self.error_parameter = ""
        self.detailed_errors: list[dict[str, Any]] = []

        if isinstance(self.response_json, dict):
            # Formato 1: {"message": "...", "errors": [{"message": "...", "parameter_name": "...", "type": "..."}]}
            errors = self.response_json.get("errors")
            if isinstance(errors, list) and errors:
                for err in errors:
                    if isinstance(err, dict):
                        self.detailed_errors.append(err)
                first = self.detailed_errors[0]
                self.error_parameter = str(first.get("parameter_name") or first.get("field") or "")
                self.error_type = str(first.get("type") or "")
                if first.get("message") and not message:
                    self.user_message = f"Erro Pagar.me ({self.error_parameter or self.error_type}): {first.get('message')}"
            elif isinstance(errors, dict):
                self.detailed_errors.append(errors)
                self.error_parameter = str(errors.get("parameter_name") or "")
                self.error_type = str(errors.get("type") or "")

            if not self.error_type:
                self.error_type = str(self.response_json.get("type") or self.response_json.get("error_type") or "")
            if not self.error_code:
                self.error_code = str(self.response_json.get("code") or self.response_json.get("error_code") or "")
            if self.response_json.get("message") and not message:
                self.user_message = str(self.response_json.get("message"))


class StoneConfigurationError(StoneAPIError):
    user_message = "A chave secreta de teste da Stone ainda não foi configurada."


class StoneAuthenticationError(StoneAPIError):
    user_message = "Não foi possível autenticar com a Stone. Verifique sua STONE_SECRET_KEY."


class StoneValidationError(StoneAPIError):
    user_message = "A Stone recusou os dados enviados para a cobrança."


class StoneUnavailableError(StoneAPIError):
    user_message = "A Stone está temporariamente indisponível. Tente novamente mais tarde."


class StoneConflictError(StoneAPIError):
    user_message = "Esta cobrança já está em processamento na Stone. Conflito de idempotência."


class StoneInProgressError(StoneAPIError):
    user_message = "Já existe uma tentativa desta cobrança em processamento. Consulte o histórico antes de reenviar."


class StoneIdempotencyExpiredError(StoneAPIError):
    user_message = "A janela de idempotência desta tentativa expirou. Não a reenvie sem antes confirmar o resultado na Stone."



class StoneService:
    """Official Pagar.me/Stone V5 server-side operations.

    `sk_test_...` is the only accepted credential for these requests. The
    account id and public key are not substituted for it.
    """

    api_base_url: str
    secret_key: str
    timeout: int

    def __init__(self, *, api_base_url: str | None = None, secret_key: str | None = None, timeout: int | None = None):
        self.api_base_url = (api_base_url or settings.STONE_API_BASE_URL).rstrip("/")
        self.secret_key = settings.STONE_SECRET_KEY if secret_key is None else secret_key
        self.timeout = settings.STONE_TIMEOUT_SECONDS if timeout is None else timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.secret_key)

    def require_server_credentials(self) -> None:
        if settings.STONE_ENVIRONMENT != "test":
            raise StoneConfigurationError("O ambiente Stone deve ser 'test' neste projeto isolado.")
        if not self.secret_key:
            raise StoneConfigurationError("A chave secreta de teste da Stone (STONE_SECRET_KEY / sk_test_...) ainda não foi configurada.")
        if not (self.secret_key.startswith("sk_test_") or self.secret_key.startswith("sk_")):
            raise StoneConfigurationError("A chave secreta configurada não possui o formato de chave secreta V5 ('sk_...').")



    def require_card_account_type(self) -> str:
        """Require an explicit provider account model before card processing."""
        account_type = settings.STONE_ACCOUNT_TYPE
        if account_type not in {"gateway", "psp"}:
            raise StoneConfigurationError(
                "Defina STONE_ACCOUNT_TYPE como 'gateway' ou 'psp' após confirmar o tipo da conta com a Stone."
            )
        return account_type

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        self.require_server_credentials()
        token = base64.b64encode(f"{self.secret_key}:".encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "print-fornece-stone-sandbox/1.0",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = str(idempotency_key)
        return headers

    @staticmethod
    def _safe_remote_message(payload: bytes) -> str:
        """Return an intentionally generic remote error, never raw API data."""
        try:
            data = json.loads(payload.decode("utf-8")) if payload else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ""
        if not isinstance(data, dict):
            return ""
        # Error details can include submitted personal data; retain no values.
        if data.get("message"):
            return "A Stone rejeitou a requisição."
        return ""

    def _log_pix_debug(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        http_status: int | None,
        response_data: dict[str, Any] | None,
    ) -> None:
        """Emit an allowlisted test diagnostic for PIX without leaking secrets/PII."""
        response_data = response_data if isinstance(response_data, dict) else {}
        if not getattr(settings, "STONE_PIX_DEBUG", False) or not (_is_pix_payload(payload) or _is_pix_response(response_data)):
            return

        summary = stone_response_summary(response_data)
        logger.info(
            "========== STONE PIX DEBUG ==========\n"
            "Endpoint: %s %s\n"
            "Environment: %s\n"
            "Request: %s\n"
            "HTTP status: %s\n"
            "Response: %s\n"
            "Charge ID: %s\n"
            "Transaction ID: %s\n"
            "Status: %s\n"
            "Error: %s\n"
            "=====================================",
            method,
            f"{self.api_base_url}/{path.lstrip('/')}",
            settings.STONE_ENVIRONMENT,
            json.dumps(_safe_pix_request_summary(payload), ensure_ascii=False, sort_keys=True),
            http_status,
            json.dumps(summary, ensure_ascii=False, sort_keys=True),
            summary.get("charge_id"),
            summary.get("transaction_id"),
            summary.get("transaction_status") or summary.get("charge_status"),
            json.dumps(summary.get("provider_error") or {}, ensure_ascii=False, sort_keys=True),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        event_type: str = "pagar_me_request",
    ) -> dict[str, Any]:
        from time import perf_counter
        from .logger import IntegrationLogger, generate_trace_id

        actual_trace = trace_id or generate_trace_id()
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        headers = self._headers(idempotency_key=idempotency_key)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=body, headers=headers, method=method)

        # Log de início de requisição
        IntegrationLogger.record(
            trace_id=actual_trace,
            nivel="REQUEST",
            tipo_evento=f"{event_type}_iniciado",
            mensagem=f"Enviando requisição {method} para {path}",
            endpoint=url,
            metodo_http=method,
            request_headers=dict(headers),
            request_body=payload or {},
        )

        start_time = perf_counter()
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - official configured HTTPS API base.
                duracao_ms = int((perf_counter() - start_time) * 1000)
                http_status = response.status
                raw = response.read()
                res_headers = dict(response.headers.items()) if hasattr(response, "headers") else {}
        except HTTPError as exc:
            duracao_ms = int((perf_counter() - start_time) * 1000)
            raw = exc.read()
            err_headers = dict(exc.headers.items()) if hasattr(exc, "headers") else {}
            try:
                error_data = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_data = {}

            self._log_pix_debug(
                method=method,
                path=path,
                payload=payload,
                http_status=exc.code,
                response_data=error_data if isinstance(error_data, dict) else {},
            )

            # Criar exceção enriquecida com todos os detalhes da API V5
            stone_err_cls = StoneAPIError
            if exc.code in {401, 403}:
                stone_err_cls = StoneAuthenticationError
            elif exc.code == 409:
                stone_err_cls = StoneConflictError
            elif exc.code in {400, 404, 412, 422}:
                stone_err_cls = StoneValidationError
            elif exc.code >= 500:
                stone_err_cls = StoneUnavailableError

            api_error = stone_err_cls(
                http_status=exc.code,
                response_json=error_data if isinstance(error_data, dict) else {},
                request_payload=payload or {},
                endpoint=url,
                method=method,
                duracao_ms=duracao_ms,
                trace_id=actual_trace,
            )

            # Registrar log de erro na telemetria
            IntegrationLogger.record(
                trace_id=actual_trace,
                nivel="ERROR",
                tipo_evento=f"{event_type}_falhou",
                mensagem=f"Falha na API Pagar.me V5: HTTP {exc.code} - {api_error.user_message}",
                endpoint=url,
                metodo_http=method,
                http_status=exc.code,
                duracao_ms=duracao_ms,
                error_code=api_error.error_code,
                error_type=api_error.error_type,
                error_message=api_error.user_message,
                error_parameter=api_error.error_parameter,
                request_headers=dict(headers),
                request_body=payload or {},
                response_headers=err_headers,
                response_body=error_data if isinstance(error_data, dict) else {"raw": raw.decode("utf-8", errors="replace")},
            )
            raise api_error from exc

        except (URLError, TimeoutError) as exc:
            duracao_ms = int((perf_counter() - start_time) * 1000)
            IntegrationLogger.record(
                trace_id=actual_trace,
                nivel="ERROR",
                tipo_evento=f"{event_type}_rede_falhou",
                mensagem=f"Falha de rede/timeout ao comunicar com a Stone: {type(exc).__name__}",
                endpoint=url,
                metodo_http=method,
                duracao_ms=duracao_ms,
                error_message=str(exc),
                request_headers=dict(headers),
                request_body=payload or {},
            )
            raise StoneUnavailableError(
                "Falha de rede ao comunicar com a Stone.",
                endpoint=url,
                method=method,
                duracao_ms=duracao_ms,
                trace_id=actual_trace,
            ) from exc

        if not raw:
            data = {}
        else:
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                duracao_ms = int((perf_counter() - start_time) * 1000)
                IntegrationLogger.record(
                    trace_id=actual_trace,
                    nivel="ERROR",
                    tipo_evento=f"{event_type}_json_invalido",
                    mensagem="A Stone retornou uma resposta não-JSON.",
                    endpoint=url,
                    metodo_http=method,
                    http_status=http_status,
                    duracao_ms=duracao_ms,
                    response_body={"raw": raw.decode("utf-8", errors="replace")},
                )
                raise StoneAPIError(
                    "A Stone retornou uma resposta inválida.",
                    http_status=http_status,
                    duracao_ms=duracao_ms,
                    trace_id=actual_trace,
                ) from exc

        if not isinstance(data, dict):
            raise StoneAPIError("A Stone retornou um formato de resposta inesperado.")

        data["_stone_http_status"] = int(http_status)
        data["_stone_duracao_ms"] = duracao_ms
        data["_stone_trace_id"] = actual_trace

        # Extrair identificadores retornados se existirem
        order_id = str(data.get("id") if str(data.get("id", "")).startswith("or_") else data.get("order", {}).get("id") or "")
        charges = data.get("charges")
        charge_id = ""
        transaction_id = ""
        if isinstance(charges, list) and charges and isinstance(charges[0], dict):
            charge_id = str(charges[0].get("id") or "")
            last_tx = charges[0].get("last_transaction")
            if isinstance(last_tx, dict):
                transaction_id = str(last_tx.get("id") or "")
        elif str(data.get("id", "")).startswith("ch_"):
            charge_id = str(data.get("id") or "")
            last_tx = data.get("last_transaction")
            if isinstance(last_tx, dict):
                transaction_id = str(last_tx.get("id") or "")

        # Registrar log de resposta bem-sucedida
        IntegrationLogger.record(
            trace_id=actual_trace,
            nivel="RESPONSE",
            tipo_evento=f"{event_type}_sucesso",
            mensagem=f"Resposta recebida com sucesso: HTTP {http_status} em {duracao_ms}ms",
            endpoint=url,
            metodo_http=method,
            http_status=http_status,
            duracao_ms=duracao_ms,
            order_id=order_id,
            charge_id=charge_id,
            transaction_id=transaction_id,
            request_headers=dict(headers),
            request_body=payload or {},
            response_headers=res_headers,
            response_body=data,
        )

        self._log_pix_debug(
            method=method,
            path=path,
            payload=payload,
            http_status=http_status,
            response_data=data,
        )
        return data

    @staticmethod
    def _customer_payload(customer) -> dict[str, Any]:
        return {
            "name": customer.nome,
            "email": customer.email,
            "code": f"cliente-{customer.pk}",
            "document": customer.cpf_cnpj,
            "document_type": document_type(customer.cpf_cnpj),
            "type": "individual" if len(customer.cpf_cnpj) == 11 else "company",
            "phones": {"mobile_phone": stone_phone(customer.telefone)},
        }

    def create_customer(self, customer) -> dict[str, Any]:
        return self._request("POST", "/customers", payload=self._customer_payload(customer))

    def update_customer(self, customer) -> dict[str, Any]:
        if not customer.stone_customer_id:
            raise StoneValidationError("Cliente não possui identificador Stone para atualização.")
        return self._request("PUT", f"/customers/{customer.stone_customer_id}", payload=self._customer_payload(customer))

    def create_customer_card(self, *, customer, card_token: str, idempotency_key: str) -> dict[str, Any]:
        """Register a tokenized card in a PSP wallet; no PAN/CVV is received."""
        if not customer.stone_customer_id:
            raise StoneValidationError("Cliente ainda não possui identificador Stone para a wallet.")
        if self.require_card_account_type() != "psp":
            raise StoneConfigurationError("A criação de card_id por token é destinada ao fluxo PSP.")
        return self._request(
            "POST",
            f"/customers/{customer.stone_customer_id}/cards",
            payload={"token": card_token},
            idempotency_key=idempotency_key,
        )

    def create_pix_payment(
        self,
        *,
        customer,
        amount: Decimal,
        reference: str,
        order_code: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        # The Pix reference explicitly requires the full customer object with
        # name, e-mail, document and phones. It also lets Pagar.me reconcile the
        # customer through its stable `code` without exposing a card.
        payload = {
            "code": order_code,
            "items": [{"amount": amount_to_cents(amount), "description": reference[:256], "quantity": 1}],
            "customer": self._customer_payload(customer),
            "payments": [
                {
                    "payment_method": "pix",
                    "pix": {"expires_in": settings.STONE_PIX_EXPIRES_IN},
                }
            ],
            "metadata": {"local_reference": reference[:100]},
        }
        return self._request("POST", "/orders", payload=payload, idempotency_key=idempotency_key)

    def create_card_payment(
        self,
        *,
        customer,
        amount: Decimal,
        reference: str,
        order_code: str,
        idempotency_key: str,
        installments: int,
        card_token: str | None = None,
        card_id: str | None = None,
    ) -> dict[str, Any]:
        if bool(card_token) == bool(card_id):
            raise StoneValidationError("Informe exatamente um token de cartão ou card_id da wallet.")
        if not customer.stone_customer_id:
            raise StoneValidationError("Cliente ainda não possui identificador Stone para cobrança por cartão.")
        if card_token and self.require_card_account_type() != "gateway":
            raise StoneConfigurationError("card_token direto em pedido só pode ser usado para uma conta Gateway confirmada.")
        credit_card: dict[str, Any] = {"installments": installments}
        if card_token:
            credit_card["card_token"] = card_token
        else:
            credit_card["card_id"] = card_id
        payload = {
            "code": order_code,
            "items": [{"amount": amount_to_cents(amount), "description": reference[:256], "quantity": 1}],
            "customer_id": customer.stone_customer_id,
            "payments": [{"payment_method": "credit_card", "credit_card": credit_card}],
            "metadata": {"local_reference": reference[:100]},
        }
        return self._request("POST", "/orders", payload=payload, idempotency_key=idempotency_key)

    def get_payment(self, stone_payment_id: str) -> dict[str, Any]:
        if not stone_payment_id:
            raise StoneValidationError("A cobrança ainda não possui identificador Stone.")
        return self._request("GET", f"/charges/{stone_payment_id}")

    def create_generic_order(
        self,
        order_payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a full or customized V5 order payload directly to POST /orders with telemetry."""
        return self._request(
            "POST",
            "/orders",
            payload=order_payload,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            event_type="order_creation",
        )

    def test_connectivity(self, *, trace_id: str | None = None) -> dict[str, Any]:
        """Perform a safe, read-only diagnostic call to check credentials and V5 endpoint reachability."""
        self.require_server_credentials()
        # GET /orders?page=1&size=1 is a safe read-only call to verify HTTP Basic auth and network connectivity
        return self._request(
            "GET",
            "/orders?page=1&size=1",
            trace_id=trace_id,
            event_type="test_connectivity",
        )

