"""A5 — senha (PIN de gerente) obrigatória para cancelar pedidos."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.business.models import BusinessSettings
from apps.orders.models import Order, OrderHistory
from apps.production.models import CancellationAttempt
from apps.production.services import MAX_CANCEL_ATTEMPTS, cancel_order

PIN = "4821"


class CancellationPinTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", name="Gerente", password="strong-password", role=User.Role.ADMINISTRATOR)
        self.employee = User.objects.create_user(email="func@example.com", name="Ana", password="strong-password", role=User.Role.EMPLOYEE)
        self.order = Order.objects.create(number="0700", client_name="Cliente", client_whatsapp="84999999999", total_amount=Decimal("50"), created_by=self.admin)
        config = BusinessSettings.load()
        config.set_cancellation_pin(PIN, actor=self.admin)
        config.save()
        self.client.force_login(self.employee)

    def _post(self, pin=PIN, reason="Cliente desistiu do pedido"):
        return self.client.post(reverse("production:cancel", args=[self.order.pk]), {"cancellation_pin": pin, "cancellation_reason": reason})

    def test_pin_is_stored_hashed(self):
        config = BusinessSettings.load()
        self.assertTrue(config.cancellation_pin_hash)
        self.assertNotIn(PIN, config.cancellation_pin_hash)
        self.assertTrue(config.check_cancellation_pin(PIN))
        self.assertFalse(config.check_cancellation_pin("0000"))
        self.assertFalse(AuditEvent.objects.filter(after__icontains=PIN).exists())

    def test_correct_pin_cancels_and_records_who_authorized(self):
        response = self._post()
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, Order.Stage.CANCELLED)
        self.assertEqual(self.order.cancelled_by, self.employee)
        self.assertEqual(self.order.cancellation_reason, "Cliente desistiu do pedido")
        history = OrderHistory.objects.get(order=self.order, action="cancelamento")
        self.assertIn("Ana", history.description)
        self.assertIn("autorizado com a senha de gerente", history.description)
        self.assertIn("Cliente desistiu do pedido", history.description)
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())  # nunca apaga
        self.assertTrue(CancellationAttempt.objects.filter(order=self.order, user=self.employee, success=True).exists())

    def test_wrong_pin_does_not_cancel_and_is_recorded(self):
        response = self._post(pin="1111")
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.stage, Order.Stage.CANCELLED)
        self.assertEqual(CancellationAttempt.objects.filter(user=self.employee, success=False).count(), 1)
        self.assertContains(self.client.get(response["Location"]), "Senha de cancelamento incorreta")

    def test_endpoint_refuses_without_pin_even_if_called_directly(self):
        self.client.post(reverse("production:cancel", args=[self.order.pk]))
        self.client.post(reverse("production:cancel", args=[self.order.pk]), {"cancellation_reason": "Motivo qualquer"})
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.stage, Order.Stage.CANCELLED)

    def test_reason_is_required(self):
        self._post(reason="  ")
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.stage, Order.Stage.CANCELLED)
        with self.assertRaisesMessage(ValidationError, "motivo"):
            cancel_order(order_id=self.order.pk, actor=self.employee, reason="", pin=PIN)

    def test_lockout_after_too_many_wrong_attempts(self):
        for _ in range(MAX_CANCEL_ATTEMPTS):
            self._post(pin="0000")
        # Mesmo com a senha certa, fica bloqueado temporariamente.
        with self.assertRaisesMessage(ValidationError, "Muitas tentativas"):
            cancel_order(order_id=self.order.pk, actor=self.employee, reason="Motivo válido", pin=PIN)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.stage, Order.Stage.CANCELLED)
        # Outro usuário não é afetado pelo bloqueio da Ana.
        cancel_order(order_id=self.order.pk, actor=self.admin, reason="Motivo válido", pin=PIN)
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, Order.Stage.CANCELLED)

    def test_cancel_blocked_until_admin_defines_pin(self):
        config = BusinessSettings.load()
        config.cancellation_pin_hash = ""
        config.save()
        with self.assertRaisesMessage(ValidationError, "O administrador precisa definir a senha de cancelamento"):
            cancel_order(order_id=self.order.pk, actor=self.employee, reason="Motivo válido", pin="")
        detail = self.client.get(reverse("production:detail", args=[self.order.pk]))
        self.assertContains(detail, "O administrador precisa definir a senha de cancelamento")

    def test_restore_does_not_require_pin(self):
        cancel_order(order_id=self.order.pk, actor=self.employee, reason="Motivo válido", pin=PIN)
        self.client.force_login(self.admin)
        self.client.post(reverse("production:restore", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, Order.Stage.NEW)

    def test_admin_sets_pin_on_settings_page(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("business:settings"), {
            "section": "cancelamento", "cancelamento-new_pin": "9090", "cancelamento-confirm_pin": "9091",
        })
        self.assertContains(response, "As senhas não conferem.")
        response = self.client.post(reverse("business:settings"), {
            "section": "cancelamento", "cancelamento-new_pin": "9090", "cancelamento-confirm_pin": "9090",
        })
        self.assertEqual(response.status_code, 302)
        config = BusinessSettings.load()
        self.assertTrue(config.check_cancellation_pin("9090"))
        self.assertEqual(config.cancellation_pin_updated_by, self.admin)
        self.assertNotIn("9090", self.client.get(reverse("business:settings")).content.decode())

    def test_employee_cannot_change_pin(self):
        response = self.client.post(reverse("business:settings"), {
            "section": "cancelamento", "cancelamento-new_pin": "1234", "cancelamento-confirm_pin": "1234",
        })
        self.assertEqual(response.status_code, 403)
        self.assertTrue(BusinessSettings.load().check_cancellation_pin(PIN))
