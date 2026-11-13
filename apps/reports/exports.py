"""Exportação dos relatórios em CSV, Excel (.xlsx) e PDF, sempre no período filtrado."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

EXPORT_FORMATS = ("csv", "xlsx", "pdf")


@dataclass
class ExportSection:
    """Um bloco tabular do relatório (título opcional, cabeçalho e linhas)."""

    headers: list[str]
    rows: list[list] = field(default_factory=list)
    title: str = ""
    totals: list | None = None


def _br_number(value: Decimal | float, places: int = 2) -> str:
    text = f"{Decimal(str(value)):,.{places}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _as_text(value, for_csv: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if timezone.is_aware(value) else value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, Decimal | float):
        # CSV mantém o padrão já usado no sistema (sem separador de milhar, vírgula decimal)
        return f"{Decimal(str(value)):.2f}".replace(".", ",") if for_csv else _br_number(value)
    return str(value)


def _filename(base: str, period, extension: str) -> str:
    return f"{base}-{period.start:%Y%m%d}-{period.end:%Y%m%d}.{extension}"


def export_csv(*, base_filename: str, title: str, period, basis: str, sections: list[ExportSection]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{_filename(base_filename, period, "csv")}"'
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow([f"PRINT FORNECE - {title.upper()}", f"Período: {period.label}"])
    if basis:
        writer.writerow([f"Período baseado na {basis}"])
    for section in sections:
        writer.writerow([])
        if section.title:
            writer.writerow([section.title.upper()])
        writer.writerow(section.headers)
        for row in section.rows:
            writer.writerow([_as_text(value, for_csv=True) for value in row])
        if section.totals:
            writer.writerow([_as_text(value, for_csv=True) for value in section.totals])
    return response


def export_xlsx(*, base_filename: str, title: str, period, basis: str, sections: list[ExportSection]) -> HttpResponse:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31] or "Relatório"
    bold = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="DDE7E1")
    sheet.append([f"Print Fornece — {title}"])
    sheet["A1"].font = Font(bold=True, size=13)
    sheet.append([f"Período: {period.label}"])
    if basis:
        sheet.append([f"Período baseado na {basis}"])
    widths: dict[int, int] = {}

    def add_row(values, font=None, fill=None):
        cells = []
        for value in values:
            if isinstance(value, Decimal):
                value = float(value)
            elif isinstance(value, datetime):
                value = timezone.localtime(value).replace(tzinfo=None) if timezone.is_aware(value) else value
            cells.append(value)
        sheet.append(cells)
        row_index = sheet.max_row
        for col, value in enumerate(cells, start=1):
            cell = sheet.cell(row=row_index, column=col)
            if font:
                cell.font = font
            if fill:
                cell.fill = fill
            if isinstance(value, float):
                cell.number_format = "#,##0.00"
            elif isinstance(value, datetime):
                cell.number_format = "dd/mm/yyyy hh:mm"
            elif isinstance(value, date):
                cell.number_format = "dd/mm/yyyy"
            widths[col] = max(widths.get(col, 8), min(60, len(_as_text(value)) + 2))

    for section in sections:
        sheet.append([])
        if section.title:
            add_row([section.title], font=bold)
        add_row(section.headers, font=bold, fill=header_fill)
        for row in section.rows:
            add_row(row)
        if section.totals:
            add_row(section.totals, font=bold)
    for col, width in widths.items():
        sheet.column_dimensions[get_column_letter(col)].width = width

    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{_filename(base_filename, period, "xlsx")}"'
    return response


def export_pdf(*, base_filename: str, title: str, period, basis: str, sections: list[ExportSection]) -> HttpResponse:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buffer, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title=title)
    styles = getSampleStyleSheet()
    cell_style = styles["BodyText"].clone("cell", fontSize=7.5, leading=9)
    head_style = styles["BodyText"].clone("head", fontSize=7.5, leading=9, fontName="Helvetica-Bold")
    story = [
        Paragraph(f"Print Fornece — {escape(title)}", styles["Title"]),
        Paragraph(f"Período: {escape(period.label)}" + (f" · baseado na {escape(basis)}" if basis else ""), styles["Normal"]),
        Paragraph(f"Gerado em {timezone.localtime():%d/%m/%Y %H:%M}", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    usable_width = page[0] - 24 * mm
    for section in sections:
        if section.title:
            story.append(Paragraph(escape(section.title), styles["Heading3"]))
        data = [[Paragraph(escape(str(h)), head_style) for h in section.headers]]
        data += [[Paragraph(escape(_as_text(v)), cell_style) for v in row] for row in section.rows]
        if section.totals:
            data.append([Paragraph(f"<b>{escape(_as_text(v))}</b>", cell_style) for v in section.totals])
        if len(data) == 1:
            data.append([Paragraph("Sem registros no período.", cell_style)] + [""] * (len(section.headers) - 1))
        col_width = usable_width / max(1, len(section.headers))
        table = Table(data, colWidths=[col_width] * len(section.headers), repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE7E1")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9AA5A0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7F5")]),
        ]))
        story += [table, Spacer(1, 5 * mm)]
    doc.build(story)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_filename(base_filename, period, "pdf")}"'
    return response


EXPORTERS = {"csv": export_csv, "xlsx": export_xlsx, "pdf": export_pdf}


def export_response(fmt: str, **kwargs) -> HttpResponse:
    return EXPORTERS[fmt](**kwargs)
