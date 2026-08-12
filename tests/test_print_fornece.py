from __future__ import annotations

import json
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
from apps.orders.calculator import CalculatorValidationError, calculate_quote
from apps.orders.legacy_import import LegacyImporter, legacy_link
from apps.orders.models import Order, OrderAttachment, OrderHistory, OrderItem, OrderNote, OrderStageHistory


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
                data='{"stage":"em_producao"}', content_type="application/json", HTTP_X_REQUESTED_WITH="XMLHttpRequest",
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
        response = self.client.post(reverse("production:move_stage", args=[self.order.pk]), {"stage": Order.Stage.DELIVERED})
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

    def test_pdf_art_preview_and_public_quote_approval(self):
        # 1. An unpaid order cannot generate a final payment receipt.
        self.login_as(self.admin)
        response = self.client.get(reverse("orders:download_receipt", args=[self.order.pk]))
        self.assertEqual(response.status_code, 403)

        # Confirming payment records the sales snapshot and unlocks the receipt.
        response = self.client.post(reverse("orders:edit", args=[self.order.pk]), {
            "client_name": self.order.client_name,
            "client_whatsapp": self.order.client_whatsapp,
            "description": self.order.description,
            "total_amount": "100,00",
            "payment_status": Order.PaymentStatus.PAID,
            "paid_amount": "100,00",
            "payment_method": Order.PaymentMethod.PIX,
            "priority": Order.Priority.NORMAL,
        })
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.payment_confirmed_at)
        self.assertEqual(self.order.receipt_total_amount, Decimal("100.00"))

        response = self.client.get(reverse("orders:download_receipt", args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("inline", response["Content-Disposition"])

        # The public quote token is no longer accepted for a paid receipt.
        self.client.logout()
        response = self.client.get(reverse("orders:download_receipt", args=[self.order.pk]) + f"?token={self.order.quote_token}")
        self.assertEqual(response.status_code, 403)
        self.login_as(self.admin)

        # 2. Test Art Preview on gray background endpoint
        response = self.client.get(reverse("orders:art_preview", args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

        # 3. Test Public Quote View & Approval
        quote_order = Order.objects.create(
            number="PF-QUOTE-0001",
            client_name="Cliente do orçamento",
            client_whatsapp="84999999999",
            description="Orçamento público",
            total_amount=Decimal("50.00"),
            paid_amount=Decimal("0"),
            created_by=self.admin,
        )
        self.client.logout()
        quote_url = reverse("orders:public_quote", args=[quote_order.quote_token])
        response = self.client.get(quote_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, quote_order.number)

        approve_url = reverse("orders:approve_quote", args=[quote_order.quote_token])
        response = self.client.post(approve_url)
        self.assertRedirects(response, quote_url)
        
        quote_order.refresh_from_db()
        self.assertEqual(quote_order.stage, Order.Stage.AWAITING_PAYMENT)
        self.assertTrue(OrderHistory.objects.filter(order=quote_order, action="aprovacao_orcamento").exists())

    def test_native_calculator_matches_rules_and_persists_historical_item(self):
        # Regression grid copied from the original calculator's public rules.
        for material, width, height, expected_cm, expected_total in (
            ("dtf_textil", "30", "30", "30", "23.00"),
            ("dtf_textil", "31", "31", "31", "30.00"),
            ("dtf_textil", "51", "80", "80", "48.00"),
            ("dtf_textil", "51", "81", "81", "50.00"),
            ("dtf_textil", "58", "900", "900", "450.00"),
            ("dtf_textil", "58", "901", "901", "405.45"),
            ("dtf_uv", "28", "30", "30", "35.00"),
            ("dtf_uv", "28", "50", "50", "45.00"),
            ("dtf_uv", "28", "90", "90", "81.00"),
            ("dtf_uv", "28", "91", "91", "75.00"),
            ("dtf_uv", "28", "199", "199", "149.25"),
            ("dtf_uv", "28", "200", "200", "140.00"),
        ):
            with self.subTest(material=material, width=width, height=height):
                local_quote = calculate_quote(material_code=material, width_cm=width, height_cm=height, quantity="1")
                self.assertEqual(local_quote.film_used_cm, Decimal(expected_cm))
                self.assertEqual(local_quote.total, Decimal(expected_total))
        with self.assertRaises(CalculatorValidationError):
            calculate_quote(material_code="dtf_textil", width_cm="59", height_cm="59", quantity="1")

        self.login_as(self.admin)
        calculate_url = reverse("orders:calculate_quote")
        response = self.client.post(
            calculate_url,
            data=json.dumps({"material_code": "dtf_textil", "width_cm": "51", "height_cm": "80", "quantity": "1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        quote = response.json()["quote"]
        self.assertEqual(quote["film_used_cm"], "80")
        self.assertEqual(quote["unit_price"], "60")
        self.assertEqual(quote["total"], "48.00")

        response = self.client.post(
            calculate_url,
            data=json.dumps({"material_code": "dtf_uv", "width_cm": "28", "height_cm": "200", "quantity": "1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["quote"]["total"], "140.00")

        calculation_payload = json.dumps({
            "material_code": "dtf_textil",
            "width_cm": "51",
            "height_cm": "80",
            "quantity": "1",
        })
        response = self.client.post(reverse("orders:create"), {
            "client_name": "Cliente do calculador",
            "client_whatsapp": "84999999999",
            "description": "DTF Têxtil calculado",
            "total_amount": "50,00",
            "payment_status": Order.PaymentStatus.PAID,
            "paid_amount": "50,00",
            "payment_method": Order.PaymentMethod.PIX,
            "priority": Order.Priority.NORMAL,
            "calculation_payload": calculation_payload,
        })
        self.assertEqual(response.status_code, 302)
        created = Order.objects.get(client_name="Cliente do calculador")
        item = OrderItem.objects.get(order=created, kind=OrderItem.Kind.MATERIAL)
        self.assertEqual(item.material_name, "DTF Têxtil")
        self.assertEqual(item.art_quantity, 1)
        self.assertEqual(item.used_length_cm, 80)
        self.assertEqual(item.billing_quantity, Decimal("0.80"))
        self.assertEqual(item.unit_price, Decimal("60.00"))
        self.assertEqual(item.line_total, Decimal("48.00"))
        adjustment = OrderItem.objects.get(order=created, kind=OrderItem.Kind.ADJUSTMENT)
        self.assertEqual(adjustment.line_total, Decimal("2.00"))
        self.assertEqual(adjustment.calculation_snapshot["source"], "manual_total_adjustment")
        self.assertEqual(created.receipt_total_amount, Decimal("50.00"))

        # The stored snapshot remains untouched if a future price configuration changes.
        snapshot = item.calculation_snapshot
        self.assertEqual(snapshot["total"], "48.00")

    def test_art_preview_and_kanban_cards(self):
        self.client.force_login(self.admin)
        order = Order.objects.create(
            client_name="Cliente Arte Preview",
            description="Banner 440g Ilhós",
            total_amount=Decimal("120.00"),
            payment_status=Order.PaymentStatus.PAID,
            priority=Order.Priority.URGENT,
            stage=Order.Stage.PRODUCTION,
            responsible=self.admin,
            created_by=self.admin,
        )
        OrderAttachment.objects.create(
            order=order,
            original_name="arte_final.pdf",
            file=SimpleUploadedFile("arte_final.pdf", b"%PDF-1.4 test content", content_type="application/pdf"),
            content_type="application/pdf",
            size=1024,
            created_by=self.admin,
        )

        response = self.client.get(reverse("orders:art_preview", kwargs={"pk": order.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(len(response.content) > 100)

        kanban_res = self.client.get(reverse("production:kanban"))
        self.assertEqual(kanban_res.status_code, 200)
        self.assertContains(kanban_res, "Cliente Arte Preview")
        self.assertContains(kanban_res, "Banner 440g Ilhós")
        self.assertContains(kanban_res, "Urgente")

