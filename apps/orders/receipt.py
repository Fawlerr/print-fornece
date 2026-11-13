"""Nota/comprovante em HTML para impressão (A4).

Usa exatamente os mesmos dados congelados do comprovante PDF (``_receipt_snapshot``),
para que a nota impressa e o PDF nunca divirjam.
"""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from .pdf import PAYMENT_METHOD_LABELS, _receipt_snapshot

COMPANY = {
    "name": "Print Fornece",
    "address": "Av. Coronel Estevam, 1534 - Alecrim",
}


def build_receipt_context(order, paper_width_mm: int = 80) -> dict:
    snapshot = _receipt_snapshot(order)
    items = list(order.items.all())
    total = Decimal(str(snapshot["total"] or 0))
    paid = Decimal(str(snapshot["paid_amount"] or 0))
    remaining = max(Decimal("0.00"), total - paid)
    if snapshot.get("is_correction"):
        payment_state = "correcao"
    elif total > 0 and paid >= total:
        payment_state = "pago"
    elif paid > 0:
        payment_state = "parcial"
    else:
        payment_state = "pendente"
    return {
        "order": order,
        "company": COMPANY,
        "paper_width_mm": 58 if int(paper_width_mm or 80) == 58 else 80,
        "client_name": str(snapshot["client_name"] or "Não informado").strip(),
        "seller_name": snapshot["seller_name"],
        "paid_at": timezone.localtime(snapshot["paid_at"]),
        "items": items,
        "shirt_discount_total": sum((item.discount_total or Decimal("0.00") for item in items), Decimal("0.00")),
        "total": total,
        "paid": paid,
        "remaining": remaining,
        "payment_state": payment_state,
        "method_label": PAYMENT_METHOD_LABELS.get(str(snapshot["payment_method"]), "Não informado"),
        "is_correction": snapshot.get("is_correction"),
        "correction_reason": snapshot.get("correction_reason") or "",
    }
