"""A6 — aprovação do orçamento pelo link do WhatsApp e selo APROVADO no Kanban."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.whatsapp import get_whatsapp_share_links
from apps.orders.models import Order, OrderHistory, OrderItem
from apps.orders.services import quote_fingerprint


class QuoteApprovalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", name="Admin", password="strong-password", role=User.Role.ADMINISTRATOR)
        self.seller = User.objects.create_user(email="vendas@example.com", name="Vendedora", password="strong-password", role=User.Role.EMPLOYEE)
        self.order = Order.objects.create(
            number="0800", client_name="Cliente Link", client_whatsapp="84999999999", total_amount=Decimal("120.00"),
            created_by=self.admin, responsible=self.seller, stage=Order.Stage.NEW,
        )
        OrderItem.objects.create(
            order=self.order, position=1, kind=OrderItem.Kind.MATERIAL, material_code="dtf_textil", material_name="DTF Têxtil",
            category="Têxtil", billing_quantity=Decimal("2.00"), billing_unit="Metro", unit_price=Decimal("60.00"),
            line_total=Decimal("120.00"), pricing_rule="Teste",
        )
        self.page_url = reverse("orders:public_quote", args=[self.order.quote_token])
        self.approve_url = reverse("orders:approve_quote", args=[self.order.quote_token])

    def _approve(self, **extra):
        data = {"v": quote_fingerprint(self.order)}
        data.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.approve_url, data, REMOTE_ADDR="203.0.113.7")

    def test_whatsapp_preview_get_never_approves(self):
        # O WhatsApp abre o link sozinho (GET) para gerar a pré-visualização.
        for _ in range(3):
            response = self.client.get(self.page_url, HTTP_USER_AGENT="WhatsApp/2.23.20.0")
            self.assertEqual(response.status_code, 200)
        self.client.get(self.approve_url)  # GET no endpoint de aprovação também não aprova
        self.order.refresh_from_db()
        self.assertIsNone(self.order.client_approved_at)
        self.assertEqual(self.order.stage, Order.Stage.NEW)
        self.assertContains(self.client.get(self.page_url), "Aprovar orçamento")

    def test_post_click_approves_records_ip_and_moves_card(self):
        self._approve()
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.client_approved_at)
        self.assertEqual(self.order.client_approved_ip, "203.0.113.7")
        self.assertEqual(self.order.stage, Order.Stage.AWAITING_PAYMENT)  # mantém o movimento atual
        history = OrderHistory.objects.get(order=self.order, action="aprovacao_orcamento")
        self.assertIn("203.0.113.7", history.description)

    def test_double_click_is_idempotent(self):
        self._approve()
        first = Order.objects.get(pk=self.order.pk).client_approved_at
        self._approve()
        self.order.refresh_from_db()
        self.assertEqual(self.order.client_approved_at, first)
        self.assertEqual(OrderHistory.objects.filter(order=self.order, action="aprovacao_orcamento").count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.seller, title__icontains="aprovou").count(), 1)
        self.assertContains(self.client.get(self.page_url), "Orçamento aprovado em")

    def test_only_the_responsible_is_notified(self):
        self._approve()
        self.assertTrue(Notification.objects.filter(user=self.seller, title__icontains="aprovou").exists())
        self.assertFalse(Notification.objects.filter(user=self.admin, title__icontains="aprovou").exists())

    def test_cancelled_order_cannot_be_approved(self):
        Order.objects.filter(pk=self.order.pk).update(stage=Order.Stage.CANCELLED)
        page = self.client.get(self.page_url)
        self.assertContains(page, "Este pedido foi cancelado")
        self.assertNotContains(page, "Aprovar orçamento")
        self._approve()
        self.order.refresh_from_db()
        self.assertIsNone(self.order.client_approved_at)

    def test_order_changed_after_link_was_sent_is_not_approved(self):
        old_fingerprint = quote_fingerprint(self.order)
        Order.objects.filter(pk=self.order.pk).update(total_amount=Decimal("150.00"))
        self.order.refresh_from_db()
        page = self.client.get(self.page_url, {"v": old_fingerprint})
        self.assertContains(page, "Este orçamento foi atualizado")
        self._approve(v=old_fingerprint)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.client_approved_at)

    def test_links_sent_before_the_fingerprint_still_work(self):
        response = self.client.post(self.approve_url, REMOTE_ADDR="203.0.113.8")  # sem "v"
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.client_approved_at)

    def test_whatsapp_link_carries_version_and_token_not_sequential_id(self):
        links = get_whatsapp_share_links(self.order, host="https://app.example")
        self.assertIn(f"/orders/quote/{self.order.quote_token}/", links["quote_message"])
        self.assertIn(f"v={quote_fingerprint(self.order)}", links["quote_message"])
        self.assertGreaterEqual(len(str(self.order.quote_token)), 32)

    def test_unknown_token_is_404(self):
        self.assertEqual(self.client.get(reverse("orders:public_quote", args=["nao-existe"])).status_code, 404)

    def test_card_shows_approved_badge_with_date(self):
        self._approve()
        self.client.force_login(self.seller)
        kanban = self.client.get(reverse("production:kanban")).content.decode()
        approved = timezone.localtime(Order.objects.get(pk=self.order.pk).client_approved_at)
        self.assertIn("APROVADO", kanban)
        self.assertIn(approved.strftime("%d/%m %H:%M"), kanban)

    def test_kanban_live_updates_endpoint(self):
        self.client.force_login(self.seller)
        since = (timezone.now() - timedelta(seconds=5)).isoformat()
        self._approve()
        self.client.force_login(self.seller)
        data = self.client.get(reverse("production:kanban_updates"), {"since": since}).json()
        ids = [o["id"] for o in data["orders"]]
        self.assertIn(self.order.pk, ids)
        card = next(o for o in data["orders"] if o["id"] == self.order.pk)
        self.assertEqual(card["stage"], Order.Stage.AWAITING_PAYMENT)
        self.assertIn("APROVADO", card["html"])
        self.assertIn("now", data)

    def test_kanban_updates_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("production:kanban_updates"))
        self.assertEqual(response.status_code, 302)
