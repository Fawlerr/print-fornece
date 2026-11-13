"""Período dos relatórios (A2): atalhos, datas personalizadas e período anterior.

Regras:
- o período é sempre de dias inteiros no fuso configurado do projeto (TIME_ZONE):
  de ``início 00:00`` até antes de ``fim + 1 dia 00:00`` — ou seja, o dia final
  entra inteiro (até 23:59:59,999999);
- data inicial maior que a final é erro (não inverte em silêncio);
- o período escolhido fica na URL (link compartilhável) e na sessão (para manter
  o mesmo período ao navegar entre os relatórios).
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from django.utils import timezone

MAX_PERIOD_DAYS = 366 * 5  # limite de 5 anos por consulta

PRESETS: list[tuple[str, str]] = [
    ("hoje", "Hoje"),
    ("ontem", "Ontem"),
    ("7d", "Últimos 7 dias"),
    ("30d", "Últimos 30 dias"),
    ("este_mes", "Este mês"),
    ("mes_passado", "Mês passado"),
    ("este_ano", "Este ano"),
    ("personalizado", "Personalizado"),
]
PRESET_LABELS = dict(PRESETS)
SESSION_KEY = "reports_period"


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(day: date, months: int) -> tuple[int, int]:
    index = day.year * 12 + (day.month - 1) + months
    return index // 12, index % 12 + 1


def preset_range(preset: str, today: date | None = None) -> tuple[date, date] | None:
    today = today or timezone.localdate()
    if preset == "hoje":
        return today, today
    if preset == "ontem":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if preset == "7d":
        return today - timedelta(days=6), today
    if preset == "30d":
        return today - timedelta(days=29), today
    if preset == "este_mes":
        return today.replace(day=1), today
    if preset == "mes_passado":
        year, month = _shift_month(today, -1)
        return _month_bounds(year, month)
    if preset == "este_ano":
        return date(today.year, 1, 1), today
    return None


@dataclass(frozen=True)
class ReportPeriod:
    start: date
    end: date
    preset: str = "personalizado"

    @property
    def start_at(self) -> datetime:
        """Início do período (00:00 do dia inicial, no fuso do projeto)."""
        return timezone.make_aware(datetime.combine(self.start, time.min))

    @property
    def end_at(self) -> datetime:
        """Fim EXCLUSIVO: 00:00 do dia seguinte ao final (inclui o dia final inteiro)."""
        return timezone.make_aware(datetime.combine(self.end + timedelta(days=1), time.min))

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def label(self) -> str:
        if self.start == self.end:
            return self.start.strftime("%d/%m/%Y")
        return f"{self.start:%d/%m/%Y} a {self.end:%d/%m/%Y}"

    @property
    def preset_label(self) -> str:
        return PRESET_LABELS.get(self.preset, "Personalizado")

    @property
    def query_params(self) -> dict[str, str]:
        if self.preset != "personalizado" and self.preset in PRESET_LABELS:
            return {"periodo": self.preset}
        return {"inicio": self.start.isoformat(), "fim": self.end.isoformat()}

    @property
    def querystring(self) -> str:
        return urlencode(self.query_params)

    def previous(self) -> "ReportPeriod":
        """Período anterior equivalente (ex.: este mês x mesmo trecho do mês passado)."""
        first_of_month = self.start.day == 1
        same_month = (self.start.year, self.start.month) == (self.end.year, self.end.month)
        if first_of_month and same_month:
            year, month = _shift_month(self.start, -1)
            _, last_day = _month_bounds(year, month)
            end_day = min(self.end.day, last_day.day)
            if self.end == _month_bounds(self.end.year, self.end.month)[1]:
                end_day = last_day.day  # mês completo x mês anterior completo
            return ReportPeriod(date(year, month, 1), date(year, month, end_day))
        if self.start == date(self.start.year, 1, 1) and self.end.year == self.start.year:
            prev_year = self.start.year - 1
            end = self.end.replace(year=prev_year) if not (self.end.month == 2 and self.end.day == 29) else date(prev_year, 2, 28)
            return ReportPeriod(date(prev_year, 1, 1), end)
        length = self.days
        prev_end = self.start - timedelta(days=1)
        return ReportPeriod(prev_end - timedelta(days=length - 1), prev_end)


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _legacy_period(params) -> ReportPeriod | None:
    """Aceita os parâmetros antigos para não quebrar links já salvos."""
    start = _parse_iso(params.get("start"))
    end = _parse_iso(params.get("end"))
    if start or end:
        today = timezone.localdate()
        start = start or today.replace(day=1)
        end = end or today
        if end < start:
            start, end = end, start
        return ReportPeriod(start, end)
    single = _parse_iso(params.get("date"))
    if single:
        return ReportPeriod(single, single)
    month_raw = (params.get("month") or "").strip()
    year_raw = (params.get("year") or "").strip()
    try:
        if "-" in month_raw:  # month=YYYY-MM
            year, month = (int(part) for part in month_raw.split("-", 1))
            return ReportPeriod(*_month_bounds(year, month))
        if year_raw:
            year = int(year_raw)
            if month_raw and month_raw != "todos":
                return ReportPeriod(*_month_bounds(year, int(month_raw)))
            return ReportPeriod(date(year, 1, 1), date(year, 12, 31))
        if month_raw and month_raw != "todos":
            return ReportPeriod(*_month_bounds(timezone.localdate().year, int(month_raw)))
    except (TypeError, ValueError):
        return None
    return None


def resolve_period(params, default_preset: str = "este_mes", session=None) -> tuple[ReportPeriod, str]:
    """Lê o período da query string. Retorna (período, mensagem de erro ou "")."""
    error = ""
    # 1) Atalho escolhido (Hoje, Este mês...) tem prioridade sobre as datas do formulário.
    preset = (params.get("periodo") or "").strip()
    if preset in PRESET_LABELS and preset != "personalizado":
        start, end = preset_range(preset)
        return _remember(ReportPeriod(start, end, preset), session), ""

    # 2) Período personalizado (data inicial e final).
    inicio_raw, fim_raw = params.get("inicio"), params.get("fim")
    if inicio_raw or fim_raw:
        inicio, fim = _parse_iso(inicio_raw), _parse_iso(fim_raw)
        if not inicio or not fim:
            error = "Informe a data inicial e a data final no formato correto."
        elif inicio > fim:
            error = "A data inicial não pode ser maior que a data final."
        elif (fim - inicio).days + 1 > MAX_PERIOD_DAYS:
            error = "O período máximo por consulta é de 5 anos."
        else:
            return _remember(ReportPeriod(inicio, fim), session), ""

    # 3) Parâmetros antigos (links salvos antes do filtro comum).
    if not error:
        legacy = _legacy_period(params)
        if legacy:
            return _remember(legacy, session), ""

    if session is not None and not error:
        stored = session.get(SESSION_KEY) or {}
        if stored.get("periodo") in PRESET_LABELS and stored.get("periodo") != "personalizado":
            start, end = preset_range(stored["periodo"])
            return ReportPeriod(start, end, stored["periodo"]), ""
        start, end = _parse_iso(stored.get("inicio")), _parse_iso(stored.get("fim"))
        if start and end and start <= end:
            return ReportPeriod(start, end), ""

    start, end = preset_range(default_preset)
    return ReportPeriod(start, end, default_preset), error


def _remember(period: ReportPeriod, session) -> ReportPeriod:
    if session is not None:
        session[SESSION_KEY] = period.query_params
    return period


def variation_percent(current, previous) -> float | None:
    """Variação percentual entre períodos (None quando a base é zero)."""
    try:
        current_f, previous_f = float(current or 0), float(previous or 0)
    except (TypeError, ValueError):
        return None
    if previous_f == 0:
        return None
    return round((current_f - previous_f) / abs(previous_f) * 100, 1)
