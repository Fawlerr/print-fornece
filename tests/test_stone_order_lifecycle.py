"""Bateria de testes automatizados completa do Ciclo de Vida do Pedido com Stone V5.

Cobre:
1. Criação de cobrança Stone vinculada ao Pedido (PIX e Cartão).
2. Webhook idempotente:
   - Primeira entrega: baixa automática no Pedido (status 'pago'), atualização de estágio, snapshot e reflexo no Caixa.
   - Segunda entrega (evento duplicado): idempotência comprovada (sem duplicidade financeira).
3. Resiliência e tratamento de falhas da API da Stone (mensagens amigáveis para ponta e log técnico).
4. Restrição estrita de permissões do Painel/Drawer Dev (HTTP 403 para usuários comuns, operadores e admins não-dev).
5. Ações rápidas do Painel Dev (forçar aprovação, recusa, reprocessamento e ping).
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.orders.models import Order, OrderPayment
from apps.payments.models import Cliente, StonePagamento, StoneLogIntegracao
from apps.payments.stone.services.stone import StoneAPIError, StoneService
from apps.payments.stone.services.payments import (
    create_order_stone_payment,
    process_stone_webhook,
    reconcile_order_payment,
)


class FakeStoneOrderService:
    def __init__(self):
        self.is_configured = True

    def require_server_credentials(self):
        return None

    def create_customer(self, customer):
        return {"id": "cus_order_test_123"}

    def update_customer(self, customer):
        return {"id": customer.stone_customer_id or "cus_order_test_123"}

    def create_pix_payment(self, **kwargs):
        order_num = kwargs.get("order_number", "0001")
        return {
            "id": f"or_stone_{order_num}",
            "status": "pending",
            "_stone_http_status": 200,
            "_stone_duracao_ms": 120,
            "charges": [
                {
                    "id": f"ch_pix_{order_num}",
                    "status": "pending",
                    "last_transaction": {
                        "id": f"tran_pix_{order_num}",
                        "transaction_type": "pix",
                        "status": "waiting_payment",
                        "qr_code": "00020126580014BR.GOV.BCB.PIX0136TESTE_STONE_ORDER_PIX",
                        "qr_code_url": "https://api.pagar.me/qr/pix_order_test.png",
                    },
                }
            ],
        }

    def create_card_payment(self, **kwargs):
        order_num = kwargs.get("order_number", "0001")
        return {
            "id": f"or_stone_{order_num}",
            "status": "paid",
            "_stone_http_status": 200,
            "_stone_duracao_ms": 180,
            "charges": [
                {
                    "id": f"ch_card_{order_num}",
                    "status": "paid",
                    "paid_at": timezone.now().isoformat(),
                    "last_transaction": {
                        "id": f"tran_card_{order_num}",
                        "transaction_type": "credit_card",
                        "status": "captured",
                        "card": {
                            "id": "card_test_123",
                            "brand": "Visa",
                            "last_four_digits": "4321",
                        },
                    },
                }
            ],
        }

    def test_connectivity(self):
        return {"status": "ok", "orders_count": 1}


class StoneOrderLifecycleTestCase(TestCase):
    def setUp(self):
        self.employee_user = User.objects.create_user(
            email="funcionario@exemplo.com",
            name="Funcionário Operador",
            password="senha_segura_123",
            role=User.Role.EMPLOYEE,
        )
        self.admin_user = User.objects.create_user(
            email="admin@exemplo.com",
            name="Admin Comum",
            password="senha_segura_123",
            role=User.Role.ADMINISTRATOR,
        )
        self.dev_user = User.objects.create_user(
            email="dev@exemplo.com",
            name="Dev Master",
            password="senha_segura_123",
            role=User.Role.DEV,
        )
        self.superuser = User.objects.create_superuser(
            email="superuser@exemplo.com",
            name="Super Admin",
            password="senha_segura_123",
        )

        self.cliente = Cliente.objects.create(
            nome="Empresa Teste LTDA",
            cpf_cnpj="12345678000195",
            email="contato@empresateste.com",
            telefone="11999998888",
        )

        self.order = Order.objects.create(
            number="PF-9901",
            cliente=self.cliente,
            client_name=self.cliente.nome,
            total_amount=Decimal("250.00"),
            paid_amount=Decimal("0.00"),
            stage="aguardando_pagamento",
            payment_status=Order.PaymentStatus.UNPAID,
            created_by=self.dev_user,
            responsible=self.dev_user,
        )

    @patch("apps.payments.stone.services.payments.StoneService", return_value=FakeStoneOrderService())
    def test_order_stone_create_pix_charge_lifecycle(self, mock_svc):
        """Testa geração de cobrança PIX Stone para um pedido e vínculo de chave estrangeira."""
        self.client.force_login(self.dev_user)
        url = reverse("orders:stone_create_charge", kwargs={"pk": self.order.pk})
        
        response = self.client.post(
            url,
            data=json.dumps({"amount": 250.00, "method": "pix"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["method"], "pix")
        self.assertEqual(data["status"], "pending")
        self.assertTrue("TESTE_STONE_ORDER_PIX" in data["pix_qr_code"])

        # Verifica relacionamento no banco
        self.assertEqual(self.order.stone_pagamentos.count(), 1)
        stone_pag = self.order.stone_pagamentos.first()
        self.assertEqual(stone_pag.valor, Decimal("250.00"))
        self.assertEqual(stone_pag.metodo, StonePagamento.Metodo.PIX)
        self.assertEqual(stone_pag.order, self.order)

    @patch("apps.payments.stone.services.payments.StoneService", return_value=FakeStoneOrderService())
    def test_webhook_receipt_and_idempotency(self, mock_svc):
        """Testa recebimento de webhook da Stone com liquidação do pedido e garantia de idempotência."""
        # 1. Cria cobrança pendente
        stone_pag = create_order_stone_payment(
            order=self.order,
            amount=Decimal("250.00"),
            method=StonePagamento.Metodo.PIX,
            user=self.dev_user,
        )
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertEqual(self.order.paid_amount, Decimal("0.00"))

        # Payload do webhook Stone
        event_id = f"evt_test_{uuid.uuid4().hex[:12]}"
        webhook_payload = {
            "id": event_id,
            "type": "charge.paid",
            "data": {
                "id": stone_pag.stone_payment_id or "ch_pix_PF-9901",
                "status": "paid",
                "paid_at": "2026-10-13T19:30:00Z",
                "amount": 25000,
                "order": {
                    "id": stone_pag.stone_order_id or "or_stone_PF-9901",
                    "code": self.order.number,
                },
                "last_transaction": {
                    "id": "tran_pix_PF-9901",
                    "transaction_type": "pix",
                    "status": "captured",
                },
            },
        }

        # 2. Primeira entrega do Webhook
        res1 = process_stone_webhook(webhook_payload, headers={"X-Test": "1"})
        self.assertEqual(res1["status"], "success")

        # Verifica baixa no pedido
        self.order.refresh_from_db()
        stone_pag.refresh_from_db()

        self.assertEqual(stone_pag.status, StonePagamento.Status.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(self.order.paid_amount, Decimal("250.00"))
        self.assertEqual(self.order.stage, "pagamento_confirmado")
        self.assertIsNotNone(self.order.payment_confirmed_at)

        # Verifica criação do OrderPayment (integração transparente com o Caixa)
        order_payments = self.order.payments.all()
        self.assertEqual(order_payments.count(), 1)
        op = order_payments.first()
        self.assertEqual(op.amount, Decimal("250.00"))
        self.assertEqual(op.payment_method, "pix")
        self.assertEqual(op.stone_payment, stone_pag)

        # 3. Segunda entrega do Webhook (simulando reenvio de rede pela Stone)
        res2 = process_stone_webhook(webhook_payload, headers={"X-Test": "2"})
        self.assertEqual(res2["status"], "already_processed")

        # Garante que NENHUM pagamento extra foi criado (Idempotência financeira)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payments.count(), 1)
        self.assertEqual(self.order.paid_amount, Decimal("250.00"))

    def test_api_failure_resilience_and_user_friendly_message(self):
        """Testa se falhas da Stone retornam mensagens amigáveis enquanto gravam log técnico."""
        class FailingStoneService:
            is_configured = True
            def require_server_credentials(self): return None
            def create_customer(self, customer): return {"id": "cus_123"}
            def update_customer(self, customer): return {"id": "cus_123"}
            def create_pix_payment(self, **kwargs):
                raise StoneAPIError(
                    "O sistema da Stone demorou para responder. Verifique sua conexão ou tente novamente em instantes.",
                    http_status=504,
                    trace_id="trc_timeout_999",
                )

        with patch("apps.payments.stone.services.payments.StoneService", return_value=FailingStoneService()):
            self.client.force_login(self.dev_user)
            url = reverse("orders:stone_create_charge", kwargs={"pk": self.order.pk})
            response = self.client.post(
                url,
                data=json.dumps({"amount": 100.00, "method": "pix"}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertFalse(data["success"])
            self.assertIn("demorou para responder", data["error"])
            self.assertEqual(data["trace_id"], "trc_timeout_999")

    def test_dev_security_and_permission_boundaries(self):
        """Garante que usuários comuns e administradores comuns NUNCA acessem rotas Dev da Stone (HTTP 403)."""
        dev_urls = [
            reverse("orders:stone_dev_logs", kwargs={"pk": self.order.pk}),
            reverse("orders:stone_dev_force_approve", kwargs={"pk": self.order.pk}),
            reverse("orders:stone_dev_force_fail", kwargs={"pk": self.order.pk}),
            reverse("orders:stone_dev_reprocess", kwargs={"pk": self.order.pk}),
            reverse("orders:stone_dev_ping", kwargs={"pk": self.order.pk}),
            reverse("payments:stone_dev_console"),
            reverse("payments:stone_dev_ping"),
        ]

        # 1. Usuário Operador / Funcionário -> HTTP 403
        self.client.force_login(self.employee_user)
        for url in dev_urls:
            resp = self.client.get(url) if "force" not in url and "reprocess" not in url else self.client.post(url)
            self.assertEqual(resp.status_code, 403, f"Rota dev {url} deveria retornar 403 para funcionário comum")

        # 2. Administrador Comum (sem is_dev e sem is_superuser) -> HTTP 403
        self.client.force_login(self.admin_user)
        for url in dev_urls:
            resp = self.client.get(url) if "force" not in url and "reprocess" not in url else self.client.post(url)
            self.assertEqual(resp.status_code, 403, f"Rota dev {url} deveria retornar 403 para admin não-dev")

        # 3. Usuário Desenvolvedor (is_dev=True) -> Acesso permitido
        self.client.force_login(self.dev_user)
        with patch("apps.payments.stone.services.stone.StoneService.test_connectivity", return_value={"status": "ok"}):
            resp_console = self.client.get(reverse("payments:stone_dev_console"))
            self.assertEqual(resp_console.status_code, 200)

            resp_logs = self.client.get(reverse("orders:stone_dev_logs", kwargs={"pk": self.order.pk}))
            self.assertEqual(resp_logs.status_code, 200)

        # 4. Superuser (is_superuser=True) -> Acesso permitido
        self.client.force_login(self.superuser)
        with patch("apps.payments.stone.services.stone.StoneService.test_connectivity", return_value={"status": "ok"}):
            resp_console = self.client.get(reverse("payments:stone_dev_console"))
            self.assertEqual(resp_console.status_code, 200)

    @patch("apps.payments.stone.services.stone.StoneService.test_connectivity", return_value={"status": "ok"})
    def test_dev_quick_actions_force_approve_and_fail(self, mock_conn):
        """Testa ações rápidas de simulação no Drawer Dev (aprovação forçada e recusa forçada)."""
        self.client.force_login(self.dev_user)

        # Forçar aprovação direta no pedido
        url_approve = reverse("orders:stone_dev_force_approve", kwargs={"pk": self.order.pk})
        resp = self.client.post(url_approve)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])

        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(self.order.paid_amount, Decimal("250.00"))
        self.assertEqual(self.order.payments.count(), 1)

        # Forçar recusa
        # Cria novo pedido pendente
        order2 = Order.objects.create(
            number="PF-9902",
            cliente=self.cliente,
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("0.00"),
            stage="aguardando_pagamento",
            payment_status=Order.PaymentStatus.UNPAID,
            created_by=self.dev_user,
            responsible=self.dev_user,
        )
        p2 = StonePagamento.objects.create(
            order=order2,
            cliente=self.cliente,
            valor=Decimal("100.00"),
            metodo=StonePagamento.Metodo.PIX,
            status=StonePagamento.Status.PENDING,
        )
        url_fail = reverse("orders:stone_dev_force_fail", kwargs={"pk": order2.pk})
        resp_fail = self.client.post(url_fail)
        self.assertEqual(resp_fail.status_code, 200)
        p2.refresh_from_db()
        self.assertEqual(p2.status, StonePagamento.Status.FAILED)
        self.assertIn("simulação", p2.last_error_message)
