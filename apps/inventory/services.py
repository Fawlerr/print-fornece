from __future__ import annotations

from decimal import Decimal
from django.db import transaction

from .models import SupplyItem, SupplyMovement


def deduct_order_stock(order, actor=None) -> list[SupplyMovement]:
    """
    Abate automaticamente o estoque de insumos de acordo com os itens do pedido.
    Abate:
    - Filmes de DTF Têxtil (em metros)
    - Filmes de DTF UV (em metros / rolos)
    - Camisetas (por modelo e tamanho)
    Obs.: Tintas não são abatidas por precisão de dosagem, conforme especificação.
    """
    movements: list[SupplyMovement] = []
    items = list(order.items.all()) if hasattr(order, "items") else []
    if not items:
        return movements

    textil_meters = Decimal("0.00")
    uv_meters = Decimal("0.00")
    shirts_to_deduct: list[tuple[str, str, str, Decimal]] = []  # (shirt_type, color, size, quantity)

    for item in items:
        mat_code = (item.material_code or "").lower()
        mat_name = (item.material_name or "").lower()
        kind = getattr(item, "kind", "")

        # DTF Têxtil
        if mat_code == "dtf_textil" or (kind == "material" and "uv" not in mat_code and "uv" not in mat_name):
            meters = Decimal("0.00")
            if item.calculation_snapshot and "film_used_m" in item.calculation_snapshot:
                meters = Decimal(str(item.calculation_snapshot["film_used_m"]))
            elif item.billing_unit.lower().startswith("metro"):
                meters = Decimal(str(item.billing_quantity))
            elif item.used_length_cm:
                meters = Decimal(str(item.used_length_cm)) / Decimal("100")
            textil_meters += meters

        # DTF UV
        elif mat_code == "dtf_uv" or "uv" in mat_code or "uv" in mat_name:
            meters = Decimal("0.00")
            if item.calculation_snapshot and "film_used_m" in item.calculation_snapshot:
                meters = Decimal(str(item.calculation_snapshot["film_used_m"]))
            elif item.billing_unit.lower().startswith("metro"):
                meters = Decimal(str(item.billing_quantity))
            elif item.used_length_cm:
                meters = Decimal(str(item.used_length_cm)) / Decimal("100")
            uv_meters += meters

        # Camisetas
        elif kind == "produto" or mat_code.startswith("camisa_") or "camisa" in mat_name or "camiseta" in mat_name:
            qty = Decimal(str(item.art_quantity if item.art_quantity else item.billing_quantity or 1))
            size = (item.product_size or "M").strip().upper()
            raw_color = (item.product_color or "").strip().lower()
            if "branc" in raw_color or "branc" in mat_name or "branc" in mat_code:
                color = "branca"
            else:
                color = "preta"

            shirt_type = "algodao" if "algodao" in mat_code or "algodão" in mat_name else "dry_fit"
            shirts_to_deduct.append((shirt_type, color, size, qty))

    with transaction.atomic():
        # 1. Abater Filme DTF Têxtil
        if textil_meters > Decimal("0.00"):
            filme_textil = SupplyItem.objects.filter(
                category=SupplyItem.Category.DTF_TEXTIL,
                name__icontains="filme",
            ).first()
            if not filme_textil:
                filme_textil = SupplyItem.objects.filter(
                    category=SupplyItem.Category.DTF_TEXTIL,
                    unit=SupplyItem.Unit.METER,
                ).first()

            if filme_textil:
                prev_qty = filme_textil.quantity
                filme_textil.quantity = max(Decimal("0.00"), filme_textil.quantity - textil_meters)
                filme_textil.save(update_fields=["quantity", "updated_at"])

                mov = SupplyMovement.objects.create(
                    item=filme_textil,
                    movement_type=SupplyMovement.MovementType.OUTPUT,
                    quantity=textil_meters,
                    previous_quantity=prev_qty,
                    new_quantity=filme_textil.quantity,
                    description=f"Consumo Pedido #{order.number} ({textil_meters:.2f}m)",
                    user=actor,
                )
                movements.append(mov)

        # 2. Abater Filme DTF UV
        if uv_meters > Decimal("0.00"):
            filmes_uv = SupplyItem.objects.filter(
                category=SupplyItem.Category.DTF_UV,
                name__icontains="filme",
            )
            if not filmes_uv.exists():
                filmes_uv = SupplyItem.objects.filter(category=SupplyItem.Category.DTF_UV)

            for filme_uv in filmes_uv:
                prev_qty = filme_uv.quantity
                # Se for por metro abate a metragem, se for por rolo/unidade proporcional
                qty_deduct = uv_meters
                filme_uv.quantity = max(Decimal("0.00"), filme_uv.quantity - qty_deduct)
                filme_uv.save(update_fields=["quantity", "updated_at"])

                mov = SupplyMovement.objects.create(
                    item=filme_uv,
                    movement_type=SupplyMovement.MovementType.OUTPUT,
                    quantity=qty_deduct,
                    previous_quantity=prev_qty,
                    new_quantity=filme_uv.quantity,
                    description=f"Consumo Pedido #{order.number} ({uv_meters:.2f}m)",
                    user=actor,
                )
                movements.append(mov)

        # 3. Abater Camisetas
        for shirt_type, color, size, qty in shirts_to_deduct:
            type_keyword = "Algodão" if shirt_type == "algodao" else "Dry Fit"
            color_keyword = "Branca" if color == "branca" else "Preta"

            shirt_item = SupplyItem.objects.filter(
                category=SupplyItem.Category.SHIRTS,
                name__icontains=type_keyword,
            ).filter(
                name__icontains=color_keyword,
            ).filter(
                name__icontains=f"Tam. {size}",
            ).first()

            if not shirt_item:
                shirt_item = SupplyItem.objects.filter(
                    category=SupplyItem.Category.SHIRTS,
                    name__icontains=type_keyword,
                ).filter(
                    name__icontains=color_keyword,
                ).filter(
                    name__icontains=size,
                ).first()

            if not shirt_item:
                shirt_item = SupplyItem.objects.filter(
                    category=SupplyItem.Category.SHIRTS,
                    name__icontains=type_keyword,
                ).filter(
                    name__icontains=size,
                ).first()

            if shirt_item:
                prev_qty = shirt_item.quantity
                shirt_item.quantity = max(Decimal("0.00"), shirt_item.quantity - qty)
                shirt_item.save(update_fields=["quantity", "updated_at"])

                mov = SupplyMovement.objects.create(
                    item=shirt_item,
                    movement_type=SupplyMovement.MovementType.OUTPUT,
                    quantity=qty,
                    previous_quantity=prev_qty,
                    new_quantity=shirt_item.quantity,
                    description=f"Consumo Pedido #{order.number} ({int(qty)} un - {shirt_item.name})",
                    user=actor,
                )
                movements.append(mov)

    return movements
