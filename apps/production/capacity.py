from __future__ import annotations

import datetime
from decimal import Decimal
from dataclasses import dataclass
from django.db.models import Sum, Q
from django.utils import timezone

from apps.orders.models import Order, OrderItem

ACTIVE_STAGES = (
    Order.Stage.NEW,
    Order.Stage.AWAITING_PAYMENT,
    Order.Stage.PAYMENT_CONFIRMED,
    Order.Stage.PRE_PRESS,
    Order.Stage.PRODUCTION,
    Order.Stage.READY,
)


SHIFT_LIMITS_METERS: dict[str, Decimal] = {
    "dtf_textil": Decimal("25.00"),
    "dtf_uv": Decimal("25.00"),
}

MATERIAL_LABELS: dict[str, str] = {
    "dtf_textil": "DTF Têxtil",
    "dtf_uv": "DTF UV",
}


@dataclass
class ShiftCapacityStatus:
    material_code: str
    material_name: str
    shift: str
    shift_label: str
    target_date: datetime.date
    limit_meters: Decimal
    used_meters: Decimal
    remaining_meters: Decimal
    percentage: float
    is_exceeded: bool
    is_warning: bool

    def as_dict(self) -> dict:
        return {
            "material_code": self.material_code,
            "material_name": self.material_name,
            "shift": self.shift,
            "shift_label": self.shift_label,
            "target_date": self.target_date.isoformat(),
            "limit_meters": float(self.limit_meters),
            "used_meters": float(self.used_meters),
            "remaining_meters": float(self.remaining_meters),
            "percentage": self.percentage,
            "is_exceeded": self.is_exceeded,
            "is_warning": self.is_warning,
        }


def get_used_meters_for_shift(
    *,
    target_date: datetime.date,
    shift: str,
    material_code: str,
    exclude_order_id: int | None = None,
) -> Decimal:
    """Calculate total DTF meters scheduled for production in a specific shift & date."""
    queryset = OrderItem.objects.filter(
        kind=OrderItem.Kind.MATERIAL,
        material_code=material_code,
        order__stage__in=ACTIVE_STAGES,
        order__shift=shift,
    )

    # Consider due_at date if present, otherwise fallback to created_at date
    date_filter = Q(order__due_at__date=target_date) | (Q(order__due_at__isnull=True) & Q(order__created_at__date=target_date))
    queryset = queryset.filter(date_filter)

    if exclude_order_id:
        queryset = queryset.exclude(order_id=exclude_order_id)

    total = queryset.aggregate(total_meters=Sum("billing_quantity"))["total_meters"]
    return total or Decimal("0.00")


def get_shift_capacity_status(
    *,
    target_date: datetime.date | None = None,
    shift: str = Order.Shift.MORNING,
    material_code: str = "dtf_textil",
    exclude_order_id: int | None = None,
) -> ShiftCapacityStatus:
    if target_date is None:
        target_date = timezone.localdate()

    limit = SHIFT_LIMITS_METERS.get(material_code, Decimal("25.00"))
    used = get_used_meters_for_shift(
        target_date=target_date,
        shift=shift,
        material_code=material_code,
        exclude_order_id=exclude_order_id,
    )
    remaining = max(Decimal("0.00"), limit - used)
    percentage = min(100.0, round(float(used / limit * 100), 1)) if limit > 0 else 0.0
    shift_label = Order.Shift(shift).label if shift in Order.Shift.values else shift.capitalize()
    material_name = MATERIAL_LABELS.get(material_code, material_code)

    return ShiftCapacityStatus(
        material_code=material_code,
        material_name=material_name,
        shift=shift,
        shift_label=shift_label,
        target_date=target_date,
        limit_meters=limit,
        used_meters=used,
        remaining_meters=remaining,
        percentage=percentage,
        is_exceeded=used > limit,
        is_warning=used >= (limit * Decimal("0.80")),
    )


def get_daily_capacity_overview(target_date: datetime.date | None = None) -> list[ShiftCapacityStatus]:
    """Return overview for both DTF types across both Morning and Afternoon shifts."""
    if target_date is None:
        target_date = timezone.localdate()

    overview = []
    for mat_code in ("dtf_textil", "dtf_uv"):
        for shift_val in (Order.Shift.MORNING, Order.Shift.AFTERNOON):
            overview.append(
                get_shift_capacity_status(
                    target_date=target_date,
                    shift=shift_val,
                    material_code=mat_code,
                )
            )
    return overview


def evaluate_order_capacity(
    *,
    order: Order | None = None,
    target_date: datetime.date | None = None,
    shift: str = Order.Shift.MORNING,
    dtf_textil_meters: Decimal = Decimal("0.00"),
    dtf_uv_meters: Decimal = Decimal("0.00"),
) -> list[str]:
    """Check if adding or updating an order breaches the 25m shift limit and return warning messages."""
    if target_date is None:
        if order and order.due_at:
            target_date = timezone.localtime(order.due_at).date()
        else:
            target_date = timezone.localdate()

    exclude_id = order.pk if order and order.pk else None
    warnings = []

    if dtf_textil_meters > 0:
        current_used = get_used_meters_for_shift(
            target_date=target_date,
            shift=shift,
            material_code="dtf_textil",
            exclude_order_id=exclude_id,
        )
        projected = current_used + dtf_textil_meters
        limit = SHIFT_LIMITS_METERS["dtf_textil"]
        shift_name = Order.Shift(shift).label
        if projected > limit:
            warnings.append(
                f"Limite de DTF Têxtil para o turno da {shift_name.upper()} em {target_date.strftime('%d/%m/%Y')} "
                f"ultrapassado! Capacidade máxima: {limit:.1f}m · Total projetado: {projected:.2f}m."
            )

    if dtf_uv_meters > 0:
        current_used = get_used_meters_for_shift(
            target_date=target_date,
            shift=shift,
            material_code="dtf_uv",
            exclude_order_id=exclude_id,
        )
        projected = current_used + dtf_uv_meters
        limit = SHIFT_LIMITS_METERS["dtf_uv"]
        shift_name = Order.Shift(shift).label
        if projected > limit:
            warnings.append(
                f"Limite de DTF UV para o turno da {shift_name.upper()} em {target_date.strftime('%d/%m/%Y')} "
                f"ultrapassado! Capacidade máxima: {limit:.1f}m · Total projetado: {projected:.2f}m."
            )

    return warnings
