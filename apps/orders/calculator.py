"""Pricing rules shared by the native Print Fornece calculator.

The calculator module is the server-authoritative source of truth for pricing
rules across DTF printing, garment products (shirts), and extra pre-press services.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP


CENTIMETERS_PER_METER = Decimal("100")
MARGIN_CM = Decimal("1")
MONEY_CENT = Decimal("0.01")


class CalculatorValidationError(ValueError):
    """Raised when the calculator receives an invalid material, measure, or product."""


@dataclass(frozen=True)
class CalculatorMaterial:
    code: str
    name: str
    category: str
    film_width_cm: Decimal
    maximum_art_width_cm: Decimal
    unit: str = "Metro"

    def catalogue_data(self) -> dict[str, str]:
        """Data needed by the order form before a calculation is requested."""
        return {
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "film_width_cm": decimal_string(self.film_width_cm),
            "maximum_art_width_cm": decimal_string(self.maximum_art_width_cm),
            "unit": self.unit,
        }


@dataclass(frozen=True)
class CalculatorShirt:
    code: str
    name: str
    category: str = "Camisas"
    unit: str = "Unidade"
    price_single: Decimal = Decimal("28.00")
    price_tiered: Decimal = Decimal("25.00")
    tier_threshold: int = 5
    available_colors: tuple[str, ...] = ("Preta", "Branca")
    available_sizes: tuple[str, ...] = ("P", "M", "G", "GG")

    def catalogue_data(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "price_single": decimal_string(self.price_single),
            "price_tiered": decimal_string(self.price_tiered),
            "tier_threshold": self.tier_threshold,
            "colors": list(self.available_colors),
            "sizes": list(self.available_sizes),
        }


@dataclass(frozen=True)
class CalculatorService:
    code: str
    name: str
    category: str = "Serviços"
    unit: str = "Serviço"
    unit_price: Decimal = Decimal("20.00")

    def catalogue_data(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "unit_price": decimal_string(self.unit_price),
        }


MATERIALS: dict[str, CalculatorMaterial] = {
    "dtf_textil": CalculatorMaterial(
        code="dtf_textil",
        name="DTF Têxtil",
        category="Têxtil",
        film_width_cm=Decimal("59"),
        maximum_art_width_cm=Decimal("58"),
    ),
    "dtf_uv": CalculatorMaterial(
        code="dtf_uv",
        name="DTF UV Rígidos",
        category="UV Rígidos",
        film_width_cm=Decimal("29"),
        maximum_art_width_cm=Decimal("28"),
    ),
}

SHIRTS: dict[str, CalculatorShirt] = {
    "camisa_algodao_menegotti": CalculatorShirt(
        code="camisa_algodao_menegotti",
        name="100% Algodão (Menegotti)",
        category="Camisas",
        price_single=Decimal("28.00"),
        price_tiered=Decimal("25.00"),
        tier_threshold=5,
        available_colors=("Preta", "Branca"),
        available_sizes=("P", "M", "G", "GG"),
    ),
    "camisa_dry_fit_grao_arroz": CalculatorShirt(
        code="camisa_dry_fit_grao_arroz",
        name="Dry Fit (Grão de Arroz)",
        category="Camisas",
        price_single=Decimal("23.00"),
        price_tiered=Decimal("20.00"),
        tier_threshold=5,
        available_colors=("Preta", "Branca"),
        available_sizes=("P", "M", "G", "GG"),
    ),
}

SERVICES: dict[str, CalculatorService] = {
    "ajuste_preparacao_arquivo": CalculatorService(
        code="ajuste_preparacao_arquivo",
        name="Serviço de ajustes e preparação de arquivo",
        category="Serviços",
        unit_price=Decimal("20.00"),
    ),
    "formato_halftone": CalculatorService(
        code="formato_halftone",
        name="Serviço para formato de Halftone",
        category="Serviços",
        unit_price=Decimal("10.00"),
    ),
}


@dataclass(frozen=True)
class Quote:
    material: CalculatorMaterial
    art_width_cm: Decimal
    art_height_cm: Decimal
    quantity: int
    used_orientation: str
    layout_width_cm: Decimal
    layout_height_cm: Decimal
    pieces_per_row: int
    rows: int
    film_used_cm: Decimal
    film_used_m: Decimal
    pricing_type: str
    pricing_rule: str
    unit_price: Decimal
    total: Decimal

    def payload(self) -> dict[str, str | int]:
        """JSON-safe response used by the calculation endpoint and form JS."""
        return {
            "kind": "material",
            "material_code": self.material.code,
            "material_name": self.material.name,
            "category": self.material.category,
            "unit": self.material.unit,
            "film_width_cm": decimal_string(self.material.film_width_cm),
            "maximum_art_width_cm": decimal_string(self.material.maximum_art_width_cm),
            "art_width_cm": decimal_string(self.art_width_cm),
            "art_height_cm": decimal_string(self.art_height_cm),
            "quantity": self.quantity,
            "used_orientation": self.used_orientation,
            "pieces_per_row": self.pieces_per_row,
            "rows": self.rows,
            "film_used_cm": decimal_string(self.film_used_cm),
            "film_used_m": decimal_string(self.film_used_m),
            "pricing_type": self.pricing_type,
            "pricing_rule": self.pricing_rule,
            "unit_price": decimal_string(self.unit_price),
            "total": decimal_string(self.total),
        }

    def persisted_snapshot(self) -> dict[str, str | int]:
        """Immutable calculation context saved with a sales item."""
        return self.payload() | {"margin_cm": decimal_string(MARGIN_CM)}


@dataclass(frozen=True)
class ShirtQuote:
    shirt: CalculatorShirt
    color: str
    size: str
    quantity: int
    unit_price: Decimal
    total: Decimal
    pricing_rule: str

    def payload(self) -> dict[str, str | int]:
        return {
            "kind": "produto",
            "material_code": self.shirt.code,
            "material_name": f"Camisa {self.shirt.name}",
            "category": self.shirt.category,
            "product_color": self.color,
            "product_size": self.size,
            "quantity": self.quantity,
            "unit": self.shirt.unit,
            "unit_price": decimal_string(self.unit_price),
            "total": decimal_string(self.total),
            "pricing_rule": self.pricing_rule,
            "calculation_detail": f"{self.quantity} un ({self.color}, {self.size}) × R$ {self.unit_price:.2f}".replace(".", ","),
        }

    def persisted_snapshot(self) -> dict[str, str | int]:
        return self.payload()


@dataclass(frozen=True)
class ServiceQuote:
    service: CalculatorService
    quantity: int
    unit_price: Decimal
    total: Decimal
    pricing_rule: str

    def payload(self) -> dict[str, str | int]:
        return {
            "kind": "servico",
            "material_code": self.service.code,
            "material_name": self.service.name,
            "category": self.service.category,
            "quantity": self.quantity,
            "unit": self.service.unit,
            "unit_price": decimal_string(self.unit_price),
            "total": decimal_string(self.total),
            "pricing_rule": self.pricing_rule,
            "calculation_detail": f"{self.quantity} un × R$ {self.unit_price:.2f}".replace(".", ","),
        }

    def persisted_snapshot(self) -> dict[str, str | int]:
        return self.payload()


def decimal_string(value: Decimal) -> str:
    """Use non-exponential strings so JSON snapshots remain stable and readable."""
    return format(value, "f")


def available_materials() -> tuple[CalculatorMaterial, ...]:
    return tuple(MATERIALS.values())


def material_catalogue() -> list[dict[str, str]]:
    return [material.catalogue_data() for material in available_materials()]


def full_catalogue() -> dict:
    return {
        "materials": material_catalogue(),
        "shirts": [s.catalogue_data() for s in SHIRTS.values()],
        "services": [s.catalogue_data() for s in SERVICES.values()],
    }


def _as_decimal(value, field_name: str) -> Decimal:
    if value is None or str(value).strip() == "":
        raise CalculatorValidationError("Preencha largura, altura e quantidade.")
    try:
        parsed = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise CalculatorValidationError("Preencha largura, altura e quantidade.") from None
    if not parsed.is_finite() or parsed <= 0:
        raise CalculatorValidationError("Preencha largura, altura e quantidade.")
    return parsed


def _as_quantity(value) -> int:
    parsed = _as_decimal(value, "quantidade")
    quantity = int(parsed)
    if quantity < 1:
        raise CalculatorValidationError("A quantidade deve ser de no mínimo 1.")
    return quantity


def _ceil_centimeter(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_CEILING)


def _floor_to_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _price_textile(film_cm: Decimal, film_m: Decimal) -> tuple[str, str, Decimal, Decimal]:
    if film_cm <= Decimal("30"):
        return "fixed", "Até 30 cm", Decimal("23"), Decimal("23")
    if film_cm <= Decimal("50"):
        return "fixed", "31 a 50 cm", Decimal("30"), Decimal("30")
    if film_cm <= Decimal("80"):
        unit_price = Decimal("60")
        return "per_meter", "51 a 80 cm", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    if film_cm <= Decimal("100"):
        return "fixed", "81 a 100 cm (1 metro)", Decimal("50"), Decimal("50")
    if film_m <= Decimal("9"):
        unit_price = Decimal("50")
        return "per_meter", "01 a 09 metros", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    if film_m <= Decimal("29"):
        unit_price = Decimal("45")
        return "per_meter", "10 a 29 metros", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    if film_m <= Decimal("49"):
        unit_price = Decimal("39.90")
        return "per_meter", "30 a 49 metros", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    unit_price = Decimal("35")
    return "per_meter", "50 metros ou mais", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)


def _price_uv(film_cm: Decimal, film_m: Decimal) -> tuple[str, str, Decimal, Decimal]:
    if film_cm <= Decimal("30"):
        return "fixed", "Até 30 cm", Decimal("35"), Decimal("35")
    if film_cm <= Decimal("50"):
        return "fixed", "31 a 50 cm", Decimal("45"), Decimal("45")
    if film_cm <= Decimal("90"):
        unit_price = Decimal("90")
        return "per_meter", "51 a 90 cm", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    if film_cm <= Decimal("100"):
        return "fixed", "91 a 100 cm (1 metro)", Decimal("75"), Decimal("75")
    if film_m < Decimal("2"):
        unit_price = Decimal("75")
        return "per_meter", "01 a menos de 02 metros", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    if film_m < Decimal("6"):
        unit_price = Decimal("70")
        return "per_meter", "02 a menos de 06 metros", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    unit_price = Decimal("65")
    return "per_meter", "06 metros ou mais", unit_price, (film_m * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)


def calculate_quote(*, material_code: str, width_cm, height_cm, quantity) -> Quote:
    material = MATERIALS.get(material_code)
    if material is None:
        raise CalculatorValidationError("Selecione um material válido.")

    art_width = _as_decimal(width_cm, "largura")
    art_height = _as_decimal(height_cm, "altura")
    amount = _as_quantity(quantity)

    candidates: list[tuple[Decimal, Decimal, Decimal, int, int, str]] = []
    for orientation, layout_width, layout_height in (
        ("normal", art_width, art_height),
        ("rotacionada", art_height, art_width),
    ):
        if layout_width > material.maximum_art_width_cm:
            continue
        pieces_per_row = _floor_to_int((material.film_width_cm + MARGIN_CM) / (layout_width + MARGIN_CM))
        if pieces_per_row < 1:
            continue
        rows = (amount + pieces_per_row - 1) // pieces_per_row
        length_cm = (Decimal(rows) * layout_height) + (Decimal(rows - 1) * MARGIN_CM)
        candidates.append((length_cm, layout_width, layout_height, pieces_per_row, rows, orientation))

    if not candidates:
        maximum = decimal_string(material.maximum_art_width_cm)
        raise CalculatorValidationError(f"A largura máxima para {material.name} é {maximum} cm.")

    length_cm, layout_width, layout_height, pieces_per_row, rows, orientation = min(candidates, key=lambda item: item[0])
    used_cm = _ceil_centimeter(length_cm)
    used_m = (used_cm / CENTIMETERS_PER_METER).quantize(Decimal("0.01"))

    if material.code == "dtf_textil":
        pricing_type, pricing_rule, unit_price, total = _price_textile(used_cm, used_m)
    else:
        pricing_type, pricing_rule, unit_price, total = _price_uv(used_cm, used_m)

    return Quote(
        material=material,
        art_width_cm=art_width,
        art_height_cm=art_height,
        quantity=amount,
        used_orientation=orientation,
        layout_width_cm=layout_width,
        layout_height_cm=layout_height,
        pieces_per_row=pieces_per_row,
        rows=rows,
        film_used_cm=used_cm,
        film_used_m=used_m,
        pricing_type=pricing_type,
        pricing_rule=pricing_rule,
        unit_price=unit_price,
        total=total,
    )


def calculate_shirt_quote(*, shirt_code: str, color: str, size: str, quantity: int | str) -> ShirtQuote:
    shirt = SHIRTS.get(shirt_code)
    if not shirt:
        raise CalculatorValidationError("Selecione um modelo de camisa válido.")
    qty = _as_quantity(quantity)
    color = str(color).strip()
    size = str(size).strip().upper()
    if color not in shirt.available_colors:
        raise CalculatorValidationError(f"Cor inválida ({color}). Escolha entre: {', '.join(shirt.available_colors)}.")
    if size not in shirt.available_sizes:
        raise CalculatorValidationError(f"Tamanho inválido ({size}). Escolha entre: {', '.join(shirt.available_sizes)}.")

    if qty >= shirt.tier_threshold:
        unit_price = shirt.price_tiered
        rule = f"Preço atacado (a partir de {shirt.tier_threshold} un: R$ {shirt.price_tiered:.2f}/un)".replace(".", ",")
    else:
        unit_price = shirt.price_single
        rule = f"Preço unitário padrão (1 a {shirt.tier_threshold - 1} un: R$ {shirt.price_single:.2f}/un)".replace(".", ",")

    total = (Decimal(qty) * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    return ShirtQuote(
        shirt=shirt,
        color=color,
        size=size,
        quantity=qty,
        unit_price=unit_price,
        total=total,
        pricing_rule=rule,
    )


def calculate_service_quote(*, service_code: str, quantity: int | str = 1) -> ServiceQuote:
    service = SERVICES.get(service_code)
    if not service:
        raise CalculatorValidationError("Selecione um serviço válido.")
    qty = _as_quantity(quantity)
    unit_price = service.unit_price
    total = (Decimal(qty) * unit_price).quantize(MONEY_CENT, rounding=ROUND_HALF_UP)
    return ServiceQuote(
        service=service,
        quantity=qty,
        unit_price=unit_price,
        total=total,
        pricing_rule=f"Valor fixo de R$ {unit_price:.2f}/un".replace(".", ","),
    )

