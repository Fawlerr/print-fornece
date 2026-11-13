from __future__ import annotations

from decimal import Decimal

from apps.orders.calculator import ShirtDiscountRule

from .models import BusinessSettings


def get_business_settings() -> BusinessSettings:
    return BusinessSettings.load()


def shirt_discount_rule(config: BusinessSettings | None = None) -> ShirtDiscountRule:
    """Regra de desconto por camisa vigente, lida do banco (fonte única)."""
    config = config or get_business_settings()
    value = Decimal(config.shirt_discount_value or 0)
    return ShirtDiscountRule(
        enabled=bool(config.shirt_discount_enabled and value > 0),
        kind=config.shirt_discount_type,
        value=value,
        min_quantity=max(1, int(config.shirt_discount_min_quantity or 1)),
        eligible_codes=frozenset(config.shirt_discount_models or []),
    )
