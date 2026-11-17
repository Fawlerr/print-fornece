"""Chat de WhatsApp: webhook da Evolution, envio, emojis, apagar, vínculo com cliente/pedido e permissões.

Nenhum teste fala com a Evolution de verdade: o cliente HTTP é substituído por um falso.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderAttachment, OrderHistory
from apps.payments.models import Cliente
from apps.whatsapp import services
from apps.whatsapp.evolution import Resultado
from apps.whatsapp.models import Conversa, EventoWebhook, Instancia, Mensagem
from apps.whatsapp.parser import interpretar
from apps.whatsapp.telefone import telefone_canonico, variantes_envio

SEGREDO = "segredo-de-teste-do-webhook"
_MIDIA_TMP = tempfile.mkdtemp(prefix="pf_wa_test_")


def upsert(key: dict, message: dict, *, instance="pf_ana", push_name="Cliente Teste", **extra) -> dict:
    data = {"key": key, "pushName": push_name, "message": message, "messageTimestamp": int(timezone.now().timestamp()), **extra}
    return {"event": "messages.upsert", "instance": instance, "data": data}


class FakeEvolution:
    """Substitui o EvolutionClient: registra as chamadas e devolve respostas no formato da Evolution v2."""

    chamadas: list[tuple[str, tuple, dict]] = []
    falhar = False
    contador = 0

    def __init__(self, *args, **kwargs):
        pass

    configurado = True

    @classmethod
    def reset(cls):
        cls.chamadas = []
        cls.falhar = False
        cls.contador = 0

    def _ok(self, nome, *args, **kwargs):
        FakeEvolution.chamadas.append((nome, args, kwargs))
        if FakeEvolution.falhar:
            return Resultado(False, 400, {}, "HTTP 400")
        FakeEvolution.contador += 1
        destino = args[1] if len(args) > 1 else ""
        return Resultado(True, 201, {"key": {"id": f"3EB0TESTE{FakeEvolution.contador:04d}", "remoteJid": f"{destino}@s.whatsapp.net", "fromMe": True}})

    def enviar_texto(self, instancia, destino, texto):
        return self._ok("enviar_texto", instancia, destino, texto)

    def enviar_midia(self, instancia, destino, **kwargs):
        return self._ok("enviar_midia", instancia, destino, **{k: v for k, v in kwargs.items() if k != "conteudo"})

    def apagar_para_todos(self, instancia, **kwargs):
        return self._ok("apagar_para_todos", instancia, **kwargs)

    def baixar_midia(self, instancia, dados):
        FakeEvolution.chamadas.append(("baixar_midia", (instancia,), {}))
        return b"\x89PNG\r\n\x1a\nconteudo", "image/png"


@override_settings(
    EVOLUTION_WEBHOOK_SECRET=SEGREDO,
    EVOLUTION_API_URL="https://evolution.teste.invalid",
    EVOLUTION_API_KEY="chave-falsa",
    WHATSAPP_MEDIA_ROOT=Path(_MIDIA_TMP),
)
class BaseChat(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MIDIA_TMP, ignore_errors=True)

    def setUp(self):
        FakeEvolution.reset()
        # patch no setUp (e não no decorator da classe) para valer também nos testes das subclasses
        patcher = patch("apps.whatsapp.provedores.EvolutionClient", FakeEvolution)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = User.objects.create_user(email="admin@pf.test", password="x", name="Admin", role=User.Role.ADMINISTRATOR)
        self.ana = User.objects.create_user(email="ana@pf.test", password="x", name="Ana", role=User.Role.EMPLOYEE, sector=User.Sector.ATENDIMENTO)
        self.bia = User.objects.create_user(email="bia@pf.test", password="x", name="Bia", role=User.Role.EMPLOYEE, sector=User.Sector.ATENDIMENTO)
        self.producao = User.objects.create_user(email="prod@pf.test", password="x", name="Paulo", role=User.Role.EMPLOYEE, sector=User.Sector.PRODUCAO)
        self.inst_ana = Instancia.objects.create(provedor="evolution", nome="pf_ana", apelido="Ana", vendedora=self.ana, estado="open")
        self.inst_bia = Instancia.objects.create(provedor="evolution", nome="pf_bia", apelido="Bia", vendedora=self.bia, estado="open")
        self.webhook = Client(enforce_csrf_checks=True)
        self.url_webhook = reverse("whatsapp:webhook_evolution", args=[SEGREDO])

    def post_webhook(self, payload, url=None):
        return self.webhook.post(url or self.url_webhook, data=json.dumps(payload), content_type="application/json")

    def receber_texto(self, texto="Oi", telefone="5584999991234", msg_id="MSG1", instance="pf_ana"):
        return self.post_webhook(upsert({"remoteJid": f"{telefone}@s.whatsapp.net", "fromMe": False, "id": msg_id}, {"conversation": texto}, instance=instance))


class TelefoneTests(TestCase):
    def test_canonico_unifica_formatos_e_nono_digito(self):
        for valor in ("84 9999-1234", "558499991234", "+55 (84) 99999-1234", "(84) 99999-1234"):
            self.assertEqual(telefone_canonico(valor), "5584999991234")

    def test_ddds_diferentes_nao_se_misturam(self):
        self.assertNotEqual(telefone_canonico("84 99999-1234"), telefone_canonico("11 99999-1234"))

    def test_fixo_nao_ganha_nono_digito(self):
        self.assertEqual(telefone_canonico("84 3222-1234"), "558432221234")

    def test_variantes_de_envio(self):
        self.assertEqual(variantes_envio("84999991234"), ["5584999991234", "558499991234"])
        self.assertEqual(variantes_envio("123@lid"), ["123@lid"])


class ParserTests(TestCase):
    def test_texto_imagem_video_figurinha(self):
        base = {"remoteJid": "5584999991234@s.whatsapp.net", "fromMe": False, "id": "A"}
        self.assertEqual(interpretar(upsert(base, {"conversation": "Olá 😀"}))[0]["texto"], "Olá 😀")
        img = interpretar(upsert(base, {"imageMessage": {"caption": "arte", "mimetype": "image/jpeg"}}))[0]
        self.assertEqual((img["tipo"], img["texto"], img["mimetype"]), ("imagem", "arte", "image/jpeg"))
        self.assertIsNotNone(img["midia"])
        self.assertEqual(interpretar(upsert(base, {"videoMessage": {"mimetype": "video/mp4"}}))[0]["tipo"], "video")
        self.assertEqual(interpretar(upsert(base, {"stickerMessage": {"mimetype": "image/webp"}}))[0]["tipo"], "figurinha")
        temporaria = {"ephemeralMessage": {"message": {"extendedTextMessage": {"text": "some em 7 dias"}}}}
        self.assertEqual(interpretar(upsert(base, temporaria))[0]["texto"], "some em 7 dias")

    def test_lid_com_numero_alternativo(self):
        ev = interpretar(upsert({"remoteJid": "1999@lid", "remoteJidAlt": "5584999991234@s.whatsapp.net", "fromMe": False, "id": "B"}, {"conversation": "x"}))[0]
        self.assertEqual((ev["telefone"], ev["lid"]), ("5584999991234", "1999"))

    def test_from_me_ignora_sender_pn_e_push_name(self):
        ev = interpretar(upsert(
            {"remoteJid": "5584999991234@s.whatsapp.net", "fromMe": True, "id": "C", "senderPn": "5584988887777@s.whatsapp.net"},
            {"conversation": "enviei do celular"}, push_name="Ana Vendedora",
        ))[0]
        self.assertTrue(ev["de_mim"])
        self.assertEqual(ev["telefone"], "5584999991234")
        self.assertEqual(ev["nome"], "")

    def test_grupos_reacoes_ignorados_e_revogacao(self):
        self.assertEqual(interpretar(upsert({"remoteJid": "123-456@g.us", "id": "D"}, {"conversation": "grupo"})), [])
        self.assertEqual(interpretar(upsert({"remoteJid": "5584999991234@s.whatsapp.net", "id": "E"}, {"reactionMessage": {"text": "👍"}})), [])
        rev = interpretar(upsert({"remoteJid": "5584999991234@s.whatsapp.net", "id": "F"}, {"protocolMessage": {"type": "REVOKE", "key": {"id": "MSG1"}}}))
        self.assertEqual(rev, [{"tipo_evento": "revogacao", "id": "MSG1"}])

    def test_status_e_delete(self):
        st = interpretar({"event": "messages.update", "data": [{"keyId": "X", "status": "READ"}, {"keyId": "Y", "status": "DELETED"}]})
        self.assertEqual(st, [{"tipo_evento": "status", "id": "X", "status": "lida"}, {"tipo_evento": "revogacao", "id": "Y"}])


class WebhookTests(BaseChat):
    def test_origem_invalida_e_segredo_nao_configurado(self):
        r = self.post_webhook(upsert({"remoteJid": "5584999991234@s.whatsapp.net", "id": "Z"}, {"conversation": "x"}),
                              url=reverse("whatsapp:webhook_evolution", args=["errado"]))
        self.assertEqual(r.status_code, 403)
        with override_settings(EVOLUTION_WEBHOOK_SECRET=""):
            self.assertEqual(self.receber_texto().status_code, 403)
        self.assertFalse(Mensagem.objects.exists())

    def test_texto_recebido_cria_conversa_e_mensagem_com_emoji(self):
        r = self.receber_texto("Bom dia 😀🎉")
        self.assertEqual(r.status_code, 200)
        conversa = Conversa.objects.get()
        self.assertEqual((conversa.instancia, conversa.telefone, conversa.nome, conversa.nao_lidas), (self.inst_ana, "5584999991234", "Cliente Teste", 1))
        msg = conversa.mensagens.get()
        self.assertEqual((msg.texto, msg.direcao, msg.id_externo), ("Bom dia 😀🎉", "in", "MSG1"))

    def test_evento_duplicado_nao_duplica(self):
        self.receber_texto()
        self.receber_texto()
        self.assertEqual(Mensagem.objects.count(), 1)
        self.assertEqual(Conversa.objects.get().nao_lidas, 1)
        self.assertEqual(EventoWebhook.objects.count(), 1)

    def test_instancia_desconhecida_e_ignorada(self):
        r = self.receber_texto(instance="nao_existe")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ignorado"])
        self.assertFalse(Conversa.objects.exists())

    def test_json_invalido(self):
        r = self.webhook.post(self.url_webhook, data="{nao é json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_lid_depois_numero_sem_duplicar_contato(self):
        self.post_webhook(upsert({"remoteJid": "1999@lid", "fromMe": False, "id": "L1"}, {"conversation": "oi"}))
        conversa = Conversa.objects.get()
        self.assertIsNone(conversa.telefone)
        self.assertEqual(conversa.destino, "1999@lid")
        # A Evolution passa a informar o número junto com o LID
        self.post_webhook(upsert({"remoteJid": "1999@lid", "remoteJidAlt": "5584999991234@s.whatsapp.net", "fromMe": False, "id": "L2"}, {"conversation": "oi de novo"}))
        self.assertEqual(Conversa.objects.count(), 1)
        conversa.refresh_from_db()
        self.assertEqual(conversa.telefone, "5584999991234")
        # Uma mensagem só com o número cai na mesma conversa
        self.receber_texto(msg_id="L3")
        self.assertEqual(Conversa.objects.count(), 1)
        self.assertEqual(conversa.mensagens.count(), 3)

    def test_contato_upsert_associa_lid(self):
        self.receber_texto()
        self.post_webhook({"event": "contacts.upsert", "instance": "pf_ana", "data": [{"id": "1999@lid", "phoneNumber": "5584999991234@s.whatsapp.net", "pushName": "Maria"}]})
        self.assertEqual(Conversa.objects.get().lid, "1999")
        # Contato da agenda sem conversa não cria conversa
        self.post_webhook({"event": "contacts.upsert", "instance": "pf_ana", "data": [{"id": "5511912345678@s.whatsapp.net", "pushName": "Outro"}]})
        self.assertEqual(Conversa.objects.count(), 1)

    def test_mensagem_do_celular_aparece_como_enviada(self):
        self.post_webhook(upsert({"remoteJid": "5584999991234@s.whatsapp.net", "fromMe": True, "id": "CEL1"}, {"conversation": "mandei do celular"}, push_name="Ana"))
        msg = Mensagem.objects.get()
        self.assertEqual((msg.direcao, msg.origem, msg.remetente), ("out", "celular", self.ana))
        self.assertEqual(msg.conversa.nome, "")  # pushName da vendedora não vira nome do cliente

    def test_eco_de_mensagem_enviada_pelo_sistema_nao_duplica(self):
        self.receber_texto()
        conversa = Conversa.objects.get()
        # Simula o eco chegando antes de o envio gravar o id: mensagem pendente com o mesmo texto
        pendente = Mensagem.objects.create(conversa=conversa, direcao="out", texto="Seu pedido está pronto", status="pendente", remetente=self.ana)
        self.post_webhook(upsert({"remoteJid": "5584999991234@s.whatsapp.net", "fromMe": True, "id": "ECO1"}, {"conversation": "Seu pedido está pronto"}))
        pendente.refresh_from_db()
        self.assertEqual(pendente.id_externo, "ECO1")
        self.assertEqual(conversa.mensagens.filter(direcao="out").count(), 1)

    def test_revogacao_recebida_e_status(self):
        self.receber_texto("vou apagar")
        self.post_webhook(upsert({"remoteJid": "5584999991234@s.whatsapp.net", "fromMe": False, "id": "R1"}, {"protocolMessage": {"type": "REVOKE", "key": {"id": "MSG1"}}}))
        msg = Mensagem.objects.get(id_externo="MSG1")
        self.assertIsNotNone(msg.revogada_em)
        self.assertEqual(msg.conversa.ultima_previa, services.MENSAGEM_APAGADA)

    def test_status_so_avanca(self):
        self.receber_texto()
        conversa = Conversa.objects.get()
        enviada = Mensagem.objects.create(conversa=conversa, direcao="out", texto="ok", status="enviada", id_externo="OUT1")
        self.post_webhook({"event": "messages.update", "instance": "pf_ana", "data": {"keyId": "OUT1", "status": "READ"}})
        self.post_webhook({"event": "messages.update", "instance": "pf_ana", "data": {"keyId": "OUT1", "status": "DELIVERY_ACK"}})
        enviada.refresh_from_db()
        self.assertEqual(enviada.status, "lida")

    def test_vincula_cliente_pelo_telefone_e_notifica_uma_vez(self):
        cliente = Cliente.objects.create(nome="Gráfica do Zé", telefone="(84) 99999-1234")
        with self.captureOnCommitCallbacks(execute=True):
            self.receber_texto(msg_id="N1")
        with self.captureOnCommitCallbacks(execute=True):
            self.receber_texto(msg_id="N2")
        self.assertEqual(Conversa.objects.get().cliente, cliente)
        self.assertEqual(Notification.objects.filter(user=self.ana).count(), 1)

    def test_erro_em_um_evento_nao_derruba_o_lote(self):
        payload = {"event": "messages.upsert", "instance": "pf_ana", "data": {"messages": [
            {"key": {"remoteJid": "5584999991234@s.whatsapp.net", "id": "OK1"}, "message": {"conversation": "um"}},
            {"key": {"remoteJid": "5584999995678@s.whatsapp.net", "id": "OK2"}, "message": {"conversation": "dois"}},
        ]}}
        original = services.registrar_mensagem_recebida

        def falha_no_primeiro(instancia, ev):
            if ev["id"] == "OK1":
                raise RuntimeError("falha simulada")
            return original(instancia, ev)

        with patch("apps.whatsapp.services.registrar_mensagem_recebida", side_effect=falha_no_primeiro), self.assertLogs("whatsapp", level="ERROR"):
            r = self.post_webhook(payload)
        self.assertEqual(r.json()["processados"], 1)
        self.assertTrue(Mensagem.objects.filter(id_externo="OK2").exists())
        # O evento que falhou fica liberado para o reenvio da Evolution
        self.assertFalse(EventoWebhook.objects.filter(chave="OK1").exists())
        self.post_webhook(payload)
        self.assertTrue(Mensagem.objects.filter(id_externo="OK1").exists())


class EnvioEApagarTests(BaseChat):
    def setUp(self):
        super().setUp()
        self.receber_texto()
        self.conversa = Conversa.objects.get()
        self.c_ana = Client()
        self.c_ana.force_login(self.ana)

    def enviar(self, cliente, texto, conversa=None):
        return cliente.post(reverse("whatsapp:api_enviar", args=[(conversa or self.conversa).pk]), data=json.dumps({"texto": texto}), content_type="application/json")

    def test_envio_de_texto_com_emoji(self):
        r = self.enviar(self.c_ana, "Pedido pronto ✅🎉")
        self.assertEqual(r.status_code, 200)
        dados = r.json()["mensagem"]
        self.assertEqual((dados["texto"], dados["status"]), ("Pedido pronto ✅🎉", "enviada"))
        nome, args, _ = FakeEvolution.chamadas[-1]
        self.assertEqual((nome, args[0], args[1], args[2]), ("enviar_texto", "pf_ana", "5584999991234", "Pedido pronto ✅🎉"))
        msg = Mensagem.objects.get(pk=dados["id"])
        self.assertEqual((msg.remetente, msg.id_externo), (self.ana, "3EB0TESTE0001"))
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.nao_lidas, 0)

    def test_falha_no_envio_fica_registrada_e_pode_reenviar(self):
        FakeEvolution.falhar = True
        dados = self.enviar(self.c_ana, "teste").json()["mensagem"]
        self.assertEqual(dados["status"], "falhou")
        FakeEvolution.falhar = False
        r = self.c_ana.post(reverse("whatsapp:api_reenviar", args=[dados["id"]]))
        self.assertEqual(r.json()["mensagem"]["status"], "enviada")
        self.assertIsNotNone(Mensagem.objects.get(pk=dados["id"]).ocultada_em)

    def test_texto_vazio_recusado(self):
        self.assertEqual(self.enviar(self.c_ana, "   ").status_code, 400)

    def test_apagar_para_mim_e_para_todos(self):
        m1 = self.enviar(self.c_ana, "um").json()["mensagem"]
        m2 = self.enviar(self.c_ana, "dois").json()["mensagem"]
        url = lambda m: reverse("whatsapp:api_apagar", args=[m["id"]])  # noqa: E731
        r = self.c_ana.post(url(m1), data=json.dumps({"escopo": "mim"}), content_type="application/json")
        self.assertTrue(r.json()["estado"]["ocultada"])
        r = self.c_ana.post(url(m2), data=json.dumps({"escopo": "todos"}), content_type="application/json")
        self.assertTrue(r.json()["estado"]["revogada"])
        nome, args, kwargs = FakeEvolution.chamadas[-1]
        self.assertEqual((nome, kwargs["id_mensagem"]), ("apagar_para_todos", Mensagem.objects.get(pk=m2["id"]).id_externo))
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.ultima_previa, services.MENSAGEM_APAGADA)

    def test_apagar_para_todos_fora_do_prazo(self):
        m = self.enviar(self.c_ana, "antiga").json()["mensagem"]
        Mensagem.objects.filter(pk=m["id"]).update(criada_em=timezone.now() - timedelta(hours=49))
        r = self.c_ana.post(reverse("whatsapp:api_apagar", args=[m["id"]]), data=json.dumps({"escopo": "todos"}), content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("48 horas", r.json()["erro"])
        self.assertIsNone(Mensagem.objects.get(pk=m["id"]).revogada_em)

    def test_vendedora_nao_apaga_mensagem_de_outra_pessoa(self):
        recebida = Mensagem.objects.get(direcao="in")
        r = self.c_ana.post(reverse("whatsapp:api_apagar", args=[recebida.pk]), data=json.dumps({"escopo": "mim"}), content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_envio_de_midia_privada_com_limite(self):
        arquivo = SimpleUploadedFile("arte.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, content_type="image/png")
        r = self.c_ana.post(reverse("whatsapp:api_enviar_midia", args=[self.conversa.pk]), {"arquivo": arquivo, "legenda": "Sua arte"})
        self.assertEqual(r.status_code, 200)
        msg = Mensagem.objects.get(pk=r.json()["mensagem"]["id"])
        self.assertEqual(msg.tipo, "imagem")
        self.assertTrue(Path(msg.arquivo.path).is_relative_to(Path(_MIDIA_TMP)))
        self.assertFalse(Path(msg.arquivo.path).is_relative_to(Path(settings.MEDIA_ROOT)))
        # Só usuário autenticado com acesso à conversa baixa a mídia
        self.assertEqual(Client().get(reverse("whatsapp:midia", args=[msg.pk])).status_code, 302)
        c_bia = Client()
        c_bia.force_login(self.bia)
        self.assertEqual(c_bia.get(reverse("whatsapp:midia", args=[msg.pk])).status_code, 404)
        r = self.c_ana.get(reverse("whatsapp:midia", args=[msg.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        with override_settings(WHATSAPP_MAX_UPLOAD_MB=0):
            grande = SimpleUploadedFile("grande.png", b"0" * 10, content_type="image/png")
            r = self.c_ana.post(reverse("whatsapp:api_enviar_midia", args=[self.conversa.pk]), {"arquivo": grande})
            self.assertEqual(r.status_code, 400)
        proibido = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/x-msdownload")
        r = self.c_ana.post(reverse("whatsapp:api_enviar_midia", args=[self.conversa.pk]), {"arquivo": proibido})
        self.assertEqual(r.status_code, 400)

    def test_midia_recebida_baixada_sob_demanda(self):
        self.post_webhook(upsert({"remoteJid": "5584999991234@s.whatsapp.net", "fromMe": False, "id": "IMG1"}, {"imageMessage": {"mimetype": "image/png", "caption": "foto"}}))
        msg = Mensagem.objects.get(id_externo="IMG1")
        self.assertTrue(msg.tem_midia)
        self.assertFalse(msg.arquivo)
        r = self.c_ana.get(reverse("whatsapp:midia", args=[msg.pk]))
        self.assertEqual(r.status_code, 200)
        msg.refresh_from_db()
        self.assertTrue(msg.arquivo)
        self.assertIsNone(msg.midia_pendente)

    def test_polling_traz_novas_e_estados(self):
        url = reverse("whatsapp:api_mensagens", args=[self.conversa.pk])
        ultimo = self.c_ana.get(url).json()["mensagens"][-1]["id"]
        self.receber_texto("nova", msg_id="MSG2")
        dados = self.c_ana.get(f"{url}?depois={ultimo}").json()
        self.assertEqual([m["texto"] for m in dados["mensagens"]], ["nova"])
        self.assertTrue(any(e["id"] == ultimo for e in dados["estados"]))


class PermissoesTests(BaseChat):
    def setUp(self):
        super().setUp()
        self.receber_texto(instance="pf_ana", msg_id="A1")
        self.receber_texto(telefone="5584988887777", instance="pf_bia", msg_id="B1")
        self.conv_ana = Conversa.objects.get(instancia=self.inst_ana)
        self.conv_bia = Conversa.objects.get(instancia=self.inst_bia)

    def test_vendedora_so_ve_as_proprias(self):
        c = Client()
        c.force_login(self.ana)
        ids = [x["id"] for x in c.get(reverse("whatsapp:api_conversas")).json()["conversas"]]
        self.assertEqual(ids, [self.conv_ana.pk])
        self.assertEqual(c.get(reverse("whatsapp:api_mensagens", args=[self.conv_bia.pk])).status_code, 404)
        r = c.post(reverse("whatsapp:api_enviar", args=[self.conv_bia.pk]), data=json.dumps({"texto": "x"}), content_type="application/json")
        self.assertEqual(r.status_code, 404)
        # Perfil de outra instância passado na URL não amplia o acesso
        ids = [x["id"] for x in c.get(reverse("whatsapp:api_conversas") + f"?perfil={self.inst_bia.pk}").json()["conversas"]]
        self.assertEqual(ids, [self.conv_ana.pk])

    def test_admin_ve_todas_e_filtra_por_perfil(self):
        c = Client()
        c.force_login(self.admin)
        dados = c.get(reverse("whatsapp:api_conversas") + "?perfil=todas").json()
        self.assertEqual({x["id"] for x in dados["conversas"]}, {self.conv_ana.pk, self.conv_bia.pk})
        self.assertEqual(dados["perfis"][0]["id"], "todas")
        ids = [x["id"] for x in c.get(reverse("whatsapp:api_conversas") + f"?perfil={self.inst_bia.pk}").json()["conversas"]]
        self.assertEqual(ids, [self.conv_bia.pk])

    def test_instancia_compartilhada_aparece_para_o_atendimento(self):
        empresa = Instancia.objects.create(provedor="evolution", nome="pf_empresa", apelido="Empresa", compartilhada=True)
        self.receber_texto(telefone="5584977776666", instance="pf_empresa", msg_id="E1")
        c = Client()
        c.force_login(self.ana)
        ids = {x["id"] for x in c.get(reverse("whatsapp:api_conversas") + "?perfil=todas").json()["conversas"]}
        self.assertIn(Conversa.objects.get(instancia=empresa).pk, ids)

    def test_producao_nao_acessa_chat(self):
        c = Client()
        c.force_login(self.producao)
        self.assertEqual(c.get(reverse("whatsapp:chat")).status_code, 403)
        self.assertEqual(c.get(reverse("whatsapp:api_conversas")).status_code, 403)

    def test_instancias_so_para_administrador(self):
        c = Client()
        c.force_login(self.ana)
        self.assertEqual(c.get(reverse("whatsapp:instancias")).status_code, 403)
        self.assertEqual(c.post(reverse("whatsapp:instancia_acao", args=[self.inst_ana.pk, "desconectar"])).status_code, 403)
        c.force_login(self.admin)
        self.assertEqual(c.get(reverse("whatsapp:instancias")).status_code, 200)

    def test_pagina_do_chat_renderiza(self):
        c = Client()
        c.force_login(self.ana)
        r = c.get(reverse("whatsapp:chat") + f"?c={self.conv_ana.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="chat-dados"')
        self.assertNotContains(r, "chave-falsa")


class IntegracaoPedidoTests(BaseChat):
    def setUp(self):
        super().setUp()
        self.order = Order.objects.create(
            number="7001", client_name="Loja da Maria", client_whatsapp="(84) 99999-1234", total_amount=Decimal("300.00"),
            paid_amount=Decimal("50.00"), payment_status=Order.PaymentStatus.PARTIAL, created_by=self.admin, responsible=self.ana,
        )
        self.c_ana = Client()
        self.c_ana.force_login(self.ana)

    def test_abrir_conversa_pelo_pedido(self):
        r = self.c_ana.get(reverse("whatsapp:abrir_pedido", args=[self.order.pk]))
        conversa = Conversa.objects.get()
        self.assertRedirects(r, reverse("whatsapp:chat") + f"?c={conversa.pk}", fetch_redirect_response=False)
        self.assertEqual((conversa.instancia, conversa.telefone), (self.inst_ana, "5584999991234"))

    def test_painel_mostra_pedidos_do_cliente_e_cadastro(self):
        self.receber_texto()
        conversa = Conversa.objects.get()
        painel = self.c_ana.get(reverse("whatsapp:api_painel", args=[conversa.pk])).json()
        self.assertIsNone(painel["cliente"])
        self.assertEqual([(p["numero"], p["saldo"]) for p in painel["pedidos"]], [("7001", "250.00")])
        r = self.c_ana.post(reverse("whatsapp:api_cliente", args=[conversa.pk]), data=json.dumps({"nome": "Loja da Maria"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        conversa.refresh_from_db()
        self.assertEqual((conversa.cliente.nome, conversa.cliente.telefone), ("Loja da Maria", "5584999991234"))

    def test_mensagem_automatica_do_pedido_entra_no_chat_sem_emojis(self):
        r = self.c_ana.post(reverse("whatsapp:enviar_aviso", args=[self.order.pk, "pronto"]))
        self.assertEqual(r.status_code, 302)
        msg = Mensagem.objects.get()
        self.assertEqual((msg.origem, msg.pedido, msg.remetente), ("automatica", self.order, self.ana))
        self.assertIn("SALDO A PAGAR NA RETIRADA: R$ 250,00", msg.texto)
        self.assertFalse(any(ord(ch) > 0x2600 and ch not in "━•" for ch in msg.texto))
        self.order.refresh_from_db()
        self.assertTrue(self.order.notified_whatsapp)
        self.assertTrue(OrderHistory.objects.filter(order=self.order, action="whatsapp_enviado").exists())

    def test_envio_de_arquivo_do_pedido(self):
        self.receber_texto()
        conversa = Conversa.objects.get()
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                anexo = OrderAttachment(order=self.order, original_name="arte.pdf", content_type="application/pdf", size=8, created_by=self.admin)
                anexo.file.save("arte.pdf", SimpleUploadedFile("arte.pdf", b"%PDF-1.4"), save=True)
                r = self.c_ana.post(reverse("whatsapp:api_enviar_anexo_pedido", args=[conversa.pk]), data=json.dumps({"anexo": anexo.pk}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        msg = Mensagem.objects.get(pk=r.json()["mensagem"]["id"])
        self.assertEqual((msg.tipo, msg.pedido), ("documento", self.order))
        outro = Order.objects.create(number="7002", client_name="Outro", client_whatsapp="11911112222", total_amount=Decimal("10"), created_by=self.admin)
        alheio = OrderAttachment.objects.create(order=outro, original_name="x.pdf", content_type="application/pdf", size=1, created_by=self.admin)
        r = self.c_ana.post(reverse("whatsapp:api_enviar_anexo_pedido", args=[conversa.pk]), data=json.dumps({"anexo": alheio.pk}), content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_card_e_detalhe_tem_atalhos(self):
        r = self.c_ana.get(reverse("production:detail", args=[self.order.pk]))
        self.assertContains(r, reverse("whatsapp:abrir_pedido", args=[self.order.pk]))
        self.assertContains(r, reverse("payments:link_confirmar", args=[self.order.pk]))
        r = self.c_ana.get(reverse("production:kanban"))
        self.assertContains(r, reverse("whatsapp:abrir_pedido", args=[self.order.pk]))
