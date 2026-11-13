"""A4 — impressão automática da nota quando o pedido entra em "Pagamento confirmado"."""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.business.models import BusinessSettings
from apps.orders.models import Order, OrderHistory, OrderPrintLog
from apps.production.services import move_order_stage


class ReceiptPrintTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", name="Admin", password="strong-password", role=User.Role.ADMINISTRATOR)
        self.employee = User.objects.create_user(email="func@example.com", name="Ana", password="strong-password", role=User.Role.EMPLOYEE)
        self.order = Order.objects.create(
            number="0500", client_name="Cliente Nota", client_whatsapp="84999999999", total_amount=Decimal("80.00"),
            paid_amount=Decimal("80.00"), payment_status=Order.PaymentStatus.PAID, stage=Order.Stage.AWAITING_PAYMENT,
            created_by=self.admin,
        )
        self.client.force_login(self.employee)

    def _claim(self, order=None, device="Balcão"):
        order = order or self.order
        return self.client.post(reverse("orders:receipt_claim", args=[order.pk]), json.dumps({"device": device}), content_type="application/json")

    def test_entering_payment_confirmed_requests_print(self):
        self.assertIsNone(self.order.receipt_print_requested_at)
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.PAYMENT_CONFIRMED, actor=self.employee)
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.receipt_print_requested_at)

    def test_other_stages_do_not_request_print(self):
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.NEW, actor=self.employee)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.receipt_print_requested_at)

    def test_payment_confirmed_without_screen_goes_to_the_station_queue(self):
        # Ex.: aprovação do cliente com o pedido já pago (nenhum funcionário na tela).
        self.order.stage = Order.Stage.NEW
        self.order.save()
        self.client.logout()
        self.client.post(reverse("orders:approve_quote", args=[self.order.quote_token]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, Order.Stage.PAYMENT_CONFIRMED)
        self.client.force_login(self.employee)
        queue = self.client.get(reverse("orders:receipt_print_queue")).json()
        self.assertEqual([o["id"] for o in queue["orders"]], [self.order.pk])

    def test_claim_prints_once_and_logs(self):
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.PAYMENT_CONFIRMED, actor=self.employee)
        first = self._claim().json()
        self.assertTrue(first["claimed"])
        second = self._claim().json()
        self.assertFalse(second["claimed"])
        self.assertTrue(second["already_printed"])
        self.assertEqual(second["printed_by"], "Ana")
        self.assertEqual(OrderPrintLog.objects.filter(order=self.order).count(), 1)
        log = OrderPrintLog.objects.get(order=self.order)
        self.assertEqual((log.source, log.user, log.device), (OrderPrintLog.Source.AUTOMATIC, self.employee, "Balcão"))
        self.assertTrue(OrderHistory.objects.filter(order=self.order, action="impressao_nota").exists())
        # Já impressa: sai da fila da estação.
        self.assertEqual(self.client.get(reverse("orders:receipt_print_queue")).json()["orders"], [])

    def test_moving_out_and_back_does_not_reprint_automatically(self):
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.PAYMENT_CONFIRMED, actor=self.employee)
        self.assertTrue(self._claim().json()["claimed"])
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.AWAITING_PAYMENT, actor=self.employee)
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.PAYMENT_CONFIRMED, actor=self.employee)
        again = self._claim().json()
        self.assertFalse(again["claimed"])
        self.assertTrue(again["already_printed"])  # a tela pergunta antes de imprimir de novo
        self.assertEqual(self.client.get(reverse("orders:receipt_print_queue")).json()["orders"], [])

    def test_reprint_is_always_allowed_and_logged(self):
        response = self.client.post(reverse("orders:receipt_log", args=[self.order.pk]), json.dumps({"source": "reimpressao", "device": "Celular"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        log = OrderPrintLog.objects.get(order=self.order)
        self.assertEqual(log.source, OrderPrintLog.Source.REPRINT)
        self.assertEqual(log.user, self.employee)

    def test_global_switch_off_disables_automatic_printing(self):
        config = BusinessSettings.load()
        config.auto_print_enabled = False
        config.save()
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.PAYMENT_CONFIRMED, actor=self.employee)
        self.assertFalse(self._claim().json()["claimed"])
        self.assertEqual(self.client.get(reverse("orders:receipt_print_queue")).json()["orders"], [])

    def test_old_requests_are_not_printed_by_a_new_station(self):
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.PAYMENT_CONFIRMED, actor=self.employee)
        Order.objects.filter(pk=self.order.pk).update(receipt_print_requested_at=timezone.now() - timedelta(days=3))
        self.assertEqual(self.client.get(reverse("orders:receipt_print_queue")).json()["orders"], [])

    def test_endpoints_require_login_and_post(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("orders:receipt_print", args=[self.order.pk])).status_code, 302)
        self.assertIn(self._claim().status_code, (302, 403))
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("orders:receipt_claim", args=[self.order.pk])).status_code, 405)

    def test_receipt_page_is_print_ready(self):
        response = self.client.get(reverse("orders:receipt_print", args=[self.order.pk]), {"autoprint": "1"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("size: 80mm auto", html)
        self.assertIn("@media print", html)
        self.assertIn("Cliente Nota", html)
        self.assertIn("Venda (nº: 0500)", html)
        self.assertIn("window.print()", html)
        self.assertNotIn("sidebar", html)
        config = BusinessSettings.load()
        config.receipt_paper_width = 58
        config.save()
        self.assertIn("size: 58mm auto", self.client.get(reverse("orders:receipt_print", args=[self.order.pk])).content.decode())

    def test_reprint_buttons_on_card_and_detail(self):
        move_order_stage(order_id=self.order.pk, new_stage=Order.Stage.PAYMENT_CONFIRMED, actor=self.employee)
        kanban = self.client.get(reverse("production:kanban")).content.decode()
        self.assertIn(f'data-reprint-order="{self.order.pk}"', kanban)
        detail = self.client.get(reverse("production:detail", args=[self.order.pk])).content.decode()
        self.assertIn(f'data-reprint-order="{self.order.pk}"', detail)
        self.assertIn("Reimprimir nota", detail)

    def test_settings_page_has_print_station_toggle(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("business:settings"))
        self.assertContains(response, "Este computador é uma estação de impressão")
        response = self.client.post(reverse("business:settings"), {
            "section": "impressao", "impressao-auto_print_enabled": "on", "impressao-receipt_paper_width": "58",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BusinessSettings.load().receipt_paper_width, 58)
