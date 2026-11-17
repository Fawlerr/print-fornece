"""Link de pagamento no cartão: cálculo do valor, link único ativo, regeneração, webhook (total, parcial,
forjado e duplicado), card em "Pagamento confirmado", nota impressa uma vez, envio pelo chat e conciliação.

O Pagar.me é substituído por um falso; nenhuma chamada sai da máquina.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.business.models import BusinessSettings
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderHistory, OrderPayment, OrderStageHistory
from apps.payments import links
from apps.payments.models import LinkPagamento, StonePagamento
from apps.payments.stone.services.payments import process_stone_webhook
from apps.payments.stone.services.stone import StoneConfigurationError, StoneService, StoneValidationError
from apps.whatsapp.evolution import Resultado
from apps.whatsapp.models import Instancia, Mensagem


class FakePagarme:
    """Lado Pagar.me: guarda links criados e responde às consultas como a API v5."""

    def __init__(self):
        self.criados: list[dict] = []
        self.cancelados: list[str] = []
        self.pedidos: dict[str, dict] = {}
        self.falhar_criacao = False

    def require_server_credentials(self):
        return None

    def create_payment_link(self, payload, *, idempotency_key):
        if self.falhar_criacao:
            raise StoneValidationError("Erro Pagar.me (amount): valor inválido", http_status=422)
        self.criados.append({"payload": payload, "idempotency_key": idempotency_key})
        n = len(self.criados)
        return {"id": f"pl_teste{n:04d}", "url": f"https://payment-link.pagar.me/pl_teste{n:04d}", "status": "active"}

    def cancel_payment_link(self, link_id):
        self.cancelados.append(link_id)
        return {}

    def pagar(self, order_code, *, pago_centavos, parcelas=1, status="paid", order_id="or_teste0001"):
        pedido = {
            "id": order_id, "code": order_code, "status": "paid" if status == "paid" else "pending",
            "charges": [{
                "id": "ch_teste0001", "status": status, "amount": pago_centavos, "paid_amount": pago_centavos,
                "paid_at": "2026-11-15T15:00:00Z", "payment_method": "credit_card",
                "last_transaction": {"id": "tran_teste0001", "status": "captured", "installments": parcelas, "transaction_type": "credit_card"},
            }],
        }
        self.pedidos[order_id] = pedido
        return pedido

    def get_order(self, order_id):
        if order_id not in self.pedidos:
            raise StoneValidationError("not found", http_status=404)
        return self.pedidos[order_id]

    def list_orders_by_code(self, code):
        return [p for p in self.pedidos.values() if p["code"] == code]


class FakeEvolution:
    enviados: list[tuple] = []

    def __init__(self, *a, **k):
        pass

    def enviar_texto(self, instancia, destino, texto):
        FakeEvolution.enviados.append((instancia, destino, texto))
        return Resultado(True, 201, {"key": {"id": f"EVO{len(FakeEvolution.enviados)}", "remoteJid": f"{destino}@s.whatsapp.net"}})


class BaseLink(TestCase):
    def setUp(self):
        self.pagarme = FakePagarme()
        for alvo in (
            "apps.payments.links.StoneService",
            "apps.payments.stone.services.payments.StoneService",
            "apps.payments.management.commands.conciliar_pagamentos.StoneService",
        ):
            p = patch(alvo, return_value=self.pagarme)
            p.start()
            self.addCleanup(p.stop)
        FakeEvolution.enviados = []
        p = patch("apps.whatsapp.provedores.EvolutionClient", FakeEvolution)
        p.start()
        self.addCleanup(p.stop)

        self.admin = User.objects.create_user(email="admin@pf.test", password="x", name="Admin", role=User.Role.ADMINISTRATOR)
        self.ana = User.objects.create_user(email="ana@pf.test", password="x", name="Ana", role=User.Role.EMPLOYEE, sector=User.Sector.ATENDIMENTO)
        self.paulo = User.objects.create_user(email="paulo@pf.test", password="x", name="Paulo", role=User.Role.EMPLOYEE, sector=User.Sector.PRODUCAO)
        config = BusinessSettings.load()
        config.link_max_parcelas, config.link_parcelas_sem_juros = 6, 3
        config.link_parcela_minima, config.link_juros_mensal = Decimal("50.00"), Decimal("2.99")
        config.link_repassar_taxa, config.link_validade_horas = False, 72
        config.save()
        self.order = self.novo_pedido(total="300.00", pago="50.00")

    def novo_pedido(self, *, total, pago="0.00", numero="8001", stage=Order.Stage.AWAITING_PAYMENT):
        status = Order.PaymentStatus.UNPAID if Decimal(pago) == 0 else Order.PaymentStatus.PARTIAL
        return Order.objects.create(
            number=numero, client_name="Loja da Maria", client_whatsapp="84999991234", total_amount=Decimal(total),
            paid_amount=Decimal(pago), payment_status=status, stage=stage, created_by=self.admin, responsible=self.ana,
        )

    def webhook(self, tipo="order.paid", order_id="or_teste0001", code=None, evento="evt_1"):
        # Como no Pagar.me: o evento de pedido traz o id e o code do pedido (o code é o do link).
        code = code or getattr(getattr(self, "link", None), "order_code", None)
        return process_stone_webhook({"id": evento, "type": tipo, "data": {"id": order_id, "code": code, "status": "paid"}})


class CalculoTests(BaseLink):
    def test_sem_pagamento_previo(self):
        c = links.calcular(self.novo_pedido(total="180.00", numero="8002"))
        self.assertEqual((c.saldo, c.valor, c.valor_centavos), (Decimal("180.00"), Decimal("180.00"), 18000))
        self.assertEqual([p.numero for p in c.parcelas], [1, 2, 3])  # 4x daria 47,xx < R$ 50

    def test_com_sinal_e_juros_price_pagos_pelo_cliente(self):
        c = links.calcular(self.order)
        self.assertEqual((c.total_pedido, c.pago, c.saldo, c.acrescimo), (Decimal("300.00"), Decimal("50.00"), Decimal("250.00"), Decimal("0.00")))
        tabela = [(p.numero, p.valor_parcela, p.total, p.com_juros) for p in c.parcelas]
        self.assertEqual(tabela, [
            (1, Decimal("250.00"), Decimal("250.00"), False),
            (2, Decimal("125.00"), Decimal("250.00"), False),
            (3, Decimal("83.33"), Decimal("250.00"), False),
            (4, Decimal("67.24"), Decimal("268.96"), True),
            (5, Decimal("54.57"), Decimal("272.85"), True),
        ])  # 6x seria R$ 46,13 < parcela mínima

    def test_total_com_desconto_e_atacado_ja_vem_no_pedido(self):
        # O total_amount do pedido já sai do formulário com atacado, desconto por camisa e abatimento.
        pedido = self.novo_pedido(total="1234.56", pago="234.56", numero="8003")
        self.assertEqual(links.calcular(pedido).valor, Decimal("1000.00"))

    def test_centavos_quebrados(self):
        c = links.calcular(self.novo_pedido(total="100.01", numero="8004"))
        self.assertEqual(c.valor_centavos, 10001)
        self.assertEqual([p.valor_parcela for p in c.parcelas], [Decimal("100.01"), Decimal("50.01")])  # 3x = 33,34 < R$ 50
        config = BusinessSettings.load()
        config.link_parcela_minima = Decimal("10.00")
        config.save()
        c = links.calcular(Order.objects.get(number="8004"))
        self.assertEqual(c.parcelas[2].valor_parcela, Decimal("33.34"))
        self.assertEqual(c.parcelas[2].total, Decimal("100.01"))

    def test_taxa_repassada_quando_ligada(self):
        config = BusinessSettings.load()
        config.link_repassar_taxa, config.link_taxa_percentual = True, Decimal("4.98")
        config.save()
        c = links.calcular(self.order)
        self.assertEqual((c.acrescimo, c.valor), (Decimal("12.45"), Decimal("262.45")))

    def test_sem_saldo_ou_cancelado(self):
        with self.assertRaises(links.LinkErro):
            links.calcular(self.novo_pedido(total="100.00", pago="100.00", numero="8005"))
        with self.assertRaises(links.LinkErro):
            links.calcular(self.novo_pedido(total="100.00", numero="8006", stage=Order.Stage.CANCELLED))


class GeracaoTests(BaseLink):
    def test_gera_link_so_cartao_em_centavos_vinculado_ao_pedido(self):
        link, reaproveitado = links.gerar(self.order, self.ana, valor_confirmado_centavos=25000)
        self.assertFalse(reaproveitado)
        enviado = self.pagarme.criados[0]
        payload = enviado["payload"]
        self.assertEqual(payload["payment_settings"]["accepted_payment_methods"], ["credit_card"])
        self.assertEqual(payload["cart_settings"]["items"][0]["amount"], 25000)
        self.assertEqual(payload["order_code"], link.order_code)
        self.assertTrue(link.order_code.startswith("PFL-8001-"))
        self.assertEqual(payload["max_paid_sessions"], 1)
        self.assertEqual(payload["expires_in"], 72 * 60)
        self.assertEqual(payload["payment_settings"]["credit_card_settings"]["installments"][-1], {"number": 5, "total": 27285})
        self.assertEqual(enviado["idempotency_key"], str(link.idempotency_key))
        self.assertEqual((link.status, link.url, link.criado_por), ("ativo", "https://payment-link.pagar.me/pl_teste0001", self.ana))
        self.assertTrue(OrderHistory.objects.filter(order=self.order, action="link_pagamento_gerado").exists())

    def test_reaproveita_link_ativo_do_mesmo_valor(self):
        primeiro, _ = links.gerar(self.order, self.ana)
        segundo, reaproveitado = links.gerar(self.order, self.ana)
        self.assertTrue(reaproveitado)
        self.assertEqual(primeiro.pk, segundo.pk)
        self.assertEqual(len(self.pagarme.criados), 1)

    def test_valor_mudou_cancela_antigo_e_gera_novo(self):
        antigo, _ = links.gerar(self.order, self.ana)
        Order.objects.filter(pk=self.order.pk).update(total_amount=Decimal("320.00"))  # sem signal: simula mudança concorrente
        novo, _ = links.gerar(self.order, self.ana)
        antigo.refresh_from_db()
        self.assertEqual((antigo.status, antigo.motivo_cancelamento), ("cancelado", "Valor do pedido mudou"))
        self.assertEqual(self.pagarme.cancelados, [antigo.pagarme_link_id])
        self.assertEqual(novo.valor_centavos, 27000)
        self.assertEqual(LinkPagamento.objects.filter(order=self.order, status="ativo").count(), 1)

    def test_um_unico_link_ativo_garantido_no_banco(self):
        links.gerar(self.order, self.ana)
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            LinkPagamento.objects.create(
                order=self.order, order_code="PFL-duplicado", valor_centavos=1, saldo_centavos=1, total_pedido=1, pago_antes=0,
                expira_em=timezone.now(), criado_por=self.ana,
            )

    def test_valor_confirmado_diferente_e_recusado(self):
        with self.assertRaises(links.LinkErro):
            links.gerar(self.order, self.ana, valor_confirmado_centavos=24999)
        self.assertFalse(LinkPagamento.objects.exists())

    def test_falha_na_api_fica_registrada(self):
        self.pagarme.falhar_criacao = True
        with self.assertRaises(links.LinkErro):
            links.gerar(self.order, self.ana)
        link = LinkPagamento.objects.get()
        self.assertEqual(link.status, "falhou")
        self.assertIsNone(link.trava_ativo)

    def test_producao_nao_gera_link(self):
        with self.assertRaises(links.LinkErro):
            links.gerar(self.order, self.paulo)
        c = Client()
        c.force_login(self.paulo)
        self.assertEqual(c.get(reverse("payments:link_confirmar", args=[self.order.pk])).status_code, 403)

    def test_tela_de_confirmacao_e_post(self):
        c = Client()
        c.force_login(self.ana)
        r = c.get(reverse("payments:link_confirmar", args=[self.order.pk]))
        self.assertContains(r, "R$ 250,00")
        self.assertContains(r, 'name="valor_centavos" value="25000"')
        r = c.post(reverse("payments:link_confirmar", args=[self.order.pk]), {"valor_centavos": "25000"})
        link = LinkPagamento.objects.get()
        self.assertRedirects(r, reverse("payments:link_detalhe", args=[link.pk]), fetch_redirect_response=False)
        r = c.get(reverse("payments:link_detalhe", args=[link.pk]))
        self.assertContains(r, link.url)
        self.assertContains(r, "Copiar link")

    def test_cancelar_link(self):
        link, _ = links.gerar(self.order, self.ana)
        c = Client()
        c.force_login(self.paulo)
        self.assertEqual(c.post(reverse("payments:link_cancelar", args=[link.pk]), {"motivo": "x"}).status_code, 403)
        c.force_login(self.ana)
        c.post(reverse("payments:link_cancelar", args=[link.pk]), {"motivo": "Cliente vai pagar no PIX"})
        link.refresh_from_db()
        self.assertEqual((link.status, link.cancelado_por, link.motivo_cancelamento), ("cancelado", self.ana, "Cliente vai pagar no PIX"))
        self.assertEqual(self.pagarme.cancelados, [link.pagarme_link_id])
        self.assertTrue(OrderHistory.objects.filter(order=self.order, action="link_pagamento_cancelado").exists())

    def test_mudanca_no_pedido_desativa_link(self):
        link, _ = links.gerar(self.order, self.ana)
        with self.captureOnCommitCallbacks(execute=True):
            self.order.total_amount = Decimal("400.00")
            self.order.save()
        link.refresh_from_db()
        self.assertEqual(link.status, "cancelado")


class ConfirmacaoTests(BaseLink):
    def setUp(self):
        super().setUp()
        self.link, _ = links.gerar(self.order, self.ana)

    def test_pagamento_total_quita_move_card_e_pede_impressao_uma_vez(self):
        self.pagarme.pagar(self.link.order_code, pago_centavos=25000)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.webhook()
        self.assertEqual(r["link_status"], "pago")
        self.order.refresh_from_db()
        self.assertEqual((self.order.payment_status, self.order.paid_amount, self.order.stage), ("pago", Decimal("300.00"), "pagamento_confirmado"))
        self.assertEqual(OrderPayment.objects.get(order=self.order).amount, Decimal("250.00"))
        self.assertIsNotNone(self.order.receipt_print_requested_at)
        self.assertEqual(OrderStageHistory.objects.filter(order=self.order, new_stage="pagamento_confirmado").count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.ana, title__contains="8001").exists())
        self.link.refresh_from_db()
        self.assertEqual((self.link.valor_pago_centavos, self.link.pagamento.metodo), (25000, "cartao"))
        # Webhook repetido (outro id de evento) não duplica nada nem reimprime
        primeira_impressao = self.order.receipt_print_requested_at
        self.webhook(evento="evt_2", tipo="charge.paid")
        self.order.refresh_from_db()
        self.assertEqual(OrderPayment.objects.filter(order=self.order).count(), 1)
        self.assertEqual(self.order.receipt_print_requested_at, primeira_impressao)
        # Mesmo id de evento: idempotência pelo log
        self.assertEqual(self.webhook(evento="evt_1")["status"], "already_processed")

    def test_juros_do_parcelamento_nao_entram_no_pedido(self):
        self.pagarme.pagar(self.link.order_code, pago_centavos=27285, parcelas=5)
        self.webhook()
        self.assertEqual(OrderPayment.objects.get(order=self.order).amount, Decimal("250.00"))
        self.link.refresh_from_db()
        self.assertEqual((self.link.valor_pago_centavos, self.link.parcelas_pagas), (27285, 5))
        self.assertIn("juros", OrderHistory.objects.filter(order=self.order, action="link_pagamento_pago").get().description)

    def test_pagamento_parcial_atualiza_saldo_sem_quitar(self):
        self.pagarme.pagar(self.link.order_code, pago_centavos=10000, status="underpaid")
        self.webhook(tipo="charge.underpaid")
        self.order.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual((self.link.status, self.order.payment_status, self.order.remaining_amount), ("pago_parcial", "parcial", Decimal("150.00")))
        self.assertEqual(self.order.stage, "aguardando_pagamento")

    def test_webhook_forjado_nao_da_baixa(self):
        # Corpo diz "pago", mas a API (fonte da verdade) diz pendente.
        self.pagarme.pagar(self.link.order_code, pago_centavos=25000, status="pending")
        self.webhook()
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "parcial")
        self.assertFalse(OrderPayment.objects.exists())
        # Pedido de outro link/código consultado na API é recusado
        self.pagarme.pagar("PFL-outro-1", pago_centavos=25000, order_id="or_outro0001")
        with self.assertRaises(links.LinkErro):
            process_stone_webhook({"id": "evt_x", "type": "order.paid", "data": {"id": "or_outro0001", "code": self.link.order_code}})
        self.assertFalse(OrderPayment.objects.exists())

    def test_envio_pelo_chat_e_confirmacao_no_chat(self):
        Instancia.objects.create(provedor="evolution", nome="pf_ana", apelido="Ana", vendedora=self.ana)
        texto = links.mensagem_padrao(self.link)
        self.assertIn(self.link.url, texto)
        self.assertIn("pedido #8001", texto)
        self.assertIn("R$ 250,00", texto)
        c = Client()
        c.force_login(self.ana)
        c.post(reverse("payments:link_enviar", args=[self.link.pk]), {"mensagem": texto})
        self.link.refresh_from_db()
        self.assertIsNotNone(self.link.enviado_em)
        self.assertEqual(FakeEvolution.enviados[0][:2], ("pf_ana", "5584999991234"))
        msg = Mensagem.objects.get()
        self.assertEqual((msg.origem, msg.pedido), ("automatica", self.order))
        # Mensagem editada sem o link é recusada
        r = c.post(reverse("payments:link_enviar", args=[self.link.pk]), {"mensagem": "sem link"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Mensagem.objects.count(), 1)
        # Ao pagar, a confirmação vai para o chat
        self.pagarme.pagar(self.link.order_code, pago_centavos=25000)
        with self.captureOnCommitCallbacks(execute=True):
            self.webhook()
        self.assertIn("Pagamento recebido", Mensagem.objects.order_by("-pk").first().texto)

    def test_conciliacao_registra_pago_e_expira_vencido(self):
        self.pagarme.pagar(self.link.order_code, pago_centavos=25000)
        outro = self.novo_pedido(total="90.00", numero="8010")
        vencido, _ = links.gerar(outro, self.ana)
        LinkPagamento.objects.filter(pk=vencido.pk).update(expira_em=timezone.now() - timedelta(hours=1))
        saida = StringIO()
        call_command("conciliar_pagamentos", stdout=saida)
        self.link.refresh_from_db()
        vencido.refresh_from_db()
        self.assertEqual((self.link.status, vencido.status), ("pago", "expirado"))
        self.assertIsNone(vencido.trava_ativo)
        self.assertIn("links_pago=1", saida.getvalue())
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "pago")


class TravaDeAmbienteTests(TestCase):
    @override_settings(STONE_ENVIRONMENT="sandbox")
    def test_sandbox_recusa_chave_de_producao(self):
        with self.assertRaises(StoneConfigurationError):
            StoneService(secret_key="sk_" + "0" * 32).require_server_credentials()
        StoneService(secret_key="sk_test_" + "0" * 32).require_server_credentials()

    @override_settings(STONE_ENVIRONMENT="production")
    def test_producao_recusa_chave_de_teste(self):
        with self.assertRaises(StoneConfigurationError):
            StoneService(secret_key="sk_test_" + "0" * 32).require_server_credentials()

    @override_settings(STONE_ENVIRONMENT="sandbox", STONE_PAYMENT_LINK_API_URL="https://sdx-api.pagar.me/core/v5")
    def test_link_usa_host_de_teste_e_so_cartao(self):
        service = StoneService(secret_key="sk_test_" + "0" * 32)
        with patch.object(StoneService, "_request", return_value={"id": "pl_x", "url": "https://x"}) as req:
            service.create_payment_link({"payment_settings": {"accepted_payment_methods": ["credit_card"]}}, idempotency_key="k")
        self.assertEqual(req.call_args.kwargs["base_url"], "https://sdx-api.pagar.me/core/v5")
        with self.assertRaises(StoneValidationError):
            service.create_payment_link({"payment_settings": {"accepted_payment_methods": ["credit_card", "pix"]}}, idempotency_key="k")


class WebhookStoneEndurecidoTests(TestCase):
    """O webhook antigo (PIX/cartão do pedido) também passou a confirmar na API antes de dar baixa."""

    def test_corpo_dizendo_pago_nao_basta(self):
        admin = User.objects.create_user(email="a@pf.test", password="x", name="A", role=User.Role.ADMINISTRATOR)
        order = Order.objects.create(number="9001", client_name="X", client_whatsapp="84999991234", total_amount=Decimal("100"), created_by=admin)
        pagamento = StonePagamento.objects.create(order=order, stone_payment_id="ch_real0001", valor=Decimal("100"), metodo="pix", referencia="Pedido #9001")

        class ApiDizPendente:
            def get_payment(self, charge_id):
                return {"id": charge_id, "status": "pending", "payment_method": "pix", "last_transaction": {"status": "waiting_payment", "transaction_type": "pix"}}

        with patch("apps.payments.stone.services.payments.StoneService", return_value=ApiDizPendente()):
            process_stone_webhook({"id": "evt_forjado", "type": "charge.paid", "data": {"id": "ch_real0001", "status": "paid"}})
        pagamento.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual((pagamento.status, order.payment_status), ("pending", "nao_pago"))

    def test_view_nao_vaza_detalhe_do_erro(self):
        with patch("apps.payments.stone.services.payments.process_stone_webhook", side_effect=RuntimeError("segredo interno")):
            r = Client().post(reverse("payments:stone_webhook_endpoint"), data=json.dumps({"id": "e"}), content_type="application/json")
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("segredo interno", r.content.decode())


class ConciliacaoStoneRegressaoTests(TestCase):
    """Dois defeitos do fluxo PIX/cartão existente, achados ao testar o link."""

    def test_sinal_digitado_no_pedido_e_mantido_e_nota_pedida(self):
        from apps.payments.stone.services.payments import reconcile_order_payment

        admin = User.objects.create_user(email="r@pf.test", password="x", name="R", role=User.Role.ADMINISTRATOR)
        order = Order.objects.create(
            number="9100", client_name="X", client_whatsapp="84999991234", total_amount=Decimal("300"), paid_amount=Decimal("50"),
            payment_status=Order.PaymentStatus.PARTIAL, stage=Order.Stage.AWAITING_PAYMENT, created_by=admin,
        )
        pagamento = StonePagamento.objects.create(order=order, stone_payment_id="ch_pix9100", valor=Decimal("250"), metodo="pix",
                                                  status="paid", referencia="Pedido #9100", paid_at=timezone.now())
        reconcile_order_payment(pagamento)
        reconcile_order_payment(pagamento)  # idempotente
        order.refresh_from_db()
        self.assertEqual((order.paid_amount, order.payment_status, order.stage), (Decimal("300.00"), "pago", "pagamento_confirmado"))
        self.assertIsNotNone(order.receipt_print_requested_at)
        self.assertEqual(OrderPayment.objects.filter(order=order).count(), 1)
