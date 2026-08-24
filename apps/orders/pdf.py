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
    "na_retirada": "Pagamento na Retirada",
    "saldo_credito": "Saldo do Plano / Crédito",
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
        "is_correction": getattr(order, "is_correction", False),
        "correction_reason": getattr(order, "correction_reason", ""),
        # Older paid orders did not have a confirmation timestamp.  Their
        # existing creation time is the closest truthful value available.
        "paid_at": order.payment_confirmed_at or order.created_at,
    }


def _logo_flowable(styles):
    for candidate in ("logo_receipt.png", "logo_bw.png", "logo_black.png", "logo.png", "logo.jpg"):
        logo_path = Path(settings.BASE_DIR) / "images" / candidate
        if logo_path.is_file():
            return Image(str(logo_path), width=34 * mm, height=14.5 * mm)
    return Paragraph("<b>PRINT FORNECE</b>", styles["brand"])


def _item_flowable(item, styles):
    title = Paragraph(f"<b>{escape(item.material_name)}</b>", styles["item_name"])
    calculation = escape(item.calculation_detail or "")
    if not calculation:
        calculation = f"<b>{_number(item.billing_quantity)} ({escape(item.billing_unit)})</b> X {_money(item.unit_price)}"
    artwork = ""
    if item.art_width_cm is not None and item.art_height_cm is not None and item.art_quantity is not None:
        artwork = f"<br/><font size=7.8><b>Arte {_number(item.art_width_cm)} x {_number(item.art_height_cm)} cm · qtd. {item.art_quantity}</b></font>"
    elif item.product_color or item.product_size:
        color_txt = escape(item.product_color) if item.product_color else ""
        size_txt = f"Tam: {escape(item.product_size)}" if item.product_size else ""
        attr_txt = " · ".join(filter(bool, [color_txt, size_txt]))
        if attr_txt:
            artwork = f"<br/><font size=7.8><b>{attr_txt}</b></font>"
    details = Paragraph(
        f"{calculation}{artwork}",
        styles["item_details"],
    )
    row = Table(
        [[details, Paragraph(f"<b>{_money(item.line_total)}</b>", styles["item_total"])]],
        colWidths=[48 * mm, 24 * mm],
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
        HRFlowable(width="100%", thickness=0.6, color=colors.black, spaceBefore=0, spaceAfter=2.2 * mm),
    ])


def _legacy_item_flowable(order, total, styles):
    description = escape((order.description or "Pedido sem descrição").strip()).replace("\n", "<br/>")
    row = Table(
        [[Paragraph("<b>Pedido</b><br/>" + description, styles["item_details"]), Paragraph(f"<b>{_money(total)}</b>", styles["item_total"])]],
        colWidths=[48 * mm, 24 * mm],
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
        HRFlowable(width="100%", thickness=0.6, color=colors.black, spaceBefore=0, spaceAfter=2.2 * mm),
    ])


def generate_order_receipt_pdf(order) -> bytes:
    """Build a narrow, printable receipt using saved sales snapshots only."""
    snapshot = _receipt_snapshot(order)
    paid_at = timezone.localtime(snapshot["paid_at"])
    buffer = io.BytesIO()

    top_margin = 3 * mm
    bottom_margin = 3 * mm
    usable_width = RECEIPT_WIDTH - (2 * RECEIPT_MARGIN)

    stylesheet = getSampleStyleSheet()
    styles = {
        "brand": ParagraphStyle("ReceiptBrand", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=colors.black),
        "meta": ParagraphStyle("ReceiptMeta", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=7.8, leading=9.5, alignment=2, textColor=colors.black),
        "body": ParagraphStyle("ReceiptBody", parent=stylesheet["Normal"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.black),
        "label": ParagraphStyle("ReceiptLabel", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=7.8, leading=9.5, textColor=colors.black),
        "item_name": ParagraphStyle("ReceiptItemName", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=8.8, leading=11, textColor=colors.black),
        "item_details": ParagraphStyle("ReceiptItemDetails", parent=stylesheet["Normal"], fontName="Helvetica", fontSize=8.0, leading=10.5, textColor=colors.black),
        "item_total": ParagraphStyle("ReceiptItemTotal", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=10.5, alignment=2, textColor=colors.black),
        "total_label": ParagraphStyle("ReceiptTotalLabel", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.black),
        "total_value": ParagraphStyle("ReceiptTotalValue", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, alignment=2, textColor=colors.black),
        "footer": ParagraphStyle("ReceiptFooter", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=11, alignment=1, textColor=colors.black),
        "footer_small": ParagraphStyle("ReceiptFooterSmall", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, alignment=1, textColor=colors.black),
        "alert_title": ParagraphStyle("ReceiptAlertTitle", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=11.5, leading=13.5, alignment=1, textColor=colors.black),
        "alert_subtitle": ParagraphStyle("ReceiptAlertSubtitle", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=9.5, leading=11.5, alignment=1, textColor=colors.black),
        "alert_row_label": ParagraphStyle("ReceiptAlertRowLabel", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=8.0, leading=10.0, textColor=colors.black),
        "alert_row_val": ParagraphStyle("ReceiptAlertRowVal", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=8.0, leading=10.0, alignment=2, textColor=colors.black),
        "alert_row_val_highlight": ParagraphStyle("ReceiptAlertRowValHi", parent=stylesheet["Normal"], fontName="Helvetica-Bold", fontSize=9.5, leading=11.5, alignment=2, textColor=colors.black),
    }

    client_str = str(snapshot["client_name"] or "Não informado").strip()
    client_font_size = 13.0
    client_leading = 15.0
    if len(client_str) > 40:
        client_font_size = 10.0
        client_leading = 12.0
    elif len(client_str) > 25:
        client_font_size = 11.5
        client_leading = 13.5

    client_style = ParagraphStyle(
        "ReceiptClientName",
        parent=stylesheet["Normal"],
        fontName="Helvetica-Bold",
        fontSize=client_font_size,
        leading=client_leading,
        textColor=colors.black,
    )

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
        Spacer(1, 2.0 * mm),
        HRFlowable(width="100%", thickness=1.0, color=colors.black, spaceBefore=0, spaceAfter=2.0 * mm),
        Paragraph("<b>CLIENTE</b>", styles["label"]),
        Spacer(1, 0.8 * mm),
        Paragraph(f"<b>{escape(client_str)}</b>", client_style),
        Spacer(1, 1.5 * mm),
        Paragraph(f"<b>Vendedor:</b> {escape(str(snapshot['seller_name']))}", styles["body"]),
        Paragraph(f"<b>Venda (nº: {escape(order.number)})</b>", styles["body"]),
        *( [Paragraph("<b>(CORREÇÃO / GARANTIA)</b>", styles["body"])] if snapshot.get("is_correction") else [] ),
        Spacer(1, 2.0 * mm),
        HRFlowable(width="100%", thickness=0.8, color=colors.black, spaceBefore=0, spaceAfter=2.0 * mm),
    ]

    item_header = Table(
        [[Paragraph("DESCRIÇÃO / QUANTIDADE X UNITÁRIO", styles["label"]), Paragraph("TOTAL", styles["label"])]],
        colWidths=[48 * mm, 24 * mm],
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

    total_amt = Decimal(str(snapshot["total"] or 0))
    paid_amt = Decimal(str(snapshot["paid_amount"] or 0))
    remaining_amt = max(Decimal(0), total_amt - paid_amt)
    method_label = PAYMENT_METHOD_LABELS.get(str(snapshot["payment_method"]), "Não informado")
    is_correction = bool(snapshot.get("is_correction"))

    if is_correction or (total_amt == Decimal("0.00") and paid_amt == Decimal("0.00")):
        correction_reason = snapshot.get("correction_reason")
        reason_txt = f"<br/><font size=7 color='#444444'>Motivo: {escape(str(correction_reason))}</font>" if correction_reason else ""
        total_table = Table(
            [
                [Paragraph("Total a Pagar", styles["total_label"]), Paragraph(_money(Decimal("0.00")), styles["total_value"])],
                [Paragraph(f"<b>PAGO</b> · Correção / Garantia{reason_txt}", styles["body"]), Paragraph(_money(Decimal("0.00")), styles["item_total"])],
            ],
            colWidths=[48 * mm, 24 * mm],
            hAlign="LEFT",
        )
        total_table.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.black),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ]))
        story.append(total_table)
    elif paid_amt >= total_amt and total_amt > 0:
        total_table = Table(
            [
                [Paragraph("Total a Pagar", styles["total_label"]), Paragraph(_money(total_amt), styles["total_value"])],
                [Paragraph(f"<b>PAGO</b> · {method_label}", styles["body"]), Paragraph(_money(paid_amt), styles["item_total"])],
            ],
            colWidths=[48 * mm, 24 * mm],
            hAlign="LEFT",
        )
        total_table.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.black),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ]))
        story.append(total_table)
    elif paid_amt > 0:
        # Pagamento Parcial em destaque
        warning_content = [
            [Paragraph("<b>ATENÇÃO</b>", styles["alert_title"])],
            [Paragraph("<b>PAGAMENTO PARCIAL</b>", styles["alert_subtitle"])],
            [Spacer(1, 1.2 * mm)],
            [Table([
                [Paragraph("<b>VALOR TOTAL:</b>", styles["alert_row_label"]), Paragraph(f"<b>{_money(total_amt)}</b>", styles["alert_row_val"])],
                [Paragraph(f"<b>VALOR PAGO ({method_label}):</b>", styles["alert_row_label"]), Paragraph(f"<b>{_money(paid_amt)}</b>", styles["alert_row_val"])],
                [Paragraph("<b>SALDO PENDENTE:</b>", styles["alert_row_label"]), Paragraph(f"<b>{_money(remaining_amt)}</b>", styles["alert_row_val_highlight"])],
            ], colWidths=[44 * mm, 26 * mm], hAlign="CENTER", style=[
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0.4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.4 * mm),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ])]
        ]
        warning_table = Table(
            warning_content,
            colWidths=[72 * mm],
            hAlign="CENTER",
        )
        warning_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.6, colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ]))
        story.append(warning_table)
    else:
        # Pagamento Pendente em destaque
        warning_content = [
            [Paragraph("<b>ATENÇÃO</b>", styles["alert_title"])],
            [Paragraph("<b>PAGAMENTO PENDENTE</b>", styles["alert_subtitle"])],
            [Spacer(1, 1.2 * mm)],
            [Table([
                [Paragraph("<b>VALOR TOTAL:</b>", styles["alert_row_label"]), Paragraph(f"<b>{_money(total_amt)}</b>", styles["alert_row_val"])],
                [Paragraph("<b>SALDO PENDENTE:</b>", styles["alert_row_label"]), Paragraph(f"<b>{_money(total_amt)}</b>", styles["alert_row_val_highlight"])],
            ], colWidths=[44 * mm, 26 * mm], hAlign="CENTER", style=[
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0.4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.4 * mm),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ])]
        ]
        warning_table = Table(
            warning_content,
            colWidths=[72 * mm],
            hAlign="CENTER",
        )
        warning_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.6, colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ]))
        story.append(warning_table)

    story.extend([
        Spacer(1, 3.5 * mm),
        Paragraph("CONFIRA SEU MATERIAL ANTES DE CORTAR", styles["footer"]),
        Paragraph("(não trocamos material cortado)", styles["footer_small"]),
    ])

    def _flowable_height(flowable, width: float) -> float:
        sb = getattr(flowable, "getSpaceBefore", lambda: getattr(flowable, "spaceBefore", 0))() or 0
        sa = getattr(flowable, "getSpaceAfter", lambda: getattr(flowable, "spaceAfter", 0))() or 0
        if hasattr(flowable, "_content"):
            ch = sum(_flowable_height(item, width) for item in getattr(flowable, "_content", []))
        else:
            try:
                _, h = flowable.wrap(width, 999999)
                ch = float(h)
            except Exception:
                ch = 0.0
        return ch + float(sb) + float(sa)

    # Dynamic and exact single-page height calculation with safety buffer for thermal rolls
    content_height = sum(_flowable_height(f, usable_width) for f in story)
    page_height = content_height + top_margin + bottom_margin + (10.0 * mm)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=(RECEIPT_WIDTH, page_height),
        leftMargin=RECEIPT_MARGIN,
        rightMargin=RECEIPT_MARGIN,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        title=f"Comprovante {order.number}",
        author="Print Fornece",
    )

    doc.build(story)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data
