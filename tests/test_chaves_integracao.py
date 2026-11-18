"""Página de desenvolvedor para trocar as chaves da Stone e da Umbler (apps.integracoes).

Só valores fictícios: nenhuma chamada real à Stone ou à Umbler.
"""
from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.integracoes import cofre
from apps.integracoes.models import ChaveIntegracao
from apps.payments.stone.services.stone import StoneConfigurationError, StoneService
from apps.whatsapp.umbler import UmblerClient

SK_TESTE = "sk_test_" + "a" * 20 + "WXYZ"
PK_TESTE = "pk_test_" + "b" * 20 + "QRST"
SK_PROD = "sk_" + "c" * 24 + "PR0D"
URL = "/dev/chaves/"


@override_settings(STONE_ENVIRONMENT="sandbox", STONE_SECRET_KEY="sk_test_do_env_0000", UMBLER_API_TOKEN="", UMBLER_ORGANIZATION_ID="",
                   UMBLER_WEBHOOK_SECRET="", INTEGRACOES_CHAVE_MESTRA="")
class ChavesIntegracaoTests(TestCase):
    def setUp(self):
        self.dev = User.objects.create_user(email="dev@pf.test", password="x", name="Dev", role=User.Role.DEV)
        self.admin = User.objects.create_user(email="admin@pf.test", password="x", name="Admin", role=User.Role.ADMINISTRATOR)
        self.func = User.objects.create_user(email="func@pf.test", password="x", name="Func", role=User.Role.EMPLOYEE)

    # --- acesso --------------------------------------------------------------------------------------------

    def test_url_resolve(self):
        self.assertEqual(reverse("integracoes:chaves"), URL)

    def test_so_desenvolvedor_acessa(self):
        self.assertEqual(self.client.get(URL).status_code, 302)  # anônimo vai para o login
        for usuario in (self.admin, self.func):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(URL).status_code, 403)
            self.assertEqual(self.client.post(URL, {"valor__UMBLER_API_TOKEN": "tok-x"}).status_code, 403)
        self.assertFalse(ChaveIntegracao.objects.exists())
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_link_no_menu_so_para_dev(self):
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("business:settings")), URL)
        self.client.force_login(self.dev)
        self.assertContains(self.client.get(URL), f'href="{URL}"')

    # --- gravação ------------------------------------------------------------------------------------------

    def test_salva_criptografado_e_passa_a_valer(self):
        self.client.force_login(self.dev)
        resp = self.client.post(URL, {"valor__STONE_SECRET_KEY": SK_TESTE, "valor__UMBLER_API_TOKEN": "tok-umbler-1234",
                                      "valor__UMBLER_ORGANIZATION_ID": "OrgFicticia9876"})
        self.assertEqual(resp.status_code, 302)
        registro = ChaveIntegracao.objects.get(nome="STONE_SECRET_KEY:sandbox")
        self.assertNotIn(SK_TESTE, registro.valor_cifrado)
        self.assertEqual(registro.final, "WXYZ")
        self.assertEqual(registro.atualizado_por, self.dev)
        # passa a valer na hora, com prioridade sobre o .env
        self.assertEqual(StoneService().secret_key, SK_TESTE)
        cliente = UmblerClient()
        self.assertEqual((cliente.token, cliente.organizacao), ("tok-umbler-1234", "OrgFicticia9876"))
        # auditoria sem o valor
        eventos = AuditEvent.objects.filter(action="chave_integracao.salva")
        self.assertEqual(eventos.count(), 3)
        self.assertNotIn(SK_TESTE, str(list(eventos.values_list("after", flat=True))))

    def test_pagina_nunca_mostra_a_chave(self):
        cofre.salvar("STONE_SECRET_KEY", SK_TESTE, self.dev)
        self.client.force_login(self.dev)
        resp = self.client.get(URL)
        self.assertNotContains(resp, SK_TESTE)
        self.assertNotContains(resp, "sk_test_do_env_0000")
        self.assertContains(resp, "…WXYZ")
        self.assertContains(resp, "Salva aqui")

    def test_campo_em_branco_mantem(self):
        cofre.salvar("UMBLER_API_TOKEN", "tok-antigo-1111", self.dev)
        self.client.force_login(self.dev)
        self.client.post(URL, {"valor__UMBLER_API_TOKEN": "   "})
        self.assertEqual(cofre.valor("UMBLER_API_TOKEN"), "tok-antigo-1111")

    def test_remover_volta_para_o_env(self):
        cofre.salvar("STONE_SECRET_KEY", SK_TESTE, self.dev)
        self.client.force_login(self.dev)
        self.client.post(URL, {"remover__STONE_SECRET_KEY": "1"})
        self.assertFalse(ChaveIntegracao.objects.exists())
        self.assertEqual(cofre.valor("STONE_SECRET_KEY"), "sk_test_do_env_0000")
        self.assertTrue(AuditEvent.objects.filter(action="chave_integracao.removida").exists())

    def test_gerar_segredo_do_webhook(self):
        self.client.force_login(self.dev)
        self.client.post(URL, {"gerar__UMBLER_WEBHOOK_SECRET": "1"})
        segredo = cofre.valor("UMBLER_WEBHOOK_SECRET")
        self.assertRegex(segredo, cofre.SEGREDO_URL)
        # o webhook passa a aceitar o novo segredo e recusa o resto
        self.assertEqual(self.client.post(f"/chat/webhook/umbler/{segredo}/", data="{}", content_type="application/json").status_code, 200)
        self.assertEqual(self.client.post("/chat/webhook/umbler/outro-segredo-qualquer-123456/", data="{}",
                                          content_type="application/json").status_code, 403)

    # --- validação no servidor (trava de ambiente) ---------------------------------------------------------

    def test_sandbox_recusa_chave_de_producao_e_nada_e_salvo(self):
        self.client.force_login(self.dev)
        resp = self.client.post(URL, {"valor__STONE_SECRET_KEY": SK_PROD, "valor__UMBLER_API_TOKEN": "tok-valido-1"})
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "sk_test_", status_code=400)
        self.assertNotContains(resp, SK_PROD, status_code=400)
        self.assertFalse(ChaveIntegracao.objects.exists())  # tudo ou nada

    def test_validacoes(self):
        casos = [
            ("STONE_SECRET_KEY", "pk_test_errada"),
            ("STONE_PUBLIC_KEY", "pk_live_semtest_1234"),
            ("UMBLER_WEBHOOK_SECRET", "curto"),
            ("UMBLER_WEBHOOK_SECRET", "tem espaço " * 4),
            ("UMBLER_API_TOKEN", "x" * 501),
        ]
        for nome, texto in casos:
            with self.subTest(nome=nome, texto=texto[:20]), self.assertRaises(cofre.ChaveInvalida):
                cofre.validar(nome, texto)
        self.assertEqual(cofre.validar("STONE_PUBLIC_KEY", f"  {PK_TESTE} "), PK_TESTE)

    @override_settings(STONE_ENVIRONMENT="production")
    def test_producao_recusa_chave_de_teste(self):
        with self.assertRaises(cofre.ChaveInvalida):
            cofre.validar("STONE_SECRET_KEY", SK_TESTE)
        self.assertEqual(cofre.validar("STONE_SECRET_KEY", SK_PROD), SK_PROD)

    def test_chaves_da_stone_separadas_por_ambiente(self):
        cofre.salvar("STONE_SECRET_KEY", SK_TESTE, self.dev)
        with override_settings(STONE_ENVIRONMENT="production", STONE_SECRET_KEY=""):
            self.assertEqual(cofre.valor("STONE_SECRET_KEY"), "")  # nunca usa a chave do sandbox em produção
            cofre.salvar("STONE_SECRET_KEY", SK_PROD, self.dev)
            self.assertEqual(cofre.valor("STONE_SECRET_KEY"), SK_PROD)
        self.assertEqual(cofre.valor("STONE_SECRET_KEY"), SK_TESTE)

    def test_trava_do_cliente_stone_continua_valendo(self):
        # Mesmo que uma chave de produção chegue ao banco por fora, o cliente em sandbox recusa usá-la.
        ChaveIntegracao.objects.create(nome="STONE_SECRET_KEY:sandbox", valor_cifrado=cofre.cifrar(SK_PROD), final="PR0D")
        with self.assertRaises(StoneConfigurationError):
            StoneService().require_server_credentials()

    def test_chave_ilegivel_cai_no_env(self):
        cofre.salvar("STONE_SECRET_KEY", SK_TESTE, self.dev)
        with override_settings(SECRET_KEY="outra-secret-key-qualquer-para-teste"):
            self.assertEqual(cofre.valor("STONE_SECRET_KEY"), "sk_test_do_env_0000")
            self.assertEqual(cofre.situacao("STONE_SECRET_KEY")["origem"], "ilegivel")

    def test_chave_mestra_propria(self):
        from cryptography.fernet import Fernet

        with override_settings(INTEGRACOES_CHAVE_MESTRA=Fernet.generate_key().decode()):
            cofre.salvar("UMBLER_API_TOKEN", "tok-mestra-5555", self.dev)
            self.assertEqual(cofre.valor("UMBLER_API_TOKEN"), "tok-mestra-5555")
        self.assertEqual(cofre.valor("UMBLER_API_TOKEN"), "")  # sem a mestra certa não lê

    def test_sem_registro_usa_env(self):
        with override_settings(UMBLER_API_TOKEN="tok-env-7777"):
            self.assertEqual(cofre.valor("UMBLER_API_TOKEN"), "tok-env-7777")
            situacao = cofre.situacao("UMBLER_API_TOKEN")
            self.assertEqual((situacao["origem"], situacao["final"]), ("env", "7777"))
        self.assertEqual(cofre.situacao("UMBLER_API_TOKEN")["origem"], "vazia")
