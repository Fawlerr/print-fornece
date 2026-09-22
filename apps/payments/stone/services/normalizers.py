"""Input normalization and safe conversion helpers for payments."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError


def only_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_document(value: str | None) -> str:
    return only_digits(value)


def _all_same(value: str) -> bool:
    return bool(value) and value == value[0] * len(value)


def is_valid_cpf(value: str) -> bool:
    if len(value) != 11 or _all_same(value):
        return False
    for position in (9, 10):
        total = sum(int(value[index]) * (position + 1 - index) for index in range(position))
        digit = (total * 10) % 11
        if digit == 10:
            digit = 0
        if digit != int(value[position]):
            return False
    return True


def is_valid_cnpj(value: str) -> bool:
    if len(value) != 14 or _all_same(value):
        return False
    weights = ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    for position, factors in ((12, weights[0]), (13, weights[1])):
        total = sum(int(value[index]) * factors[index] for index in range(position))
        remainder = total % 11
        digit = 0 if remainder < 2 else 11 - remainder
        if digit != int(value[position]):
            return False
    return True


def validate_document(value: str | None) -> str:
    document = normalize_document(value)
    if len(document) == 11 and is_valid_cpf(document):
        return document
    if len(document) == 14 and is_valid_cnpj(document):
        return document
    raise ValidationError("Informe um CPF ou CNPJ válido.")


def document_type(value: str) -> str:
    if len(value) == 11:
        return "CPF"
    if len(value) == 14:
        return "CNPJ"
    raise ValidationError("Documento inválido para a Stone.")


def normalize_phone(value: str | None) -> str:
    phone = only_digits(value)
    # Keep the local Brazilian number in the database; tolerate a supplied +55.
    if len(phone) in {12, 13} and phone.startswith("55"):
        phone = phone[2:]
    if len(phone) not in {10, 11}:
        raise ValidationError("Informe um telefone brasileiro com DDD.")
    return phone


def stone_phone(value: str) -> dict[str, str]:
    phone = normalize_phone(value)
    return {"country_code": "55", "area_code": phone[:2], "number": phone[2:]}


def parse_brl(value: str | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        amount = value
    else:
        raw = str(value).strip()
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        try:
            amount = Decimal(raw)
        except Exception as exc:
            raise ValidationError("Informe um valor monetário válido.") from exc
    try:
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValidationError("Informe um valor monetário válido.") from exc
    if amount <= 0:
        raise ValidationError("O valor da cobrança deve ser maior que zero.")
    if amount > Decimal("9999999999.99"):
        raise ValidationError("O valor informado excede o limite permitido.")
    return amount


def amount_to_cents(value: Decimal) -> int:
    amount = parse_brl(value)
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mask_document(value: str) -> str:
    if len(value) == 11:
        return f"***.***.{value[6:9]}-**"
    if len(value) == 14:
        return f"**.***.***/{value[8:12]}-**"
    return "***"


def format_phone(value: str) -> str:
    phone = only_digits(value)
    if len(phone) == 11:
        return f"({phone[:2]}) {phone[2:7]}-{phone[7:]}"
    if len(phone) == 10:
        return f"({phone[:2]}) {phone[2:6]}-{phone[6:]}"
    return value
