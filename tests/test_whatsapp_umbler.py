"""Integração com a Umbler Talk: cliente HTTP, webhook (formato oficial), envio, mídia, apagar, status e canais.

Nenhum teste fala com a Umbler de verdade: o urlopen ou o cliente são substituídos.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.whatsapp import services
from apps.whatsapp.models import Conversa, Instancia, Mensagem
from apps.whatsapp.umbler import Resposta, UmblerClient, UmblerNaoConfigurada, e164
from apps.whatsapp.umbler_parser import interpretar_umbler

SEGREDO = "segredo-umbler-teste"
_TMP = tempfile.mkdtemp(prefix="pf_umbler_test_")


def webhook_message(*, msg_id="MsgAAAAAAAAAAAA1", texto="Olá 😀", source="Contact", tipo="Text", telefone="+5584999991234",
                    canal_id="CanalAAAAAAAAAA1", canal_tel="+5584988880001", evento_id="EvtAAAAAAAAAAAA1", estado="Received",
                    privada=False, contact_type="DirectMessage", arquivo=None) -> dict:
    """Payload no formato documentado (PascalCase, BasicChatModel em Payload.Content)."""
    mensagem = {
        "Id": msg_id, "Content": texto, "MessageType": tipo, "Source": source, "IsPrivate": privada,
        "MessageState": estado, "EventAtUTC": "2026-11-17T15:00:00.000Z",
    }
    if arquivo:
        mensagem["File"] = arquivo
    return {
        "Type": "Message",
        "EventDate": "2026-11-17T15:00:01.3135533Z",
        "EventId": evento_id,
        "Payload": {"Type": "Chat", "Content": {
            "Id": "ChatAAAAAAAAAAA1",
            "Contact": {"Id": "CtAAAAAAAAAAAAA1", "Name": "Maria Cliente", "PhoneNumber": telefone, "ContactType": contact_type},
            "Channel": {"Id": canal_id, "Name": "Ana", "PhoneNumber": canal_tel},
            "LastMessage": mensagem,
        }},
    }


class FakeUmbler:
    """Substitui o UmblerClient no provedor."""

    chamadas: list[tuple] = []
    resposta_envio = Resposta(True, 200, {"id": "SentAAAAAAAAAAA1", "messageState": "Processing"})
    estado_mensagem = "Read"
    configurado = True

    def __init__(self, *a, **k):
        pass

    @classmethod
    def reset(cls):
        cls.chamadas = []
        cls.resposta_envio = Resposta(True, 200, {"id": "SentAAAAAAAAAAA1", "messageState": "Processing"})
        cls.estado_mensagem = "Read"

    def enviar_texto(self, **kw):
        FakeUmbler.chamadas.append(("texto", kw))
        return FakeUmbler.resposta_envio

    def enviar_arquivo(self, **kw):
        FakeUmbler.chamadas.append(("arquivo", {k: v for k, v in kw.items() if k != "conteudo"}))
        return Resposta(True, 200, {"id": "SentFileAAAAAAA1", "messageState": "Sent"})

    def apagar(self, id_mensagem, *, para_todos):
        FakeUmbler.chamadas.append(("apagar", {"id": id_mensagem, "para_todos": para_todos}))
        return Resposta(True, 200, {})

    def mensagem(self, id_mensagem):
        FakeUmbler.chamadas.append(("mensagem", {"id": id_mensagem}))
        return Resposta(True, 200, {"id": id_mensagem, "messageState": FakeUmbler.estado_mensagem})

    def baixar_arquivo_da_mensagem(self, id_mensagem, limite):
        FakeUmbler.chamadas.append(("baixar", {"id": id_mensagem}))
        return b"%PDF-1.4 teste", "application/pdf", "orcamento.pdf"

    def canal(self, canal_id):
        return {"id": canal_id, "state": "Live", "phoneNumber": "+5584988880001"}

    def canais(self):
        return [
            {"id": "CanalAAAAAAAAAA1", "name": "Ana Vendas", "phoneNumber": "+5584988880001", "state": "Live"},
            {"id": "CanalBBBBBBBBBB2", "name": "Empresa", "phoneNumber": "+5584988880002", "state": "Offline"},
            {"id": "InstaCCCCCCCCCC3", "name": "Instagram", "state": "Live"},
        ]


class FakeResp:
    def __init__(self, corpo: bytes, status=200):
        self._corpo, self.status = corpo, status

    def read(self, *a):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@override_settings(UMBLER_API_TOKEN="token-falso", UMBLER_ORGANIZATION_ID="OrgAAAAAAAAAAAA1", UMBLER_API_URL="https://umbler.test.invalid/api")
class ClienteUmblerTests(TestCase):
    def test_envio_de_texto_em_e164_com_bearer(self):
        with patch("apps.whatsapp.umbler.urllib.request.urlopen", return_value=FakeResp(b'{"id":"X1","messageState":"Processing"}')) as uo:
            res = UmblerClient().enviar_texto(de="+55 84 98888-0001", para="(84) 99999-1234", texto="Oi ✅", nome_contato="Maria")
        req = uo.call_args.args[0]
        self.assertTrue(res.ok)
        self.assertEqual(req.full_url, "https://umbler.test.invalid/api/v1/messages/simplified/")
        self.assertEqual(req.get_header("Authorization"), "Bearer token-falso")
        corpo = json.loads(req.data.decode("utf-8"))
        self.assertEqual(corpo, {"toPhone": "+5584999991234", "fromPhone": "+5584988880001", "organizationId": "OrgAAAAAAAAAAAA1",
                                 "message": "Oi ✅", "skipReassign": True, "contactName": "Maria"})

    def test_arquivo_vai_em_multipart(self):
        with patch("apps.whatsapp.umbler.urllib.request.urlopen", return_value=FakeResp(b'{"id":"X2"}')) as uo:
            UmblerClient().enviar_arquivo(de="+5584988880001", para="84999991234", conteudo=b"%PDF", nome_arquivo="arte.pdf",
                                          mimetype="application/pdf", legenda="Sua arte")
        req = uo.call_args.args[0]
        self.assertIn("multipart/form-data; boundary=", req.get_header("Content-type"))
        self.assertIn(b'name="File"; filename="arte.pdf"', req.data)
        self.assertIn(b'name="ToPhone"\r\n\r\n+5584999991234', req.data)
        self.assertIn(b'name="Message"\r\n\r\nSua arte', req.data)

    def test_apagar_para_todos_usa_query_oficial(self):
        with patch("apps.whatsapp.umbler.urllib.request.urlopen", return_value=FakeResp(b"{}")) as uo:
            UmblerClient().apagar("MsgX", para_todos=True)
        req = uo.call_args.args[0]
        self.assertEqual(req.get_method(), "DELETE")
        self.assertEqual(req.full_url, "https://umbler.test.invalid/api/v1/messages/MsgX/?organizationId=OrgAAAAAAAAAAAA1&deleteForEveryone=true")

    def test_erro_http_nao_vaza_corpo_e_nao_configurado(self):
        import urllib.error

        erro = urllib.error.HTTPError("u", 400, "Bad", {}, io.BytesIO(b'{"title":"Invalid phone","detail":"+5584999991234 texto do cliente"}'))
        with patch("apps.whatsapp.umbler.urllib.request.urlopen", side_effect=erro), self.assertLogs("whatsapp", "WARNING") as logs:
            res = UmblerClient().enviar_texto(de="+5584988880001", para="84999991234", texto="segredo do cliente")
        self.assertFalse(res.ok)
        self.assertEqual(res.erro, "HTTP 400: Invalid phone")
        self.assertNotIn("segredo do cliente", "".join(logs.output))
        with self.assertRaises(UmblerNaoConfigurada):
            UmblerClient(token="").enviar_texto(de="+1", para="+2", texto="x")

    def test_e164(self):
        self.assertEqual(e164("84 9999-1234"), "+5584999991234")


class ParserUmblerTests(TestCase):
    def test_mensagem_do_contato(self):
        r = interpretar_umbler(webhook_message())
        self.assertEqual((r["evento_id"], r["canal_id"], r["canal_telefone"]), ("EvtAAAAAAAAAAAA1", "CanalAAAAAAAAAA1", "5584988880001"))
        ev = r["eventos"][0]
        self.assertEqual((ev["id"], ev["telefone"], ev["de_mim"], ev["texto"], ev["tipo"], ev["nome"]),
                         ("MsgAAAAAAAAAAAA1", "5584999991234", False, "Olá 😀", "texto", "Maria Cliente"))

    def test_mensagem_da_equipe_e_camelcase(self):
        payload = json.loads(json.dumps(webhook_message(source="Member")).replace('"LastMessage"', '"lastMessage"').replace('"Source"', '"source"'))
        self.assertTrue(interpretar_umbler(payload)["eventos"][0]["de_mim"])

    def test_nota_privada_grupo_reacao_e_outros_eventos_ignorados(self):
        self.assertEqual(interpretar_umbler(webhook_message(privada=True))["eventos"], [])
        self.assertEqual(interpretar_umbler(webhook_message(contact_type="Group"))["eventos"], [])
        self.assertEqual(interpretar_umbler(webhook_message(tipo="Reaction"))["eventos"], [])
        outro = webhook_message()
        outro["Type"] = "ChatClosed"
        self.assertEqual(interpretar_umbler(outro)["eventos"], [])

    def test_midia_e_mensagem_apagada(self):
        ev = interpretar_umbler(webhook_message(tipo="File", texto="", arquivo={"Url": "https://cdn.x/a.pdf", "ContentType": "application/pdf", "OriginalName": "orc.pdf", "Caption": "orçamento"}))["eventos"]
        self.assertEqual((ev[0]["tipo"], ev[0]["texto"], ev[0]["arquivo_nome"], ev[0]["midia"]), ("documento", "orçamento", "orc.pdf", {"umbler_id": "MsgAAAAAAAAAAAA1"}))
        self.assertNotIn("cdn.x", json.dumps(ev))  # a URL do webhook não é usada para baixar
        apagada = interpretar_umbler(webhook_message(estado="Deleted"))["eventos"]
        self.assertEqual(apagada[-1], {"tipo_evento": "revogacao", "id": "MsgAAAAAAAAAAAA1"})


@override_settings(UMBLER_WEBHOOK_SECRET=SEGREDO, UMBLER_API_TOKEN="token-falso", UMBLER_ORGANIZATION_ID="OrgAAAAAAAAAAAA1", WHATSAPP_MEDIA_ROOT=Path(_TMP))
class FluxoUmblerTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP, ignore_errors=True)

    def setUp(self):
        FakeUmbler.reset()
        p = patch("apps.whatsapp.provedores.UmblerClient", FakeUmbler)
        p.start()
        self.addCleanup(p.stop)
        self.admin = User.objects.create_user(email="admin@pf.test", password="x", name="Admin", role=User.Role.ADMINISTRATOR)
        self.ana = User.objects.create_user(email="ana@pf.test", password="x", name="Ana", role=User.Role.EMPLOYEE, sector=User.Sector.ATENDIMENTO)
        self.inst = Instancia.objects.create(nome="umbler_ana", apelido="Ana", vendedora=self.ana, canal_id="CanalAAAAAAAAAA1", telefone_canal="+5584988880001")
        self.url = reverse("whatsapp:webhook_umbler", args=[SEGREDO])
        self.c_ana = Client()
        self.c_ana.force_login(self.ana)

    def post(self, payload, url=None):
        return Client(enforce_csrf_checks=True).post(url or self.url, data=json.dumps(payload), content_type="application/json")

    def test_provedor_padrao_e_umbler(self):
        self.assertEqual(self.inst.provedor, "umbler")

    def test_webhook_recebe_e_e_idempotente_pelo_event_id(self):
        r = self.post(webhook_message())
        self.assertEqual((r.status_code, r.json()["processados"]), (200, 1))
        conversa = Conversa.objects.get()
        self.assertEqual((conversa.instancia, conversa.telefone, conversa.nome, conversa.nao_lidas), (self.inst, "5584999991234", "Maria Cliente", 1))
        self.assertEqual(self.post(webhook_message()).json().get("repetido"), True)  # re-tentativa da Umbler
        self.post(webhook_message(evento_id="EvtOutroAAAAAAA2"))  # mesmo id de mensagem em outro evento
        self.assertEqual(Mensagem.objects.count(), 1)

    def test_segredo_invalido_canal_desconhecido_e_por_telefone(self):
        self.assertEqual(self.post(webhook_message(), url=reverse("whatsapp:webhook_umbler", args=["errado"])).status_code, 403)
        with override_settings(UMBLER_WEBHOOK_SECRET=""):
            self.assertEqual(self.post(webhook_message()).status_code, 403)
        self.assertTrue(self.post(webhook_message(canal_id="Desconhecido", canal_tel="+5511900000000")).json()["ignorado"])
        # Canal sem id cadastrado é achado pelo telefone
        r = self.post(webhook_message(canal_id="IdNovoAAAAAAAAA9", evento_id="EvtTelAAAAAAAAA3"))
        self.assertEqual(r.json()["processados"], 1)
        self.assertEqual(Mensagem.objects.count(), 1)

    def test_resposta_pelo_sistema_e_eco_do_webhook_sem_duplicar(self):
        self.post(webhook_message())
        conversa = Conversa.objects.get()
        r = self.c_ana.post(reverse("whatsapp:api_enviar", args=[conversa.pk]), data=json.dumps({"texto": "Pedido pronto ✅"}), content_type="application/json")
        msg = Mensagem.objects.get(pk=r.json()["mensagem"]["id"])
        tipo, kw = FakeUmbler.chamadas[-1]
        self.assertEqual((tipo, kw["de"], kw["para"], kw["texto"]), ("texto", "+5584988880001", "5584999991234", "Pedido pronto ✅"))
        self.assertEqual((msg.status, msg.id_externo), ("pendente", "SentAAAAAAAAAAA1"))  # Processing = ainda na fila
        # A Umbler devolve a mesma mensagem pelo webhook (Source=Member)
        self.post(webhook_message(msg_id="SentAAAAAAAAAAA1", texto="Pedido pronto ✅", source="Member", evento_id="EvtEcoAAAAAAAAA4"))
        self.assertEqual(conversa.mensagens.filter(direcao="out").count(), 1)
        # Mensagem enviada pela equipe direto na Umbler aparece no Print
        self.post(webhook_message(msg_id="DoAppAAAAAAAAAA5", texto="Enviei pela Umbler", source="Member", evento_id="EvtAppAAAAAAAAA5"))
        externa = Mensagem.objects.get(id_externo="DoAppAAAAAAAAAA5")
        self.assertEqual((externa.direcao, externa.origem), ("out", "celular"))

    def test_falha_da_umbler_fica_registrada(self):
        self.post(webhook_message())
        conversa = Conversa.objects.get()
        FakeUmbler.resposta_envio = Resposta(False, 400, {}, "HTTP 400: Invalid phone")
        msg = services.enviar_texto(conversa, "teste", usuario=self.ana)
        self.assertEqual(msg.status, "falhou")
        self.assertIn("Invalid phone", msg.erro)

    def test_canal_sem_telefone_nao_envia(self):
        self.post(webhook_message())
        Instancia.objects.filter(pk=self.inst.pk).update(telefone_canal="")
        msg = services.enviar_texto(Conversa.objects.select_related("instancia").get(), "oi", usuario=self.ana)
        self.assertEqual(msg.status, "falhou")
        self.assertIn("telefone do canal", msg.erro)

    def test_status_e_revogacao_pelo_comando(self):
        self.post(webhook_message())
        conversa = Conversa.objects.get()
        msg = services.enviar_texto(conversa, "oi", usuario=self.ana)
        saida = io.StringIO()
        call_command("whatsapp_atualizar_status", stdout=saida)
        msg.refresh_from_db()
        self.assertEqual(msg.status, "lida")
        self.assertIn("lida=1", saida.getvalue())
        FakeUmbler.resposta_envio = Resposta(True, 200, {"id": "OutraAAAAAAAAAA6", "messageState": "Sent"})
        outra = services.enviar_texto(conversa, "vou apagar", usuario=self.ana)
        FakeUmbler.estado_mensagem = "Deleted"
        call_command("whatsapp_atualizar_status", stdout=io.StringIO())
        self.assertIsNotNone(Mensagem.objects.get(pk=outra.pk).revogada_em)

    def test_apagar_para_todos_e_midia_sob_demanda(self):
        self.post(webhook_message())
        conversa = Conversa.objects.get()
        enviada = services.enviar_texto(conversa, "apagar", usuario=self.ana)
        Mensagem.objects.filter(pk=enviada.pk).update(status="enviada")
        r = self.c_ana.post(reverse("whatsapp:api_apagar", args=[enviada.pk]), data=json.dumps({"escopo": "todos"}), content_type="application/json")
        self.assertTrue(r.json()["estado"]["revogada"])
        self.assertEqual(FakeUmbler.chamadas[-1], ("apagar", {"id": "SentAAAAAAAAAAA1", "para_todos": True}))
        self.post(webhook_message(msg_id="ArqAAAAAAAAAAAA7", tipo="File", texto="", evento_id="EvtArqAAAAAAAAA7",
                                  arquivo={"ContentType": "application/pdf", "OriginalName": "orc.pdf"}))
        recebida = Mensagem.objects.get(id_externo="ArqAAAAAAAAAAAA7")
        r = self.c_ana.get(reverse("whatsapp:midia", args=[recebida.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 teste")
        self.assertEqual(FakeUmbler.chamadas[-1], ("baixar", {"id": "ArqAAAAAAAAAAAA7"}))

    def test_envio_de_arquivo(self):
        self.post(webhook_message())
        conversa = Conversa.objects.get()
        msg = services.enviar_midia(conversa, services.Arquivo(b"%PDF", "arte.pdf", "application/pdf"), legenda="Arte", usuario=self.ana)
        self.assertEqual((msg.status, msg.id_externo), ("enviada", "SentFileAAAAAAA1"))
        tipo, kw = FakeUmbler.chamadas[-1]
        self.assertEqual((tipo, kw["nome_arquivo"], kw["legenda"]), ("arquivo", "arte.pdf", "Arte"))

    def test_importar_canais_e_verificar_conexao(self):
        c = Client()
        c.force_login(self.admin)
        with patch("apps.whatsapp.views.UmblerClient", FakeUmbler):
            r = c.post(reverse("whatsapp:instancias"), {"acao": "importar_umbler"})
        self.assertEqual(r.status_code, 302)
        empresa = Instancia.objects.get(canal_id="CanalBBBBBBBBBB2")
        self.assertEqual((empresa.provedor, empresa.telefone_canal, empresa.estado), ("umbler", "+5584988880002", "close"))
        self.assertFalse(Instancia.objects.filter(canal_id="InstaCCCCCCCCCC3").exists())  # canal sem telefone
        self.assertEqual(Instancia.objects.filter(canal_id="CanalAAAAAAAAAA1").count(), 1)  # já existia: atualizado
        r = c.post(reverse("whatsapp:instancia_acao", args=[empresa.pk, "estado"]))
        self.assertEqual(r.json()["estado"], "open")
        r = c.post(reverse("whatsapp:instancia_acao", args=[empresa.pk, "vendedora"]), {"vendedora": str(self.ana.pk)})
        empresa.refresh_from_db()
        self.assertEqual(empresa.vendedora, self.ana)
        r = c.post(reverse("whatsapp:instancia_acao", args=[empresa.pk, "conectar"]))
        self.assertEqual(r.status_code, 400)  # na Umbler a conexão é feita no painel dela

    @override_settings(WHATSAPP_WEBHOOK_BASE_URL="https://print.exemplo.test")
    def test_tela_mostra_url_do_webhook_so_para_admin(self):
        c = Client()
        c.force_login(self.admin)
        r = c.get(reverse("whatsapp:instancias"))
        self.assertContains(r, f"https://print.exemplo.test/chat/webhook/umbler/{SEGREDO}/")
        self.assertNotContains(r, "token-falso")
        self.assertEqual(self.c_ana.get(reverse("whatsapp:instancias")).status_code, 403)
