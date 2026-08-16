from __future__ import annotations

import urllib.parse
from decimal import Decimal
from django.utils import timezone
from apps.orders.models import Order, OrderItem


def format_whatsapp_phone(phone_raw: str | None) -> str:
    """Format phone number with country code 55 for WhatsApp wa.me links."""
    clean = "".join(filter(str.isdigit, phone_raw or ""))
    if not clean:
        return ""
    if not clean.startswith("55") and len(clean) in (10, 11):
        clean = f"55{clean}"
    return clean


def format_money_br(val: Decimal | float | int | None) -> str:
    if val is None:
        return "0,00"
    return f"{Decimal(str(val)):.2f}".replace(".", ",")


def get_service_name_and_measures(order: Order) -> tuple[str, str, str]:
    """
    Extract summary service name, measurements, and meter price from order items.
    Fallback to description if items are not present.
    """
    items = list(order.items.all())
    material_items = [item for item in items if item.kind == OrderItem.Kind.MATERIAL]
    product_items = [item for item in items if item.kind == OrderItem.Kind.PRODUCT]
    service_items = [item for item in items if item.kind == OrderItem.Kind.SERVICE]

    # 1. Service name
    if material_items:
        names = [item.material_name for item in material_items]
        service_name = " / ".join(names)
    elif product_items:
        names = [item.material_name for item in product_items]
        service_name = " / ".join(names)
    elif service_items:
        names = [item.material_name for item in service_items]
        service_name = " / ".join(names)
    else:
        service_name = order.description.split("\n")[0][:60] if order.description else "Serviços Gráficos"

    # 2. Measures
    measures_parts = []
    for item in material_items:
        if item.art_width_cm and item.art_height_cm:
            measures_parts.append(
                f"{item.art_width_cm:.1f}x{item.art_height_cm:.1f} cm ({item.art_quantity or 1} un · total {item.billing_quantity:.2f} m)"
            )
        elif item.billing_quantity:
            measures_parts.append(f"{item.billing_quantity:.2f} metros")
    for item in product_items:
        detail = f"{item.art_quantity or item.billing_quantity:.0f} un"
        if item.product_color or item.product_size:
            detail += f" ({item.product_color} / Tam: {item.product_size})"
        measures_parts.append(f"{item.material_name}: {detail}")
    for item in service_items:
        measures_parts.append(f"{item.material_name} ({item.art_quantity or item.billing_quantity:.0f} un)")

    if measures_parts:
        measures = "\n   • " + "\n   • ".join(measures_parts)
    else:
        measures = "Conforme arte aprovada / especificações"

    # 3. Meter price (or unit price of primary material)
    if material_items:
        unit_prices = [format_money_br(item.unit_price) for item in material_items]
        valor_metro = " / R$ ".join(unit_prices)
    else:
        valor_metro = "Sob consulta / Tabela padrão"

    return service_name, measures, valor_metro


def build_quote_whatsapp_message(order: Order, public_quote_url: str = "") -> str:
    """Template 1: Orçamento Completo."""
    service_name, measures, valor_metro = get_service_name_and_measures(order)
    valor_total = format_money_br(order.total_amount)

    if order.due_at:
        prazo = timezone.localtime(order.due_at).strftime("%d/%m/%Y às %H:%M")
    else:
        prazo = "A combinar com nossa equipe"

    link_part = f"\n🔗 Visualize e aprove seu orçamento:\n{public_quote_url}\n" if public_quote_url else ""

    message = (
        f"🍀 PRINT FORNECE\n"
        f"Segue o orçamento para {service_name}:\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📏 Medida: {measures}\n\n"
        f"💰 Valor do metro: R$ {valor_metro}\n\n"
        f"🟢 TOTAL: R$ {valor_total} ✅\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⏰ Prazo: {prazo}\n\n"
        f"💳 Pagamento: PIX ou Cartão (crédito/débito via link){link_part}\n"
        f"⚠️ Importante:\n"
        f"• A produção inicia mediante a confirmação do pagamento\n"
        f"• Não realizamos reimpressão de arte já aprovada ou material cortado\n"
        f"• Confira todos os detalhes antes de confirmar\n\n"
        f"Ficou alguma dúvida? É só falar! 😊"
    )
    return message


def build_ready_whatsapp_message(order: Order) -> str:
    """Template 2: Pronto para Retirada."""
    items = list(order.items.all())
    if items:
        item_names = [f"• {i.material_name} ({i.billing_quantity} {i.billing_unit})" for i in items]
        resumo_itens = "\n" + "\n".join(item_names)
    else:
        resumo_itens = f"\n• {order.description[:80]}"

    valor_total = format_money_br(order.total_amount)

    message = (
        f"🍀 PRINT FORNECE\n"
        f"Olá, {order.client_name}! 👋\n"
        f"Seu pedido #{order.number} está *PRONTO PARA RETIRADA*! 🎉\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📦 Itens:{resumo_itens}\n"
        f"🟢 TOTAL: R$ {valor_total}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📍 Retirada: Loja Print Fornece\n"
        f"⏰ Horário: Segunda a Sexta, das 08h às 18h\n\n"
        f"Qualquer dúvida estamos à disposição! 😊"
    )
    return message


def build_delivered_whatsapp_message(order: Order) -> str:
    """Template 3: Material Entregue."""
    items = list(order.items.all())
    if items:
        item_names = [f"• {i.material_name} ({i.billing_quantity} {i.billing_unit})" for i in items]
        resumo_itens = "\n" + "\n".join(item_names)
    else:
        resumo_itens = f"\n• {order.description[:80]}"

    valor_total = format_money_br(order.total_amount)

    message = (
        f"🍀 PRINT FORNECE\n"
        f"Olá, {order.client_name}! 👋\n"
        f"Confirmamos a *ENTREGA* do seu pedido #{order.number}! ✅\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📦 Itens entregues:{resumo_itens}\n"
        f"🟢 Total: R$ {valor_total}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Muito obrigado pela confiança e preferência!\n"
        f"Precisando de novos materiais ou produtos, é só nos chamar por aqui! 😊🍀"
    )
    return message


def get_whatsapp_share_links(order: Order, host: str = "") -> dict[str, str]:
    """Return wa.me URLs for each of the 3 stages."""
    phone = format_whatsapp_phone(order.client_whatsapp)
    if not phone:
        return {"phone": "", "quote_url": "#", "ready_url": "#", "delivered_url": "#"}

    public_quote_url = f"{host}/orders/quote/{order.quote_token}/" if host else ""

    quote_msg = build_quote_whatsapp_message(order, public_quote_url)
    ready_msg = build_ready_whatsapp_message(order)
    delivered_msg = build_delivered_whatsapp_message(order)

    return {
        "phone": phone,
        "quote_message": quote_msg,
        "quote_url": f"https://wa.me/{phone}?text={urllib.parse.quote(quote_msg)}",
        "ready_message": ready_msg,
        "ready_url": f"https://wa.me/{phone}?text={urllib.parse.quote(ready_msg)}",
        "delivered_message": delivered_msg,
        "delivered_url": f"https://wa.me/{phone}?text={urllib.parse.quote(delivered_msg)}",
    }
