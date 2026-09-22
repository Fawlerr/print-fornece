"""Telemetry, structured logging and tracing for Stone / Pagar.me V5."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone

logger = logging.getLogger("pagamentos")

_SECRET_PATTERN = re.compile(
    r"\b(?:sk|pk|acc|tok|card)_(?:test_|live_)?[A-Za-z0-9_-]+\b",
    re.IGNORECASE,
)
_BASIC_AUTH_PATTERN = re.compile(r"Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE)
_CARD_NUMBER_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_CVV_PATTERN = re.compile(r"\b\d{3,4}\b")


def mask_secret(value: str | None, *, keep_end: int = 4) -> str:
    """Mask credentials like sk_test_... into sk_test_••••••••1234."""
    if not value or not isinstance(value, str):
        return ""
    clean = value.strip()
    if len(clean) <= keep_end + 4:
        return "••••" + clean[-keep_end:] if len(clean) >= keep_end else "••••"
    prefix = clean[:8] if clean.startswith(("sk_test_", "sk_live_", "pk_test_", "pk_live_")) else clean[:3]
    return f"{prefix}••••••••{clean[-keep_end:]}"


def sanitize_data(data: Any, *, in_card_context: bool = False) -> Any:
    """Recursively sanitize dicts and lists to guarantee no PAN, CVV or raw keys leak."""
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            lower_key = str(key).lower()
            if any(term in lower_key for term in ["secret", "authorization", "api_key", "password", "token_key"]):
                sanitized[key] = "[PROTECTED CREDENTIAL]"
            elif lower_key in ["cvv", "card_cvv", "csc"]:
                sanitized[key] = "***"
            elif lower_key in ["number", "card_number", "numero_cartao", "pan"]:
                raw = re.sub(r"\D", "", str(value or ""))
                sanitized[key] = f"•••• •••• •••• {raw[-4:]}" if len(raw) >= 4 else "••••"
            elif lower_key in ["qr_code", "qr_code_url"] and isinstance(value, str) and len(value) > 200:
                sanitized[key] = value[:120] + "... [TRUNCATED QR DATA]"
            else:
                sanitized[key] = sanitize_data(value, in_card_context=("card" in lower_key))
        return sanitized
    if isinstance(data, list):
        return [sanitize_data(item, in_card_context=in_card_context) for item in data]
    if isinstance(data, str):
        masked = _BASIC_AUTH_PATTERN.sub("Basic [REDACTED AUTH TOKEN]", data)
        return masked
    if isinstance(data, Decimal):
        return float(data)
    return data


def generate_trace_id() -> str:
    """Generate human-readable trace identifier: trace_YYYYMMDD_HHMMSS_XXXX."""
    now = timezone.now()
    unique_suffix = uuid.uuid4().hex[:6].upper()
    return f"trace_{now:%Y%m%d_%H%M%S}_{unique_suffix}"


class IntegrationLogger:
    """Helper to record structured events to StoneLogIntegracao model and python logger."""

    @staticmethod
    def record(
        *,
        trace_id: str | None = None,
        nivel: str = "INFO",
        tipo_evento: str,
        mensagem: str,
        endpoint: str = "",
        metodo_http: str = "",
        http_status: int | None = None,
        duracao_ms: int | None = None,
        order_id: str = "",
        charge_id: str = "",
        transaction_id: str = "",
        error_code: str = "",
        error_type: str = "",
        error_message: str = "",
        error_parameter: str = "",
        request_headers: dict | None = None,
        request_body: dict | None = None,
        response_headers: dict | None = None,
        response_body: dict | None = None,
        detalhes_extras: dict | None = None,
    ):
        from apps.payments.models import StoneLogIntegracao

        actual_trace = trace_id or generate_trace_id()
        safe_req_headers = sanitize_data(request_headers or {})
        safe_req_body = sanitize_data(request_body or {})
        safe_res_headers = sanitize_data(response_headers or {})
        safe_res_body = sanitize_data(response_body or {})
        safe_extras = sanitize_data(detalhes_extras or {})

        try:
            log_entry = StoneLogIntegracao.objects.create(
                trace_id=actual_trace,
                nivel=nivel,
                tipo_evento=tipo_evento,
                mensagem=mensagem,
                endpoint=endpoint,
                metodo_http=metodo_http,
                http_status=http_status,
                duracao_ms=duracao_ms,
                order_id=order_id,
                charge_id=charge_id,
                transaction_id=transaction_id,
                error_code=error_code,
                error_type=error_type,
                error_message=error_message,
                error_parameter=error_parameter,
                request_headers=safe_req_headers,
                request_body=safe_req_body,
                response_headers=safe_res_headers,
                response_body=safe_res_body,
                detalhes_extras=safe_extras,
            )
            # Log to console
            log_msg = f"[{actual_trace}] [{nivel}] {tipo_evento} - {mensagem}"
            if http_status:
                log_msg += f" (HTTP {http_status}, {duracao_ms or 0}ms)"
            if nivel in ["ERROR", "WARNING"]:
                logger.warning(log_msg)
            else:
                logger.info(log_msg)
            return log_entry
        except Exception as exc:
            logger.error("Failed to persist StoneLogIntegracao: %s", exc)
            return None
