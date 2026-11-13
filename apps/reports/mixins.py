from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .exports import EXPORT_FORMATS, export_response
from .periods import PRESETS, ReportPeriod, resolve_period, variation_percent


@dataclass
class SummaryMetric:
    """Indicador principal usado na comparação com o período anterior."""

    label: str
    value: Decimal | int | float
    kind: str = "money"  # money | number | meters


class PeriodReportMixin:
    """Período, comparação e exportação comuns a todos os relatórios.

    Cada relatório implementa ``build(period) -> dict`` com o contexto do template,
    incluindo ``summary`` (lista de SummaryMetric) e ``export_sections``
    (lista de ExportSection). O mixin cuida do resto.
    """

    report_title = "Relatório"
    report_slug = "relatorio"
    period_basis = "data de criação do pedido"
    period_default = "este_mes"
    period_use_session = True
    # Parâmetros extras que o filtro de período deve preservar (ex.: order_by)
    preserved_params: tuple[str, ...] = ()

    def build(self, period: ReportPeriod) -> dict:  # pragma: no cover - implementado por cada relatório
        raise NotImplementedError

    def pre_check(self, request):
        """Permite ao relatório responder antes do cálculo (ex.: módulo bloqueado)."""
        return None

    def get_period(self) -> tuple[ReportPeriod, str]:
        if not hasattr(self, "_period"):
            session = self.request.session if self.period_use_session else None
            self._period = resolve_period(self.request.GET, self.period_default, session=session)
        return self._period

    def comparison_rows(self, summary: list[SummaryMetric], period: ReportPeriod) -> tuple[ReportPeriod, list[dict]]:
        previous = period.previous()
        previous_summary = {metric.label: metric for metric in self.build(previous).get("summary", [])}
        rows = []
        for metric in summary:
            before = previous_summary.get(metric.label)
            before_value = before.value if before else 0
            rows.append({
                "label": metric.label,
                "kind": metric.kind,
                "current": metric.value,
                "previous": before_value,
                "variation": variation_percent(metric.value, before_value),
            })
        return previous, rows

    def get(self, request, *args, **kwargs):
        early = self.pre_check(request)
        if early is not None:
            return early
        period, period_error = self.get_period()
        data = self.build(period)

        fmt = (request.GET.get("export") or "").lower()
        if fmt in EXPORT_FORMATS:
            return export_response(
                fmt,
                base_filename=self.report_slug,
                title=self.report_title,
                period=period,
                basis=self.period_basis,
                sections=data.get("export_sections", []),
            )

        compare = request.GET.get("comparar") == "1"
        previous_period, comparison = (None, [])
        if compare and data.get("summary"):
            previous_period, comparison = self.comparison_rows(data["summary"], period)

        preserved = {key: request.GET.get(key) for key in self.preserved_params if request.GET.get(key)}
        context = self.get_context_data(
            **data,
            period=period,
            period_error=period_error,
            period_presets=PRESETS,
            period_basis=self.period_basis,
            period_preserved=preserved,
            report_title=self.report_title,
            compare=compare,
            previous_period=previous_period,
            comparison=comparison,
        )
        return self.render_to_response(context)
