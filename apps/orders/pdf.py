"""Thermal-style internal sales receipt generation."""
from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


RECEIPT_WIDTH = 80 * mm
RECEIPT_MARGIN = 4 * mm
PAYMENT_METHOD_LABELS = {
    "pix": "PIX",
    "cartao": "Cartão",
    "dinheiro": "Dinheiro",
    "transferencia": "Transferência",
    "outro": "Outro",
}


def _money(value: Decimal | None) -> str:
    amount = Decimal(value or 0)
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _number(value: Decimal | int | None, decimal_places: int = 2) -> str:
    amount = Decimal(value or 0)
    formatted = f"{amount:,.{decimal_places}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return formatted


def _receipt_page_height(order) -> float:
    """Keep ordinary receipts compact, while allowing tables to split when needed."""
    items = list(order.items.all()) if hasattr(order, "items") else []
    estimated_lines = 0
    if items:
        for item in items:
            estimated_lines += 3 + max(0, len(item.material_name) // 30)
    else:
        estimated_lines = 4 + max(0, len(order.description or "") // 36)
    # A normal receipt should finish shortly after the footer rather than
    # leaving an A4-like blank tail. Long receipts can still split over
    # multiple 80 mm-wide pages.
    return min(297, max(104, 74 + (estimated_lines * 6.2))) * mm


def _receipt_snapshot(order) -> dict[str, object]:
    seller = order.responsible or order.created_by or order.payment_confirmed_by
    seller_name = ""
    if seller is not None:
        seller_name = seller.name or seller.email
    return {
        "client_name": order.receipt_client_name or order.client_name,
        "seller_name": order.receipt_seller_name or seller_name or "Não informado",
        "total": order.receipt_total_amount if order.receipt_total_amount is not None else order.total_amount,
        "paid_amount": order.receipt_paid_amount if order.receipt_paid_amount is not None else order.paid_amount,
        "payment_method": order.receipt_payment_method or order.payment_method or "",
        # Older paid orders did not have a confirmation timestamp.  Their
        # existing creation time is the closest truthful value available.
        "paid_at": order.payment_confirmed_at or order.created_at,
    }


def _logo_flowable(styles):
    for candidate in ("logo.png", "logo.jpg"):
        logo_path = Path(settings.BASE_DIR) / "images" / candidate
        if logo_path.is_file():
            return Image(str(logo_path), width=34 * mm, height=14.5 * mm)
    return Paragraph("<b>PRINT FORNECE</b>", styles["brand"])


def _item_flowable(item, styles):
    title = Paragraph(escape(item.material_name), styles["item_name"])
    calculation = escape(item.calculation_detail or "")
    if not calculation:
        calculation = f"{_number(item.billing_quantity)} ({escape(item.billing_unit)}) X {_money(item.unit_price)}"
    artwork = ""
    if item.art_width_cm is not None and item.art_height_cm is not None and item.art_quantity is not None:
        artwork = f"<br/><font size=6.8>Arte {_number(item.art_width_cm)} x {_number(item.art_height_cm)} cm · qtd. {item.art_quantity}</font>"
    details = Paragraph(
        f"{calculation}{artwork}",
        styles["item_details"],
    )
    row = Table(
        [[details, Paragraph(f"<b>{_money(item.line_total)}</b>", styles["item_total"])]],
        colWidths=[50 * mm, 22 * mm],
        hAlign="LEFT",
    )
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return KeepTogether([
        title,
        Spacer(1, 1.2 * mm),
        row,
        Spacer(1, 2.2 * mm),
        HRFlowable(width="100%", thickness=0.35, color=colors.HexColor("#B9B9B9"), spaceBefore=0, spaceAfter=2.2 * mm),
    ])


def _legacy_item_flowable(order, total, styles):
    description = escape((order.description or "Pedido sem descrição").strip()).replace("\n", "<br/>")
    row = Table(
        [[Paragraph("<b>Pedido</b><br/>" + description, styles["item_details"]), Paragraph(f"<b>{_money(total)}</b>", styles["item_total"])]],
        colWidths=[50 * mm, 22 * mm],
        hAlign="LEFT",
    )
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return KeepTogether([
        row,
        Spacer(1, 2.2 * mm),
        HRFlowable(width="100%", thickness=0.35, color=colors.HexColor("#B9B9B9"), spaceBefore=0, spaceAfter=2.2 * mm),
    ])


def generate_order_receipt_pdf(order) -> bytes:
    """Build a narrow, printable receipt using saved sales snapshots only."""
    snapshot = _receipt_snapshot(order)
    paid_at = timezone.localtime(snapshot["paid_at"])
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(RECEIPT_WIDTH, _receipt_page_height(order)),
        leftMargin=RECEIPT_MARGIN,
        rightMargin=RECEIPT_MARGIN,
        topMargin=4 * mm,
        bottomMargin=4 * mm,
        title=f"Comprovante {order.number}",
        author="Print Fornece",
    )

    stylesheet = getSampleStyleSheet()
    styles = {
        "brand": ParagraphStyle("ReceiptBrand", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=11, leading=13),
        "meta": ParagraphStyle("ReceiptMeta", parent=stylesheet["Normal"], fontName="Helvetica", fontSize=7.2, leading=9, alignment=2),
        "body": ParagraphStyle("ReceiptBody", parent=stylesheet["Normal"], fontName="Helvetica", fontSize=8, leading=10.2),
        "label": ParagraphStyle("ReceiptLabel", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=colors.HexColor("#333333")),
        "item_name": ParagraphStyle("ReceiptItemName", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=8.3, leading=10),
        "item_details": ParagraphStyle("ReceiptItemDetails", parent=stylesheet["Normal"], fontName="Helvetica", fontSize=7.25, leading=9),
        "item_total": ParagraphStyle("ReceiptItemTotal", parent=stylesheet["Normal"], fontName="Helvetica", fontSize=7.65, leading=9, alignment=2),
        "total_label": ParagraphStyle("ReceiptTotalLabel", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=10, leading=12),
        "total_value": ParagraphStyle("ReceiptTotalValue", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=10, leading=12, alignment=2),
        "footer": ParagraphStyle("ReceiptFooter", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, alignment=1),
        "footer_small": ParagraphStyle("ReceiptFooterSmall", parent=stylesheet["Normal"], fontName="Helvetica", fontSize=6.8, leading=8.5, alignment=1),
    }

    header = Table(
        [[_logo_flowable(styles), Paragraph(
            f"<b>DATA</b><br/>{paid_at:%d/%m/%Y}<br/><b>HORA</b><br/>{paid_at:%H:%M:%S}",
            styles["meta"],
        )]],
        colWidths=[45 * mm, 27 * mm],
        hAlign="LEFT",
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    story = [
        header,
        Spacer(1, 2.5 * mm),
        HRFlowable(width="100%", thickness=0.8, color=colors.black, spaceBefore=0, spaceAfter=2.5 * mm),
        Paragraph(f"<b>Cliente:</b> {escape(str(snapshot['client_name']))}", styles["body"]),
        Paragraph(f"<b>Vendedor:</b> {escape(str(snapshot['seller_name']))}", styles["body"]),
        Paragraph(f"<b>Venda (n: {escape(order.number)})</b>", styles["body"]),
        Spacer(1, 2.6 * mm),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#666666"), spaceBefore=0, spaceAfter=2.3 * mm),
    ]

    item_header = Table(
        [[Paragraph("DESCRIÇÃO / QUANTIDADE X UNITÁRIO", styles["label"]), Paragraph("TOTAL", styles["label"])]],
        colWidths=[50 * mm, 22 * mm],
        hAlign="LEFT",
    )
    item_header.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8 * mm),
    ]))
    story.append(item_header)

    items = list(order.items.all()) if hasattr(order, "items") else []
    if items:
        story.extend(_item_flowable(item, styles) for item in items)
    else:
        story.append(_legacy_item_flowable(order, snapshot["total"], styles))

    total_table = Table(
        [
            [Paragraph("Total a Pagar", styles["total_label"]), Paragraph(_money(snapshot["total"]), styles["total_value"])],
            [Paragraph(PAYMENT_METHOD_LABELS.get(str(snapshot["payment_method"]), "Não informado"), styles["body"]), Paragraph(_money(snapshot["paid_amount"]), styles["item_total"])],
        ],
        colWidths=[48 * mm, 24 * mm],
        hAlign="LEFT",
    )
    total_table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#777777")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.extend([
        total_table,
        Spacer(1, 4 * mm),
        Paragraph("CONFIRA SEU MATERIAL ANTES DE CORTAR", styles["footer"]),
        Paragraph("(não trocamos material cortado)", styles["footer_small"]),
    ])

    doc.build(story)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data
