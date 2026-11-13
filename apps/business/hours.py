"""Horário de funcionamento (A3) — fonte única para textos, prazos e contadores.

Tudo é calculado no fuso configurado do projeto (settings.TIME_ZONE).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.utils import timezone

WEEKDAY_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
WEEKDAY_CHOICES = [(0, "Segunda"), (1, "Terça"), (2, "Quarta"), (3, "Quinta"), (4, "Sexta"), (5, "Sábado"), (6, "Domingo")]
DEFAULT_DAYS = [0, 1, 2, 3, 4]
DEFAULT_OPEN = time(8, 0)
DEFAULT_CLOSE = time(17, 0)


def _hour_label(value: time) -> str:
    return f"{value.hour}h" if value.minute == 0 else f"{value.hour}h{value.minute:02d}"


def _group_days(days: list[int]) -> list[str]:
    """[0,1,2,3,4] -> ["Seg a Sex"]; [5,6] -> ["Sáb e Dom"]; [0,2] -> ["Seg", "Qua"]."""
    groups: list[list[int]] = []
    for day in sorted(days):
        if groups and day == groups[-1][-1] + 1:
            groups[-1].append(day)
        else:
            groups.append([day])
    labels = []
    for group in groups:
        if len(group) == 1:
            labels.append(WEEKDAY_SHORT[group[0]])
        elif len(group) == 2:
            labels.append(f"{WEEKDAY_SHORT[group[0]]} e {WEEKDAY_SHORT[group[1]]}")
        else:
            labels.append(f"{WEEKDAY_SHORT[group[0]]} a {WEEKDAY_SHORT[group[-1]]}")
    return labels


@dataclass(frozen=True)
class BusinessHours:
    days: frozenset[int] = frozenset(DEFAULT_DAYS)
    opens: time = DEFAULT_OPEN
    closes: time = DEFAULT_CLOSE

    @property
    def minutes_per_day(self) -> int:
        return (self.closes.hour * 60 + self.closes.minute) - (self.opens.hour * 60 + self.opens.minute)

    def _at(self, moment: datetime, at: time) -> datetime:
        return moment.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)

    def is_open(self, moment: datetime | None = None) -> bool:
        local = timezone.localtime(moment or timezone.now())
        return local.weekday() in self.days and self.opens <= local.time() < self.closes

    def next_opening(self, moment: datetime) -> datetime:
        """O próprio momento, se estiver no expediente; senão, a próxima abertura."""
        local = timezone.localtime(moment)
        if not self.days or self.minutes_per_day <= 0:
            return local
        for offset in range(0, 15):
            day = local + timedelta(days=offset)
            if day.weekday() not in self.days:
                continue
            opening = self._at(day, self.opens)
            closing = self._at(day, self.closes)
            if offset == 0:
                if local < opening:
                    return opening
                if local < closing:
                    return local
                continue
            return opening
        return local

    def add_business_minutes(self, start: datetime, minutes: int) -> datetime:
        """Soma minutos de trabalho respeitando o expediente.

        Um pedido feito fora do expediente começa a contar na próxima abertura.
        """
        current = self.next_opening(start)
        if not self.days or self.minutes_per_day <= 0:
            return current + timedelta(minutes=minutes)
        remaining = max(0, int(minutes))
        while remaining > 0:
            closing = self._at(current, self.closes)
            available = int((closing - current).total_seconds() // 60)
            if remaining <= available:
                return current + timedelta(minutes=remaining)
            remaining -= available
            current = self.next_opening(closing + timedelta(minutes=1))
        return current

    def subtract_business_minutes(self, end: datetime, minutes: int) -> datetime:
        """Momento X tal que entre X e ``end`` existam ``minutes`` minutos úteis."""
        current = timezone.localtime(end)
        if not self.days or self.minutes_per_day <= 0:
            return current - timedelta(minutes=minutes)
        remaining = max(0, int(minutes))
        for _ in range(0, 3660):  # limite de segurança (~10 anos de dias)
            if current.weekday() in self.days:
                opening = self._at(current, self.opens)
                closing = self._at(current, self.closes)
                window_end = min(current, closing)
                if window_end > opening:
                    available = int((window_end - opening).total_seconds() // 60)
                    if remaining <= available:
                        return window_end - timedelta(minutes=remaining)
                    remaining -= available
            previous_day = current - timedelta(days=1)
            current = previous_day.replace(hour=23, minute=59, second=59, microsecond=0)
        return current

    def describe(self, separator: str = " · ") -> str:
        """Texto humano, ex.: "Seg a Sex: 8h às 17h · Sáb e Dom: fechado"."""
        open_days = sorted(self.days)
        closed_days = [d for d in range(7) if d not in self.days]
        parts = []
        hours = f"{_hour_label(self.opens)} às {_hour_label(self.closes)}"
        for label in _group_days(open_days):
            parts.append(f"{label}: {hours}")
        if closed_days:
            parts.append(f"{' e '.join(_group_days(closed_days))}: fechado")
        return separator.join(parts)


def get_business_hours(config=None) -> BusinessHours:
    """Expediente vigente, lido da configuração do negócio (fonte única)."""
    if config is None:
        from .models import BusinessSettings

        config = BusinessSettings.load()
    days = frozenset(int(d) for d in (config.business_days or []) if str(d).isdigit() and 0 <= int(d) <= 6)
    return BusinessHours(
        days=days,
        opens=config.business_open_time or DEFAULT_OPEN,
        closes=config.business_close_time or DEFAULT_CLOSE,
    )
