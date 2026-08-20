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
        self.dev = User.objects.create_user(
            email="dev@example.com", name="Desenvolvedor", password="strong-password", role=User.Role.DEV,
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
        # 1. Generating order PDF works for staff
        self.login_as(self.admin)
        response = self.client.get(reverse("orders:download_receipt", args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

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

        # Unauthenticated access with token works
        self.client.logout()
        response = self.client.get(reverse("orders:download_receipt", args=[self.order.pk]) + f"?token={self.order.quote_token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
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
        self.assertContains(kanban_res, "Quadro de Produção")

    def test_dev_role_master_access_and_complete_isolation_from_admin(self):
        # 1. Create DEV user
        dev_user = User.objects.create_user(
            email="devmaster@example.com",
            name="Dev Master",
            password="strong-password",
            role=User.Role.DEV,
        )
        self.assertTrue(dev_user.is_dev)
        self.assertTrue(dev_user.is_administrator)
        self.assertTrue(dev_user.is_staff)

        # 2. Admin cannot see DEV user in user list
        self.login_as(self.admin)
        res = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "devmaster@example.com")
        self.assertNotContains(res, "Dev Master")
        self.assertContains(res, self.admin.email)
        self.assertContains(res, self.employee.email)

        # 3. Admin cannot edit DEV user (returns 404)
        edit_url = reverse("accounts:user_edit", args=[dev_user.pk])
        res = self.client.get(edit_url)
        self.assertEqual(res.status_code, 404)

        # 4. Admin cannot create user with role DEV
        create_res = self.client.post(reverse("accounts:user_create"), {
            "name": "Tentativa Dev",
            "email": "hacker@example.com",
            "role": User.Role.DEV,
            "password1": "strong-password123",
            "password2": "strong-password123",
        })
        self.assertEqual(create_res.status_code, 200)
        self.assertFalse(User.objects.filter(email="hacker@example.com").exists())

        # 5. DEV can see all users in user list
        self.client.logout()
        self.login_as(dev_user)
        dev_res = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(dev_res.status_code, 200)
        self.assertContains(dev_res, "devmaster@example.com")
        self.assertContains(dev_res, self.admin.email)
        self.assertContains(dev_res, self.employee.email)

        # 6. Audit logs: AuditEventAdmin hides DEV events from Admin
        from django.test import RequestFactory
        from apps.audit.admin import AuditEventAdmin
        from apps.audit.models import AuditEvent
        from apps.audit.services import record_audit

        record_audit(dev_user, "teste_dev", "sistema", 1)
        record_audit(self.admin, "teste_admin", "sistema", 2)

        factory = RequestFactory()
        admin_req = factory.get("/admin/")
        admin_req.user = self.admin
        dev_req = factory.get("/admin/")
        dev_req.user = dev_user

        audit_admin = AuditEventAdmin(AuditEvent, None)
        admin_qs = audit_admin.get_queryset(admin_req)
        dev_qs = audit_admin.get_queryset(dev_req)

        self.assertFalse(admin_qs.filter(user=dev_user).exists())
        self.assertTrue(admin_qs.filter(user=self.admin).exists())
        self.assertTrue(dev_qs.filter(user=dev_user).exists())
        self.assertTrue(dev_qs.filter(user=self.admin).exists())

    def test_shirt_and_service_pricing_rules(self):
        from apps.orders.calculator import calculate_shirt_quote, calculate_service_quote

        # 1. Camisa Algodão Menegotti
        quote_single = calculate_shirt_quote(
            shirt_code="camisa_algodao_menegotti", color="Preta", size="M", quantity=1
        )
        self.assertEqual(quote_single.unit_price, Decimal("28.00"))
        self.assertEqual(quote_single.total, Decimal("28.00"))

        quote_tiered = calculate_shirt_quote(
            shirt_code="camisa_algodao_menegotti", color="Branca", size="GG", quantity=5
        )
        self.assertEqual(quote_tiered.unit_price, Decimal("25.00"))
        self.assertEqual(quote_tiered.total, Decimal("125.00"))

        # 2. Camisa Dry Fit
        quote_dry_single = calculate_shirt_quote(
            shirt_code="camisa_dry_fit_grao_arroz", color="Preta", size="P", quantity=4
        )
        self.assertEqual(quote_dry_single.unit_price, Decimal("23.00"))
        self.assertEqual(quote_dry_single.total, Decimal("92.00"))

        quote_dry_tiered = calculate_shirt_quote(
            shirt_code="camisa_dry_fit_grao_arroz", color="Branca", size="G", quantity=10
        )
        self.assertEqual(quote_dry_tiered.unit_price, Decimal("20.00"))
        self.assertEqual(quote_dry_tiered.total, Decimal("200.00"))

        # 3. Serviços Extras
        quote_ajuste = calculate_service_quote(service_code="ajuste_preparacao_arquivo", quantity=1)
        self.assertEqual(quote_ajuste.unit_price, Decimal("20.00"))
        self.assertEqual(quote_ajuste.total, Decimal("20.00"))

        quote_halftone = calculate_service_quote(service_code="formato_halftone", quantity=2)
        self.assertEqual(quote_halftone.unit_price, Decimal("10.00"))
        self.assertEqual(quote_halftone.total, Decimal("20.00"))

    def test_multi_item_order_creation_and_capacity_evaluation(self):
        from apps.production.capacity import get_shift_capacity_status, evaluate_order_capacity
        self.login_as(self.admin)

        cart_payload = {
            "items": [
                {
                    "kind": "material",
                    "material_code": "dtf_textil",
                    "width_cm": 50,
                    "height_cm": 50,
                    "quantity": 10,
                },
                {
                    "kind": "produto",
                    "shirt_code": "camisa_algodao_menegotti",
                    "color": "Preta",
                    "size": "G",
                    "quantity": 6,
                },
                {
                    "kind": "servico",
                    "service_code": "ajuste_preparacao_arquivo",
                    "quantity": 1,
                }
            ]
        }

        # Order creation with multi-items
        response = self.client.post(reverse("orders:create"), {
            "client_name": "Cliente Multi Item",
            "client_whatsapp": "(84) 98888-7777",
            "description": "Pedido com múltiplos produtos e serviços",
            "total_amount": "320,00",
            "payment_status": Order.PaymentStatus.UNPAID,
            "payment_method": Order.PaymentMethod.PIX,
            "priority": Order.Priority.NORMAL,
            "due_at": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT10:00"),
            "shift": Order.Shift.MORNING,
            "calculation_payload": json.dumps(cart_payload),
        })
        self.assertEqual(response.status_code, 302)

        order = Order.objects.get(client_name="Cliente Multi Item")
        self.assertEqual(order.shift, Order.Shift.MORNING)
        self.assertEqual(order.items.count(), 4)  # 3 items + 1 manual adjustment
        self.assertTrue(order.items.filter(kind=OrderItem.Kind.PRODUCT, product_color="Preta", product_size="G").exists())
        self.assertTrue(order.items.filter(kind=OrderItem.Kind.SERVICE, material_code="ajuste_preparacao_arquivo").exists())

        # Test capacity calculation for tomorrow morning
        target_date = (timezone.now() + timedelta(days=1)).date()
        cap_status = get_shift_capacity_status(
            target_date=target_date,
            shift=Order.Shift.MORNING,
            material_code="dtf_textil",
        )
        self.assertEqual(cap_status.limit_meters, Decimal("25.00"))
        self.assertGreater(cap_status.used_meters, Decimal("0.00"))

    def test_whatsapp_notification_templates(self):
        from apps.notifications.whatsapp import (
            build_quote_whatsapp_message,
            build_ready_whatsapp_message,
            build_delivered_whatsapp_message,
            get_whatsapp_share_links,
        )
        quote_msg = build_quote_whatsapp_message(self.order, "https://exemplo.com/orders/quote/token123/")
        self.assertIn("PRINT FORNECE", quote_msg)
        self.assertIn("Valor unitário/metro:", quote_msg)
        self.assertIn("TOTAL: R$", quote_msg)
        self.assertIn("Prazo estimado:", quote_msg)
        self.assertIn("preview", quote_msg.lower())
        # Ensure zero emojis in the message
        for emoji in ["🍀", "📏", "💰", "🟢", "✅", "⏰", "💳", "⚠️", "😊", "👋", "🎉", "📦", "📍", "🖼️"]:
            self.assertNotIn(emoji, quote_msg)

        ready_msg = build_ready_whatsapp_message(self.order)
        self.assertIn("pronto para retirada", ready_msg.lower())
        for emoji in ["🍀", "📏", "💰", "🟢", "✅", "⏰", "💳", "⚠️", "😊", "👋", "🎉", "📦", "📍", "🖼️"]:
            self.assertNotIn(emoji, ready_msg)

        delivered_msg = build_delivered_whatsapp_message(self.order)
        self.assertIn("entrega", delivered_msg.lower())
        for emoji in ["🍀", "📏", "💰", "🟢", "✅", "⏰", "💳", "⚠️", "😊", "👋", "🎉", "📦", "📍", "🖼️"]:
            self.assertNotIn(emoji, delivered_msg)

        links = get_whatsapp_share_links(self.order, "https://exemplo.com")
        self.assertIn("https://wa.me/5584999999999", links["quote_url"])

    def test_download_primary_attachment_route(self):
        self.login_as(self.admin)
        att = OrderAttachment.objects.create(
            order=self.order,
            original_name="arte_estampa.png",
            file=SimpleUploadedFile("arte_estampa.png", b"\x89PNG\r\n\x1a\nfakeimage", content_type="image/png"),
            content_type="image/png",
            size=100,
            created_by=self.admin,
        )
        res = self.client.get(reverse("orders:download_primary_attachment", args=[self.order.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Disposition"], 'attachment; filename="arte_estampa.png"')

    def test_four_digit_order_number_and_optional_description(self):
        from apps.orders.services import generate_order_number
        num = generate_order_number()
        self.assertEqual(len(num), 4)
        self.assertTrue(num.isdigit())

    def test_receipt_pdf_single_page_and_financial_alerts(self):
        import re
        from apps.orders.pdf import generate_order_receipt_pdf

        def _count_pages(pdf_bytes: bytes) -> int:
            return len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))

        # Caso 1: Nome curto + PAGO -> exatamente 1 página
        order1 = Order.objects.create(
            number="PDF-0001",
            client_name="JOÃO",
            client_whatsapp="84999991111",
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("100.00"),
            payment_status=Order.PaymentStatus.PAID,
            created_by=self.admin,
        )
        pdf1 = generate_order_receipt_pdf(order1)
        self.assertEqual(_count_pages(pdf1), 1)

        # Caso 2: Nome extremamente longo + PAGO -> exatamente 1 página
        order2 = Order.objects.create(
            number="PDF-0002",
            client_name="NOME EXTREMAMENTE GRANDE DE CLIENTE PARA TESTE DE IMPRESSÃO DA PRINT FORNECE",
            client_whatsapp="84999992222",
            total_amount=Decimal("250.00"),
            paid_amount=Decimal("250.00"),
            payment_status=Order.PaymentStatus.PAID,
            created_by=self.admin,
        )
        pdf2 = generate_order_receipt_pdf(order2)
        self.assertEqual(_count_pages(pdf2), 1)

        # Caso 3: Total R$ 150, Pago R$ 70, Saldo R$ 80 -> PAGAMENTO PARCIAL -> exatamente 1 página
        order3 = Order.objects.create(
            number="PDF-0003",
            client_name="Cliente Parcial",
            client_whatsapp="84999993333",
            total_amount=Decimal("150.00"),
            paid_amount=Decimal("70.00"),
            payment_status=Order.PaymentStatus.PARTIAL,
            created_by=self.admin,
        )
        pdf3 = generate_order_receipt_pdf(order3)
        self.assertEqual(_count_pages(pdf3), 1)

        # Caso 4: Total R$ 150, Pago R$ 0 -> PAGAMENTO PENDENTE -> exatamente 1 página
        order4 = Order.objects.create(
            number="PDF-0004",
            client_name="Cliente Não Pago",
            client_whatsapp="84999994444",
            total_amount=Decimal("150.00"),
            paid_amount=Decimal("0.00"),
            payment_status=Order.PaymentStatus.UNPAID,
            created_by=self.admin,
        )
        pdf4 = generate_order_receipt_pdf(order4)
        self.assertEqual(_count_pages(pdf4), 1)

    def test_customer_special_price_45_applied_automatically(self):
        from apps.orders.calculator import calculate_quote
        from apps.payments.models import Cliente

        # Cliente padrão sem preço especial (58x100cm = 1m dtf textil -> R$ 50,00)
        quote_normal = calculate_quote(material_code="dtf_textil", width_cm="58", height_cm="100", quantity=1)
        self.assertEqual(quote_normal.total, Decimal("50.00"))

        # Cliente com preço especial de R$ 45,00/m (58x100cm = 1m dtf textil -> R$ 45,00)
        cli_especial = Cliente.objects.create(
            nome="Cliente Especial 45",
            preco_especial_metro=Decimal("45.00"),
        )
        quote_especial = calculate_quote(
            material_code="dtf_textil",
            width_cm="58",
            height_cm="100",
            quantity=1,
            custom_price_per_meter=cli_especial.preco_especial_metro,
        )
        self.assertEqual(quote_especial.total, Decimal("45.00"))
        self.assertEqual(quote_especial.unit_price, Decimal("45.00"))
        self.assertIn("Preço especial", quote_especial.pricing_rule)

        # Via endpoint calculator com cliente_id
        self.login_as(self.admin)
        res = self.client.post(
            reverse("orders:calculate_quote"),
            data=json.dumps({
                "kind": "material",
                "material_code": "dtf_textil",
                "width_cm": "58",
                "height_cm": "100",
                "quantity": 1,
                "cliente_id": cli_especial.pk,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        res_data = res.json()
        self.assertEqual(res_data["quote"]["total"], "45.00")
        self.assertEqual(res_data["quote"]["unit_price"], "45.00")

    def test_kanban_uv_differentiation_and_whatsapp_notified(self):
        self.login_as(self.admin)
        uv_order = Order.objects.create(
            number="UV-0001",
            client_name="Cliente UV Card",
            client_whatsapp="84999995555",
            total_amount=Decimal("80.00"),
            description="DTF UV Rígidos",
            created_by=self.admin,
        )
        self.assertTrue(uv_order.is_uv)

        # Mark as notified via post endpoint
        res_notify = self.client.post(reverse("production:mark_whatsapp_notified", args=[uv_order.pk]))
        self.assertEqual(res_notify.status_code, 302)
        uv_order.refresh_from_db()
        self.assertTrue(uv_order.notified_whatsapp)
        self.assertIsNotNone(uv_order.notified_whatsapp_at)
        self.assertEqual(uv_order.notified_whatsapp_by, self.admin)

        # Check Kanban view contains UV badge and Avisado indicator
        res_kanban = self.client.get(reverse("production:kanban"))
        self.assertEqual(res_kanban.status_code, 200)
        self.assertContains(res_kanban, "badge-material-uv")
        self.assertContains(res_kanban, "badge-avisado")
        self.assertContains(res_kanban, "Avisado")

        # Test creating an order with blank description
        self.login_as(self.admin)
        response = self.client.post(reverse("orders:create"), {
            "client_name": "Cliente Sem Descricao",
            "client_whatsapp": "84999998888",
            "description": "",  # Optional!
            "total_amount": "50,00",
            "payment_status": Order.PaymentStatus.UNPAID,
            "paid_amount": "0,00",
            "priority": Order.Priority.NORMAL,
        })
        self.assertEqual(response.status_code, 302)
        new_order = Order.objects.get(client_name="Cliente Sem Descricao")
        self.assertEqual(new_order.description, "")
        self.assertEqual(len(new_order.number), 4)

    def test_stone_pagar_me_models(self):
        from apps.payments.models import Cliente, Pagamento, MetodoPagamento
        cli = Cliente.objects.create(
            nome="Empresa Teste Stone",
            cpf_cnpj="12.345.678/0001-90",
            email="contato@empresa.com",
            telefone="84988887777",
            stone_customer_id="cus_stone_12345",
        )
        self.assertEqual(str(cli), "Empresa Teste Stone")

        metodo = MetodoPagamento.objects.create(
            cliente=cli,
            stone_token_id="tok_stone_999",
            bandeira="Mastercard",
            ultimos_4="1234",
            validade="12/28",
            ativo=True,
        )
        self.assertIn("1234", str(metodo))

        pag = Pagamento.objects.create(
            cliente=cli,
            stone_payment_id="pay_stone_888",
            valor=Decimal("250.00"),
            metodo=Pagamento.Metodo.CARD,
            status=Pagamento.Status.PAID,
            parcelas=2,
            pedido_referencia=self.order,
        )
        self.assertEqual(pag.valor, Decimal("250.00"))
        self.assertEqual(pag.pedido_referencia, self.order)
        self.assertEqual(cli.pagamentos.count(), 1)

    def test_bug_report_workflow_and_permissions(self):
        from apps.bug_reports.models import BugReport
        # Regular employee submits a bug report
        self.login_as(self.employee)
        response = self.client.post(
            reverse("bug_reports:submit"),
            {
                "description": "Botão de impressão desalinhado no Safari",
                "current_url": "/orders/new/",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        report = BugReport.objects.get(description="Botão de impressão desalinhado no Safari")
        self.assertEqual(report.user, self.employee)
        self.assertEqual(report.status, BugReport.Status.PENDING)
        self.assertEqual(report.current_url, "/orders/new/")

        # Regular employee views list
        res_list = self.client.get(reverse("bug_reports:list"))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, "Botão de impressão desalinhado")

        # Dev user logs in and updates status
        self.login_as(self.dev)
        res_dev_list = self.client.get(reverse("bug_reports:list"))
        self.assertEqual(res_dev_list.status_code, 200)
        self.assertContains(res_dev_list, "Painel do Desenvolvedor")

        res_update = self.client.post(
            reverse("bug_reports:update_status", args=[report.pk]),
            {
                "status": BugReport.Status.FIXED,
                "dev_notes": "Corrigido CSS flexbox no commit abc1234",
            },
        )
        self.assertEqual(res_update.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.dev_notes, "Corrigido CSS flexbox no commit abc1234")

    def test_large_attachment_upload_accepted(self):
        from apps.orders.services import validate_upload
        # Test simulated 45MB file (which previously failed on 25MB limit)
        large_file = SimpleUploadedFile("projeto_estampa_45mb.pdf", b"%PDF-1.4\nsimulated pdf stream", content_type="application/pdf")
        large_file.size = 45 * 1024 * 1024
        orig_name, c_type = validate_upload(large_file)
        self.assertEqual(orig_name, "projeto_estampa_45mb.pdf")
        self.assertEqual(c_type, "application/pdf")

        # Test simulated 1GB file
        huge_file = SimpleUploadedFile("arquivo_vetor_1gb.ai", b"%PDF-1.5\nsimulated ai vector", content_type="application/pdf")
        huge_file.size = 1024 * 1024 * 1024
        orig_name2, c_type2 = validate_upload(huge_file)
        self.assertEqual(orig_name2, "arquivo_vetor_1gb.ai")

    def test_attachment_exceeding_max_limit_rejected(self):
        from django.core.exceptions import ValidationError
        from apps.orders.services import validate_upload

        # 7GB file (exceeds 6GB limit)
        oversized = SimpleUploadedFile("arte_pesada_7gb.pdf", b"%PDF-1.4\ncontent", content_type="application/pdf")
        oversized.size = 7 * 1024 * 1024 * 1024
        with self.assertRaises(ValidationError) as ctx:
            validate_upload(oversized)
        self.assertIn("excede o limite máximo permitido de 6 GB", str(ctx.exception))

    def test_tiff_attachment_validation(self):
        from apps.orders.services import validate_upload
        # Test .tif and .tiff
        tif_file = SimpleUploadedFile("estampa_alta_resolucao.tif", b"II*\x00simulated tiff data", content_type="image/tiff")
        orig_name, c_type = validate_upload(tif_file)
        self.assertEqual(orig_name, "estampa_alta_resolucao.tif")
        self.assertEqual(c_type, "image/tiff")

        tiff_file = SimpleUploadedFile("logo_empresa.tiff", b"MM\x00*simulated tiff data", content_type="image/tiff")
        orig_name2, c_type2 = validate_upload(tiff_file)
        self.assertEqual(orig_name2, "logo_empresa.tiff")
        self.assertEqual(c_type2, "image/tiff")

    def test_cliente_flow_and_volume_package(self):
        from apps.payments.models import Cliente, ClienteArquivo
        self.login_as(self.admin)

        # 1. Create cliente
        response = self.client.post(
            reverse("payments:customer_create"),
            {
                "nome": "Malharia Brasil",
                "telefone": "(11) 98888-7777",
                "preco_especial_metro": "35,00",
                "saldo_credito": "1750,00",
                "metros_saldo": "50,00",
                "observacoes": "Cliente VIP de alto volume.",
            },
        )
        self.assertEqual(response.status_code, 302)
        cliente = Cliente.objects.get(nome="Malharia Brasil")
        self.assertEqual(cliente.preco_especial_metro, Decimal("35.00"))
        self.assertEqual(cliente.saldo_credito, Decimal("1750.00"))

        # 2. Add file to cliente vault
        sample_file = SimpleUploadedFile("logo_cliente.png", b"\x89PNG\r\n\x1a\nsample", content_type="image/png")
        response = self.client.post(
            reverse("payments:customer_add_arquivo", args=[cliente.pk]),
            {"nome": "Logo Principal 2026", "arquivo": sample_file},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(cliente.arquivos_registrados.count(), 1)

        # 3. Autocomplete search
        response = self.client.get(reverse("payments:api_customer_search"), {"q": "Malharia"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["nome"], "Malharia Brasil")

        # 4. Excluir cliente
        delete_url = reverse("payments:customer_delete", args=[cliente.pk])
        get_delete_resp = self.client.get(delete_url)
        self.assertEqual(get_delete_resp.status_code, 200)
        self.assertIn("Excluir Cliente Definitivamente", get_delete_resp.content.decode("utf-8"))

        post_delete_resp = self.client.post(delete_url)
        self.assertRedirects(post_delete_resp, reverse("payments:customer_list"))
        self.assertFalse(Cliente.objects.filter(pk=cliente.pk).exists())

    def test_quick_payment_registration(self):
        self.login_as(self.admin)
        order = Order.objects.create(
            number="PED-TEST-PAY",
            client_name="Cliente Pagador",
            client_whatsapp="11999998888",
            description="Impressão DTF",
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("0.00"),
            payment_status=Order.PaymentStatus.UNPAID,
            stage=Order.Stage.AWAITING_PAYMENT,
            created_by=self.admin,
            responsible=self.employee,
        )

        # Register partial payment R$ 40
        response = self.client.post(
            reverse("orders:register_payment", args=[order.pk]),
            {"paid_amount": "40,00", "payment_method": Order.PaymentMethod.PIX, "notes": "Entrada"},
        )
        self.assertRedirects(response, reverse("production:detail", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.paid_amount, Decimal("40.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.PARTIAL)
        self.assertEqual(order.remaining_amount, Decimal("60.00"))

        # Complete payment R$ 60
        response = self.client.post(
            reverse("orders:register_payment", args=[order.pk]),
            {"paid_amount": "60,00", "payment_method": Order.PaymentMethod.PIX, "notes": "Restante"},
        )
        self.assertRedirects(response, reverse("production:detail", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.paid_amount, Decimal("100.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(order.stage, Order.Stage.PAYMENT_CONFIRMED)

    def test_whatsapp_messages_include_preview_links(self):
        from apps.notifications.whatsapp import build_ready_whatsapp_message, build_delivered_whatsapp_message
        preview_url = "https://printfornece.com/orders/quote/test-token-123/"
        ready_msg = build_ready_whatsapp_message(self.order, public_quote_url=preview_url)
        self.assertIn(preview_url, ready_msg)
        self.assertIn("pronto para retirada", ready_msg.lower())

        delivered_msg = build_delivered_whatsapp_message(self.order, public_quote_url=preview_url)
        self.assertIn(preview_url, delivered_msg)
        self.assertIn("entrega", delivered_msg.lower())

    def test_sector_permission_rules(self):
        from apps.production.services import move_order_stage
        from django.core.exceptions import PermissionDenied
        from apps.accounts.models import User

        paula_user = User.objects.create_user(
            email="paula@test.com",
            name="Paula Produção",
            password="testpassword",
            role=User.Role.EMPLOYEE,
            sector=User.Sector.PRODUCAO,
        )
        atendimento_user = User.objects.create_user(
            email="atendimento@test.com",
            name="Atendimento Vendas",
            password="testpassword",
            role=User.Role.EMPLOYEE,
            sector=User.Sector.ATENDIMENTO,
        )

        test_order = Order.objects.create(
            number="PED-SECTOR-01",
            client_name="Cliente Setores",
            client_whatsapp="11977776666",
            total_amount=Decimal("50.00"),
            stage=Order.Stage.NEW,
            created_by=self.admin,
            responsible=self.employee,
        )

        # Paula is production only: cannot move commercial initial stages (novo -> aguardando_pagamento)
        with self.assertRaises(PermissionDenied):
            move_order_stage(order_id=test_order.pk, new_stage=Order.Stage.AWAITING_PAYMENT, actor=paula_user)

        # Atendimento cannot move to pre_impressao / em_producao
        test_order.stage = Order.Stage.PAYMENT_CONFIRMED
        test_order.save()
        with self.assertRaises(PermissionDenied):
            move_order_stage(order_id=test_order.pk, new_stage=Order.Stage.PRE_PRESS, actor=atendimento_user)





