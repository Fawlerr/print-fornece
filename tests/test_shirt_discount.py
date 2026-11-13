"""A1 — desconto por camisa (6+ do mesmo modelo, cor e tamanho), em cima do atacado."""
from __future__ import annotations

import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.business.models import BusinessSettings
from apps.business.services import shirt_discount_rule
from apps.orders.calculator import (
    ShirtDiscountRule,
    apply_shirt_volume_discount,
    calculate_service_quote,
    calculate_shirt_quote,
)
from apps.orders.models import Order, OrderHistory, OrderItem

ALGODAO = "camisa_algodao_menegotti"
DRY_FIT = "camisa_dry_fit_grao_arroz"
ALL_MODELS = frozenset({ALGODAO, DRY_FIT})


def fixed_rule(value="3.00", min_quantity=6, codes=ALL_MODELS):
    return ShirtDiscountRule(enabled=True, kind="fixo", value=Decimal(value), min_quantity=min_quantity, eligible_codes=codes)


def shirt(size="M", qty=6, color="Preta", code=ALGODAO):
    return calculate_shirt_quote(shirt_code=code, color=color, size=size, quantity=qty)


class ShirtDiscountRuleTests(TestCase):
    """Regra pura da calculadora (sem banco)."""

    def test_five_units_keep_only_wholesale_price(self):
        quotes, _ = apply_shirt_volume_discount([shirt(qty=5)], fixed_rule())
        line = quotes[0]
        self.assertEqual(line.unit_price, Decimal("25.00"))  # atacado, como hoje
        self.assertEqual(line.discount_per_unit, Decimal("0.00"))
        self.assertEqual(line.total, Decimal("125.00"))

    def test_six_units_same_size_get_wholesale_plus_discount(self):
        quotes, hints = apply_shirt_volume_discount([shirt(qty=6)], fixed_rule("3.00"))
        line = quotes[0]
        self.assertEqual(line.table_unit_price, Decimal("28.00"))
        self.assertEqual(line.wholesale_unit_price, Decimal("25.00"))
        self.assertEqual(line.discount_per_unit, Decimal("3.00"))
        self.assertEqual(line.unit_price, Decimal("22.00"))
        self.assertEqual(line.total, Decimal("132.00"))
        self.assertEqual(line.discount_total, Decimal("18.00"))
        self.assertEqual(hints[0]["status"], "aplicado")

    def test_six_plus_with_mixed_sizes_has_no_discount(self):
        quotes, hints = apply_shirt_volume_discount([shirt("M", 5), shirt("G", 3)], fixed_rule())
        self.assertTrue(all(q.discount_per_unit == 0 for q in quotes))
        self.assertEqual(quotes[0].unit_price, Decimal("25.00"))  # M: atacado (5 un)
        self.assertEqual(quotes[1].unit_price, Decimal("28.00"))  # G: tabela (3 un)
        self.assertEqual(hints[0]["status"], "tamanhos_misturados")

    def test_different_colors_are_different_groups(self):
        quotes, hints = apply_shirt_volume_discount([shirt(color="Preta", qty=4), shirt(color="Branca", qty=4)], fixed_rule())
        self.assertTrue(all(q.discount_per_unit == 0 for q in quotes))
        self.assertEqual({h["status"] for h in hints}, {"faltam"})
        self.assertIn("mais 2 unidades", hints[0]["message"])

    def test_changing_a_size_removes_the_discount(self):
        with_discount, _ = apply_shirt_volume_discount([shirt("M", 8)], fixed_rule())
        self.assertEqual(with_discount[0].discount_per_unit, Decimal("3.00"))
        # Alguém troca 3 camisas para G: o desconto some na hora, inclusive da linha que já tinha.
        changed = [with_discount[0], shirt("G", 3)]
        changed[0] = calculate_shirt_quote(shirt_code=ALGODAO, color="Preta", size="M", quantity=5)
        recalculated, _ = apply_shirt_volume_discount(changed, fixed_rule())
        self.assertTrue(all(q.discount_per_unit == 0 for q in recalculated))
        # Reaplicar a regra sobre um item que já tinha desconto também limpa o desconto anterior.
        stale, _ = apply_shirt_volume_discount([with_discount[0], shirt("G", 1)], fixed_rule())
        self.assertEqual(stale[0].discount_per_unit, Decimal("0.00"))
        self.assertEqual(stale[0].unit_price, Decimal("25.00"))

    def test_disabled_or_zero_rule_changes_nothing(self):
        for rule in (ShirtDiscountRule(), ShirtDiscountRule(enabled=True, value=Decimal("0"), eligible_codes=ALL_MODELS)):
            quotes, hints = apply_shirt_volume_discount([shirt(qty=10)], rule)
            self.assertEqual(quotes[0].unit_price, Decimal("25.00"))
            self.assertEqual(hints, [])

    def test_only_selected_models_participate(self):
        rule = fixed_rule(codes=frozenset({DRY_FIT}))
        quotes, _ = apply_shirt_volume_discount([shirt(qty=6, code=ALGODAO), shirt(qty=6, code=DRY_FIT)], rule)
        self.assertEqual(quotes[0].discount_per_unit, Decimal("0.00"))
        self.assertEqual(quotes[1].discount_per_unit, Decimal("3.00"))
        self.assertEqual(quotes[1].unit_price, Decimal("17.00"))  # Dry Fit atacado 20 - 3

    def test_percent_discount_rounds_cents_per_unit(self):
        # 7% de R$ 25,00 = 1,75 ; 3,33% de 25,00 = 0,8325 -> 0,83 (arredonda por unidade antes de multiplicar)
        rule = ShirtDiscountRule(enabled=True, kind="percentual", value=Decimal("3.33"), min_quantity=6, eligible_codes=ALL_MODELS)
        quotes, _ = apply_shirt_volume_discount([shirt(qty=7)], rule)
        line = quotes[0]
        self.assertEqual(line.discount_per_unit, Decimal("0.83"))
        self.assertEqual(line.unit_price, Decimal("24.17"))
        self.assertEqual(line.total, Decimal("169.19"))
        self.assertEqual(line.discount_total, Decimal("5.81"))
        self.assertEqual(line.total + line.discount_total, Decimal("175.00"))

    def test_fixed_discount_never_makes_price_negative(self):
        quotes, _ = apply_shirt_volume_discount([shirt(qty=6)], fixed_rule("999.00"))
        self.assertEqual(quotes[0].unit_price, Decimal("0.00"))

    def test_non_shirt_items_are_untouched(self):
        service = calculate_service_quote(service_code="formato_halftone", quantity=1)
        quotes, _ = apply_shirt_volume_discount([service, shirt(qty=6)], fixed_rule())
        self.assertIs(quotes[0], service)


class ShirtDiscountFlowTests(TestCase):
    """Fluxo completo: configuração no banco, criação, edição e telas."""

    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", name="Admin", password="strong-password", role=User.Role.ADMINISTRATOR)
        self.employee = User.objects.create_user(email="func@example.com", name="Func", password="strong-password", role=User.Role.EMPLOYEE)
        config = BusinessSettings.load()
        config.shirt_discount_enabled = True
        config.shirt_discount_value = Decimal("3.00")
        config.save()

    def _payload(self, *lines):
        return json.dumps({"items": [
            {"kind": "produto", "material_code": code, "product_color": color, "product_size": size, "quantity": qty}
            for code, color, size, qty in lines
        ]})

    def _create(self, payload, total="0,00"):
        self.client.force_login(self.employee)
        response = self.client.post(reverse("orders:create"), {
            "client_name": "Cliente Camisa", "client_whatsapp": "84999999999", "description": "Camisas",
            "total_amount": total, "payment_status": Order.PaymentStatus.UNPAID, "paid_amount": "0,00",
            "priority": Order.Priority.NORMAL, "calculation_payload": payload,
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context.get("form").errors)
        return Order.objects.get(client_name="Cliente Camisa")

    def test_discount_is_off_until_value_is_defined(self):
        config = BusinessSettings.load()
        config.shirt_discount_enabled = False
        config.shirt_discount_value = Decimal("0")
        config.save()
        self.assertFalse(shirt_discount_rule().enabled)
        self.assertEqual(BusinessSettings.objects.count(), 1)

    def test_backend_applies_discount_and_records_history(self):
        order = self._create(self._payload((ALGODAO, "Preta", "M", 6)), total="132,00")
        item = OrderItem.objects.get(order=order, kind=OrderItem.Kind.PRODUCT)
        self.assertEqual(item.unit_price, Decimal("22.00"))
        self.assertEqual(item.discount_per_unit, Decimal("3.00"))
        self.assertEqual(item.discount_total, Decimal("18.00"))
        self.assertEqual(item.line_total, Decimal("132.00"))
        self.assertEqual(item.calculation_snapshot["table_unit_price"], "28.00")
        self.assertEqual(item.calculation_snapshot["wholesale_unit_price"], "25.00")
        self.assertFalse(OrderItem.objects.filter(order=order, kind=OrderItem.Kind.ADJUSTMENT).exists())
        self.assertTrue(OrderHistory.objects.filter(order=order, action="desconto_camisa").exists())

    def test_browser_cannot_inject_a_discount(self):
        payload = json.dumps({"items": [{
            "kind": "produto", "material_code": ALGODAO, "product_color": "Preta", "product_size": "M", "quantity": 5,
            "unit_price": "1.00", "discount_per_unit": "20.00", "total": "5.00",
        }]})
        order = self._create(payload, total="125,00")
        item = OrderItem.objects.get(order=order, kind=OrderItem.Kind.PRODUCT)
        self.assertEqual(item.unit_price, Decimal("25.00"))
        self.assertEqual(item.discount_total, Decimal("0.00"))

    def test_cart_endpoint_recalculates_and_returns_hints(self):
        self.client.force_login(self.employee)
        url = reverse("orders:calculate_cart")
        body = {"items": json.loads(self._payload((ALGODAO, "Preta", "M", 5)))["items"]}
        data = self.client.post(url, json.dumps(body), content_type="application/json").json()
        self.assertEqual(data["discount_total"], "0.00")
        self.assertEqual(data["hints"][0]["status"], "faltam")
        self.assertIn("mais 1 unidade", data["hints"][0]["message"])
        body["items"][0]["quantity"] = 6
        data = self.client.post(url, json.dumps(body), content_type="application/json").json()
        self.assertEqual(data["discount_total"], "18.00")
        self.assertEqual(data["items"][0]["unit_price"], "22.00")

    def test_cart_endpoint_requires_login(self):
        response = self.client.post(reverse("orders:calculate_cart"), "{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_old_order_is_not_recalculated_when_items_did_not_change(self):
        # Pedido "antigo": camisas gravadas a R$ 25,00, sem desconto (antes da regra existir).
        order = Order.objects.create(number="0900", client_name="Antigo", client_whatsapp="84999999999", total_amount=Decimal("200.00"), created_by=self.admin)
        OrderItem.objects.create(
            order=order, position=1, kind=OrderItem.Kind.PRODUCT, material_code=ALGODAO, material_name="Camisa 100% Algodão (Menegotti)",
            category="Camisas", product_color="Preta", product_size="M", art_quantity=8, billing_quantity=Decimal("8"),
            billing_unit="Unidade", unit_price=Decimal("25.00"), line_total=Decimal("200.00"), pricing_rule="Preço atacado",
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("orders:edit", args=[order.pk]), {
            "client_name": "Antigo renomeado", "client_whatsapp": "84999999999", "description": "", "total_amount": "200,00",
            "payment_status": Order.PaymentStatus.UNPAID, "paid_amount": "0,00", "priority": Order.Priority.NORMAL,
            "calculation_payload": self._payload((ALGODAO, "Preta", "M", 8)),
        })
        self.assertEqual(response.status_code, 302)
        item = OrderItem.objects.get(order=order, kind=OrderItem.Kind.PRODUCT)
        self.assertEqual(item.unit_price, Decimal("25.00"))
        self.assertEqual(item.discount_total, Decimal("0.00"))
        self.assertFalse(OrderItem.objects.filter(order=order, kind=OrderItem.Kind.ADJUSTMENT).exists())

    def test_old_order_is_recalculated_when_an_item_changes(self):
        order = Order.objects.create(number="0901", client_name="Antigo 2", client_whatsapp="84999999999", total_amount=Decimal("200.00"), created_by=self.admin)
        OrderItem.objects.create(
            order=order, position=1, kind=OrderItem.Kind.PRODUCT, material_code=ALGODAO, material_name="Camisa 100% Algodão (Menegotti)",
            category="Camisas", product_color="Preta", product_size="M", art_quantity=8, billing_quantity=Decimal("8"),
            billing_unit="Unidade", unit_price=Decimal("25.00"), line_total=Decimal("200.00"), pricing_rule="Preço atacado",
        )
        self.client.force_login(self.admin)
        self.client.post(reverse("orders:edit", args=[order.pk]), {
            "client_name": "Antigo 2", "client_whatsapp": "84999999999", "description": "", "total_amount": "198,00",
            "payment_status": Order.PaymentStatus.UNPAID, "paid_amount": "0,00", "priority": Order.Priority.NORMAL,
            "calculation_payload": self._payload((ALGODAO, "Preta", "M", 9)),
        })
        item = OrderItem.objects.get(order=order, kind=OrderItem.Kind.PRODUCT)
        self.assertEqual(item.art_quantity, 9)
        self.assertEqual(item.unit_price, Decimal("22.00"))
        self.assertEqual(item.line_total, Decimal("198.00"))

    def test_discount_is_shown_on_detail_card_public_page_and_whatsapp(self):
        from apps.notifications.whatsapp import build_quote_whatsapp_message
        order = self._create(self._payload((ALGODAO, "Preta", "M", 6)), total="132,00")
        self.client.force_login(self.admin)
        detail = self.client.get(reverse("production:detail", args=[order.pk])).content.decode()
        self.assertIn("Desconto −R$ 3,00/camisa", detail)
        self.assertIn("Atacado R$ 25,00", detail)
        self.assertIn("Tabela R$ 28,00", detail)
        kanban = self.client.get(reverse("production:kanban")).content.decode()
        self.assertIn("Desc. camisas −R$ 18,00", kanban)
        public = self.client.get(reverse("orders:public_quote", args=[order.quote_token])).content.decode()
        self.assertIn("Desconto por camisa", public)
        self.assertIn("-R$ 18,00", build_quote_whatsapp_message(order))
        pdf = self.client.get(reverse("orders:download_receipt", args=[order.pk]))
        self.assertEqual(pdf.status_code, 200)

    def test_settings_page_is_admin_only_and_validates(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("business:settings")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("business:settings")).status_code, 200)
        response = self.client.post(reverse("business:settings"), {
            "section": "desconto_camisa",
            "desconto_camisa-shirt_discount_enabled": "on",
            "desconto_camisa-shirt_discount_type": "fixo",
            "desconto_camisa-shirt_discount_value": "0",
            "desconto_camisa-shirt_discount_min_quantity": "6",
            "desconto_camisa-shirt_discount_models": [ALGODAO],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Defina o valor do desconto antes de ativá-lo.")
        response = self.client.post(reverse("business:settings"), {
            "section": "desconto_camisa",
            "desconto_camisa-shirt_discount_enabled": "on",
            "desconto_camisa-shirt_discount_type": "fixo",
            "desconto_camisa-shirt_discount_value": "2.50",
            "desconto_camisa-shirt_discount_min_quantity": "6",
            "desconto_camisa-shirt_discount_models": [ALGODAO],
        })
        self.assertEqual(response.status_code, 302)
        config = BusinessSettings.load()
        self.assertEqual(config.shirt_discount_value, Decimal("2.50"))
        self.assertEqual(config.shirt_discount_models, [ALGODAO])
        self.assertEqual(config.updated_by, self.admin)
