from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import check_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.expenses.models import Expense
from apps.notifications.models import Notification
from apps.orders.legacy_import import LegacyImporter, legacy_link
from apps.orders.models import Order, OrderAttachment, OrderHistory, OrderNote, OrderStageHistory


class FakeCursor:
    def __init__(self, tables):
        self.tables = tables
        self.rows = []
        self.offset = 0

    def execute(self, query, params=None):
        if query.startswith("SHOW TABLES"):
            self.rows = [{"Tables_in_legacy": name} for name in self.tables]
        elif query.startswith("SELECT * FROM"):
            name = query.split("`")[1]
            self.rows = list(self.tables.get(name, []))
        self.offset = 0

    def fetchall(self):
        return self.rows

    def fetchmany(self, size):
        batch = self.rows[self.offset:self.offset + size]
        self.offset += len(batch)
        return batch


class FakeLegacyConnection:
    def __init__(self, tables):
        self.tables = tables

    def cursor(self):
        return FakeCursor(self.tables)


class PrintForneceTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com", name="Admin", password="strong-password", role=User.Role.ADMINISTRATOR,
        )
        self.employee = User.objects.create_user(
            email="employee@example.com", name="Funcionária", password="strong-password", role=User.Role.EMPLOYEE,
        )
        self.order = Order.objects.create(
            number="PF-TEST-0001", client_name="Cliente", client_whatsapp="84999999999", description="Pedido de teste",
            total_amount=Decimal("100.00"), paid_amount=Decimal("0"), created_by=self.admin,
        )

    def login_as(self, user):
        self.assertTrue(self.client.login(username=user.email, password="strong-password"))

    def test_login_logout_and_force_password_change(self):
        response = self.client.post(reverse("accounts:login"), {"email": self.admin.email, "password": "strong-password"})
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))
        self.admin.force_password_change = True
        self.admin.save()
        self.login_as(self.admin)
        response = self.client.get(reverse("production:kanban"))
        self.assertRedirects(response, reverse("accounts:change_password"))

    def test_employee_is_blocked_from_administrative_data(self):
        self.login_as(self.employee)
        for url in (reverse("dashboard:index"), reverse("expenses:list"), reverse("reports:index"), reverse("accounts:user_list")):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("production:kanban")).status_code, 200)

    def test_admin_can_create_order_and_employee_cannot_modify_financial_data(self):
        self.login_as(self.admin)
        response = self.client.post(reverse("orders:create"), {
            "client_name": "Nova Cliente", "client_whatsapp": "(84) 99999-9999", "description": "Descrição válida",
            "total_amount": "50,00", "payment_status": Order.PaymentStatus.PARTIAL, "paid_amount": "25,00",
            "payment_method": Order.PaymentMethod.PIX, "priority": Order.Priority.URGENT, "internal_notes": "Interno",
        })
        self.assertEqual(response.status_code, 302)
        created = Order.objects.get(client_name="Nova Cliente")
        self.assertEqual(created.paid_amount, Decimal("25.00"))
        self.assertTrue(OrderHistory.objects.filter(order=created, action="criacao").exists())
        self.assertTrue(OrderStageHistory.objects.filter(order=created, new_stage=Order.Stage.NEW).exists())
        self.client.logout()
        self.login_as(self.employee)
        response = self.client.post(reverse("orders:edit", args=[created.pk]), {
            "client_name": "Nova Cliente", "client_whatsapp": "84999999999", "description": "Descrição válida",
            "total_amount": "999,00", "payment_status": Order.PaymentStatus.PAID, "paid_amount": "999,00",
            "payment_method": Order.PaymentMethod.CASH, "priority": Order.Priority.NORMAL, "internal_notes": "Alteração operacional",
        })
        self.assertEqual(response.status_code, 302)
        created.refresh_from_db()
        self.assertEqual(created.total_amount, Decimal("50.00"))
        self.assertEqual(created.payment_status, Order.PaymentStatus.PARTIAL)

    def test_kanban_move_creates_history_audit_and_notifications(self):
        self.login_as(self.employee)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("production:move_stage", args=[self.order.pk]),
                data='{"stage":"producao"}', content_type="application/json", HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, Order.Stage.PRODUCTION)
        self.assertTrue(OrderStageHistory.objects.filter(order=self.order, previous_stage=Order.Stage.NEW, new_stage=Order.Stage.PRODUCTION).exists())
        self.assertTrue(OrderHistory.objects.filter(order=self.order, action="mudanca_etapa").exists())
        self.assertTrue(AuditEvent.objects.filter(entity="pedido", entity_id=self.order.pk, action="mudanca_etapa").exists())
        self.assertTrue(Notification.objects.filter(title="Pedido atualizado").exists())

    def test_invalid_stage_and_finalization_are_blocked(self):
        self.login_as(self.employee)
        response = self.client.post(reverse("production:move_stage", args=[self.order.pk]), {"stage": Order.Stage.FINISHED})
        self.assertEqual(response.status_code, 422)
        response = self.client.post(reverse("production:finalize", args=[self.order.pk]))
        self.assertRedirects(response, reverse("production:detail", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, Order.Stage.NEW)

    def test_notes_attachments_and_protected_download(self):
        self.login_as(self.admin)
        response = self.client.post(reverse("production:add_note", args=[self.order.pk]), {"text": "Arte revisada"})
        self.assertRedirects(response, reverse("production:detail", args=[self.order.pk]))
        self.assertTrue(OrderNote.objects.filter(order=self.order, text="Arte revisada").exists())
        valid_pdf = SimpleUploadedFile("arte.pdf", b"%PDF-1.4\nconteudo", content_type="application/pdf")
        response = self.client.post(reverse("orders:edit", args=[self.order.pk]), {
            "client_name": self.order.client_name, "client_whatsapp": self.order.client_whatsapp, "description": self.order.description,
            "total_amount": "100,00", "payment_status": Order.PaymentStatus.UNPAID, "paid_amount": "0,00", "priority": Order.Priority.NORMAL,
            "attachments": valid_pdf,
        })
        self.assertEqual(response.status_code, 302)
        attachment = OrderAttachment.objects.get(order=self.order)
        response = self.client.get(reverse("orders:download_attachment", args=[self.order.pk, attachment.pk]))
        self.assertEqual(response.status_code, 200)
        invalid = SimpleUploadedFile("malicioso.jpg", b"not an image", content_type="image/jpeg")
        response = self.client.post(reverse("orders:edit", args=[self.order.pk]), {
            "client_name": self.order.client_name, "client_whatsapp": self.order.client_whatsapp, "description": self.order.description,
            "total_amount": "100,00", "payment_status": Order.PaymentStatus.UNPAID, "paid_amount": "0,00", "priority": Order.Priority.NORMAL,
            "attachments": invalid,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "conteúdo do arquivo")

    def test_cancel_and_restore_require_admin_for_restore(self):
        self.login_as(self.employee)
        self.client.post(reverse("production:cancel", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, Order.Stage.CANCELLED)
        response = self.client.post(reverse("production:restore", args=[self.order.pk]))
        self.assertEqual(response.status_code, 403)
        self.client.logout()
        self.login_as(self.admin)
        response = self.client.post(reverse("production:restore", args=[self.order.pk]))
        self.assertRedirects(response, reverse("production:detail", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.stage, Order.Stage.NEW)

    def test_expenses_reports_csv_dashboard_and_notifications(self):
        self.login_as(self.admin)
        response = self.client.post(reverse("expenses:create"), {
            "description": "Filme", "category": Expense.Category.MATERIAL, "amount": "25,50", "expense_date": timezone.localdate(), "note": "teste",
        })
        self.assertEqual(response.status_code, 302)
        self.order.payment_status = Order.PaymentStatus.PAID
        self.order.paid_amount = self.order.total_amount
        self.order.save()
        self.assertEqual(self.client.get(reverse("dashboard:index")).status_code, 200)
        report = self.client.get(reverse("reports:index"))
        self.assertEqual(report.status_code, 200)
        csv_response = self.client.get(reverse("reports:index") + "?export=csv")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response["Content-Type"])
        notification = Notification.objects.create(user=self.admin, title="Teste", message="Mensagem")
        self.assertJSONEqual(self.client.get(reverse("notifications:poll")).content, {"unread": 1})
        self.client.post(reverse("notifications:mark_read", args=[notification.pk]))
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_php_bcrypt_and_idempotent_legacy_import(self):
        legacy_hash = "$2y$10$d5n64iay03kxQzBh9dtqBuyzFBbVMZxmAwkBz0PvyblIm1IQO4xO."
        self.assertTrue(check_password("legacy-password", f"php_bcrypt${legacy_hash}"))
        source = FakeLegacyConnection({
            "usuarios": [{
                "id": 91, "nome": "Legado", "email": "legado@example.com", "senha": legacy_hash, "perfil": "funcionario",
                "ativo": 1, "forcar_troca_senha": 1, "ultimo_acesso": None,
                "created_at": timezone.now().replace(tzinfo=None), "updated_at": timezone.now().replace(tzinfo=None),
            }]
        })
        first = LegacyImporter(source, dry_run=False).run()
        user = User.objects.get(pk=91)
        self.assertEqual(user.email, "legado@example.com")
        self.assertTrue(check_password("legacy-password", user.password))
        second = LegacyImporter(source, dry_run=False).run()
        self.assertEqual(User.objects.filter(pk=91).count(), 1)
        self.assertEqual(first.imported["usuarios"], 1)
        self.assertEqual(second.updated["usuarios"], 1)
        self.assertEqual(legacy_link("producao/detalhes.php?id=8"), "/production/8/")
