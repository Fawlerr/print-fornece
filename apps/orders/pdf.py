from __future__ import annotations

import io
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def generate_order_receipt_pdf(order) -> bytes:
    """Generate a clean PDF receipt / order invoice using ReportLab."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    story = []

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#111827'),
        fontName='Helvetica-Bold',
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#4B5563'),
        fontName='Helvetica',
    )
    temp_notice_style = ParagraphStyle(
        'TempNotice',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#DC2626'),
        fontName='Helvetica-Oblique',
        alignment=1, # Center
    )
    label_style = ParagraphStyle(
        'MetaLabel',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#6B7280'),
        fontName='Helvetica-Bold',
    )
    value_style = ParagraphStyle(
        'MetaValue',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#111827'),
        fontName='Helvetica',
    )

    # Header section
    story.append(Paragraph("PRINT FORNECE", title_style))
    story.append(Paragraph(f"Comprovante do Pedido <b>#{order.number}</b>", subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    
    # Placeholder Watermark / Notice
    story.append(Paragraph("⚠️ <i>[LAYOUT TEMPORÁRIO DE REFERÊNCIA — MARCA D'ÁGUA TEMPORÁRIA]</i>", temp_notice_style))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E5E7EB'), spaceBefore=0, spaceAfter=15))

    # Order Meta Table
    client_info = f"<b>Cliente:</b> {order.client_name}<br/><b>WhatsApp:</b> {order.client_whatsapp or 'Não informado'}"
    order_info = f"<b>Data do Pedido:</b> {timezone.localtime(order.created_at).strftime('%d/%m/%Y %H:%M')}<br/><b>Status Pagamento:</b> {order.get_payment_status_display()}<br/><b>Etapa:</b> {order.get_stage_display()}"
    
    meta_table_data = [
        [Paragraph(client_info, value_style), Paragraph(order_info, value_style)]
    ]
    meta_table = Table(meta_table_data, colWidths=[9.5 * cm, 8.5 * cm])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('ROUNDEDCORNERS', [4, 4, 4, 4]),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.5 * cm))

    # Description Section
    story.append(Paragraph("Descrição do Pedido / Produtos:", label_style))
    story.append(Spacer(1, 0.1 * cm))
    desc_p = Paragraph(order.description.replace("\n", "<br/>") if order.description else "Sem descrição.", value_style)
    desc_table = Table([[desc_p]], colWidths=[18 * cm])
    desc_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFFFFF')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
    ]))
    story.append(desc_table)
    story.append(Spacer(1, 0.6 * cm))

    # Values Summary Table
    val_table_data = [
        [Paragraph("<b>Resumo Financeiro</b>", label_style), Paragraph("<b>Valor (R$)</b>", label_style)],
        [Paragraph("Valor Total", value_style), Paragraph(f"R$ {order.total_amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), value_style)],
        [Paragraph("Valor Pago", value_style), Paragraph(f"R$ {order.paid_amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), value_style)],
        [Paragraph("Saldo Restante", value_style), Paragraph(f"R$ {max(0, order.remaining_amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), value_style)],
        [Paragraph("Forma de Pagamento", value_style), Paragraph(order.get_payment_method_display() or "Não especificada", value_style)],
    ]
    val_table = Table(val_table_data, colWidths=[12 * cm, 6 * cm])
    val_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#F3F4F6')),
        ('LINEBELOW', (0, 0), (1, 0), 1, colors.HexColor('#D1D5DB')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    story.append(val_table)
    story.append(Spacer(1, 1.0 * cm))

    # Footer
    footer_text = f"Comprovante gerado em {timezone.localtime().strftime('%d/%m/%Y às %H:%M')} — Print Fornece"
    story.append(Paragraph(footer_text, ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#9CA3AF'), alignment=1)))

    doc.build(story)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data
