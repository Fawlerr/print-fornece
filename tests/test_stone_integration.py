"""Testes de integração automatizados do módulo Stone / Pagar.me V5 (Sandbox & Serviços)."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.payments.models import (
    Cliente,
    StoneEventoPagamento,
    StoneLogIntegracao,
    StoneMetodoPagamento,
    StonePagamento,
)
from apps.payments.stone.services.normalizers import (
    amount_to_cents,
    is_valid_cnpj,
    is_valid_cpf,
    mask_document,
    normalize_phone,
    parse_brl,
)
from apps.payments.stone.services.payments import create_payment, refresh_payment, sync_customer
from apps.payments.stone.services.stone import (
    StoneAPIError,
    StoneConfigurationError,
    StoneIdempotencyExpiredError,
    StoneInProgressError,
    StoneService,
    StoneValidationError,
)


class FakeStoneService:
    def __init__(self):
        self.pix_calls = 0
        self.card_calls = 0
        self.is_configured = True

    def require_server_credentials(self):
        return None

    def require_card_account_type(self):
        return "gateway"

    def create_customer(self, customer):
        return {"id": "cus_test_mock_123"}

    def update_customer(self, customer):
        return {"id": customer.stone_customer_id or "cus_test_mock_123"}

    def create_pix_payment(self, **kwargs):
        self.pix_calls += 1
        return {
            "id": "or_test_mock_123",
            "status": "pending",
            "_stone_http_status": 200,
            "_stone_duracao_ms": 150,
            "charges": [
                {
                    "id": "ch_test_mock_123",
                    "status": "pending",
                    "last_transaction": {
                        "id": "tran_test_mock_123",
                        "transaction_type": "pix",
                        "status": "waiting_payment",
                        "qr_code": "000201010212TESTE_PIX_QR_CODE",
                        "qr_code_url": "https://api.pagar.me/qr/test.png",
                    },
                }
            ],
        }

    def create_card_payment(self, **kwargs):
        self.card_calls += 1
        return {
            "id": "or_test_card_123",
            "status": "paid",
            "_stone_http_status": 200,
            "_stone_duracao_ms": 200,
            "charges": [
                {
                    "id": "ch_test_card_123",
                    "status": "paid",
                    "paid_at": "2026-09-22T00:00:00Z",
                    "last_transaction": {
                        "id": "tran_test_card_123",
                        "transaction_type": "credit_card",
                        "status": "captured",
                        "card": {
                            "id": "card_test_mock_123",
                            "brand": "Mastercard",
                            "last_four_digits": "1234",
                            "exp_month": 12,
                            "exp_year": 2030,
                        },
                    },
                }
            ],
        }

    def get_payment(self, charge_id):
        return {
            "id": charge_id,
            "status": "paid",
            "paid_at": "2026-09-22T00:05:00Z",
            "last_transaction": {
                "id": "tran_test_mock_123",
                "status": "paid",
                "transaction_type": "pix",
            },
        }

    def test_connectivity(self, trace_id=""):
        return {"_stone_http_status": 200, "status": "ok"}


class StoneIntegrationTestCase(TestCase):
    def setUp(self):
        self.dev_user = User.objects.create_user(
            email="dev_stone@test.com",
            name="Dev Stone",
            role=User.Role.DEV,
            password="devpassword123",
        )

        self.common_user = User.objects.create_user(
            email="employee_stone@test.com",
            name="Employee Stone",
            role=User.Role.EMPLOYEE,
            password="emppassword123",
        )
        self.cliente = Cliente.objects.create(
            nome="Gráfica Parceira Teste",
            cpf_cnpj="11222333000181",
            email="contato@graficaparceira.com.br",
            telefone="11987654321",
        )

    def test_normalizers(self):
        self.assertTrue(is_valid_cpf("11144477735"))
        self.assertFalse(is_valid_cpf("11111111111"))
        self.assertTrue(is_valid_cnpj("11222333000181"))
        self.assertEqual(normalize_phone("+55 (11) 98765-4321"), "11987654321")
        self.assertEqual(mask_document("11222333000181"), "**.***.***/0001-**")
        self.assertEqual(amount_to_cents(Decimal("150.50")), 15050)
        self.assertEqual(parse_brl("150,50"), Decimal("150.50"))

    def test_create_pix_payment_flow(self):
        service = FakeStoneService()
        idempotency = uuid.uuid4()
        payment = create_payment(
            customer=self.cliente,
            amount=Decimal("250.00"),
            reference="Pedido Teste #999",
            method=StonePagamento.Metodo.PIX,
            installments=1,
            idempotency_key=idempotency,
            service=service,
        )
        self.assertEqual(payment.status, StonePagamento.Status.PENDING)
        self.assertEqual(payment.stone_order_id, "or_test_mock_123")
        self.assertEqual(payment.stone_payment_id, "ch_test_mock_123")
        self.assertEqual(payment.pix_qr_code, "000201010212TESTE_PIX_QR_CODE")
        self.assertTrue(payment.is_pix)
        self.assertEqual(service.pix_calls, 1)

        # Atualização do status na Stone
        refreshed = refresh_payment(payment, service=service)
        self.assertEqual(refreshed.status, StonePagamento.Status.PAID)
        self.assertIsNotNone(refreshed.paid_at)

    def test_create_card_payment_and_wallet_sync(self):
        service = FakeStoneService()
        payment = create_payment(
            customer=self.cliente,
            amount=Decimal("320.00"),
            reference="Cartão Teste #1000",
            method=StonePagamento.Metodo.CARTAO,
            installments=2,
            idempotency_key=uuid.uuid4(),
            card_token="tok_test_mock_token_123",
            service=service,
        )
        self.assertEqual(payment.status, StonePagamento.Status.PAID)
        self.assertEqual(payment.stone_order_id, "or_test_card_123")

        # Cartão deve estar salvo na wallet
        wallet_method = StoneMetodoPagamento.objects.filter(cliente=self.cliente).first()
        self.assertIsNotNone(wallet_method)
        self.assertEqual(wallet_method.ultimos_4, "1234")
        self.assertEqual(wallet_method.bandeira, "Mastercard")

    def test_views_access_control(self):
        # 1. Usuário comum (EMPLOYEE) é barrado das views de teste Stone
        self.client.force_login(self.common_user)
        res_emp = self.client.get(reverse("payments:stone_dashboard"))
        self.assertIn(res_emp.status_code, [302, 403])

        # 2. Desenvolvedor tem acesso total
        self.client.force_login(self.dev_user)
        res_dev = self.client.get(reverse("payments:stone_dashboard"))
        self.assertEqual(res_dev.status_code, 200)
        self.assertContains(res_dev, "Painel de Integração Stone")
        self.assertContains(res_dev, "SANDBOX")

        # 3. View de Cobrança
        res_cobranca = self.client.get(reverse("payments:stone_cobranca"))
        self.assertEqual(res_cobranca.status_code, 200)
        self.assertContains(res_cobranca, "Gerar cobrança")



        # 4. View de Criar Pedido V5
        res_pedido = self.client.get(reverse("payments:stone_criar_pedido"))
        self.assertEqual(res_pedido.status_code, 200)
        self.assertContains(res_pedido, "POST /core/v5/orders")

        # 5. View de Testes Automatizados
        res_testes = self.client.get(reverse("payments:stone_testes"))
        self.assertEqual(res_testes.status_code, 200)

        # 6. View de Configuração
        res_cfg = self.client.get(reverse("payments:stone_configuracao"))
        self.assertEqual(res_cfg.status_code, 200)

    def test_api_executar_suite_testes(self):
        self.client.force_login(self.dev_user)
        response = self.client.post(reverse("payments:stone_api_executar_suite_testes"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("testes", data)
        self.assertGreater(data["total_testes"], 0)
