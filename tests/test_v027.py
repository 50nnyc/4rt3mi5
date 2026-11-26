"""0.27.0: VIP List. Quem adiciona pede o que quer ver; a outra pessoa aceita ou recusa o que compartilha.
Só vale o que foi pedido E aceito. Desligar tira os detalhes na hora; religar pede autorização de novo."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.server import app as server
from tests import limpar_banco
from tests.test_server import COMMENTS, fake_fetch


class VipListTests(unittest.TestCase):
    def setUp(self):
        limpar_banco(server.store._conn)
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails,
                      server._captcha_used):
            cache.clear()
        COMMENTS.clear()
        self.patches = [mock.patch.object(server, "fetch_character", fake_fetch),
                        mock.patch.object(server, "fetch_experience", lambda *a, **k: None),
                        mock.patch.object(server.captcha, "verify", lambda *a, **k: None)]
        for p in self.patches:
            p.start()
        self.dono_key = server.store.create_key(30, "vip-dono")["key"]
        self.alvo_key = server.store.create_key(30, "vip-alvo")["key"]
        self.dono = {"X-Access-Key": self.dono_key, "X-Device-Token": self.login(self.dono_key, "Dono Vip")}
        self.alvo = {"X-Access-Key": self.alvo_key, "X-Device-Token": self.login(self.alvo_key, "Alvo Vip")}

    def tearDown(self):
        mock.patch.stopall()

    def login(self, key, character):
        hdr = {"X-Access-Key": key}
        code = self.client.post("/api/verify/start", json={"character": character}, headers=hdr).json()["code"]
        COMMENTS[character.lower()] = code
        server._last_check.clear()
        r = self.client.post("/api/verify/check", json={"code": code}, headers=hdr)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"]

    def entry(self, nome="Alvo Vip"):
        lista = self.client.get("/api/vip/list", headers=self.dono).json()["entries"]
        return next(e for e in lista if e["name"] == nome)

    def test_full_consent_cycle(self):
        r = self.client.post("/api/vip/add", json={"character": "Alvo Vip"}, headers=self.dono)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.entry()["state"], "off")  # adicionar não pede nada ainda

        # o dono liga e pede skills + hunts: a pessoa ainda não respondeu
        self.assertEqual(self.client.post("/api/vip/Alvo%20Vip/share", json={"on": True, "scopes": ["skills", "hunts"]},
                                          headers=self.dono).status_code, 200)
        self.assertEqual(self.entry()["state"], "pending")
        self.assertEqual(self.client.get("/api/vip/view/Alvo%20Vip", headers=self.dono).json()["details"], {})
        convites = self.client.get("/api/vip/list", headers=self.alvo).json()["incoming"]
        self.assertEqual(len(convites), 1)
        self.assertEqual(convites[0]["owner_char"], "Dono Vip")  # o convite mostra quem pediu (personagem principal do dono)
        self.assertEqual(convites[0]["requested"], ["skills", "hunts"])

        # aceita só skills: hunts não vai
        link_id = convites[0]["id"]
        r = self.client.post(f"/api/vip/invites/{link_id}/answer", json={"accept": True, "scopes": ["skills"]}, headers=self.alvo)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.entry()["effective"], ["skills"])
        ficha = self.client.get("/api/vip/view/Alvo%20Vip", headers=self.dono).json()
        self.assertEqual(ficha["state"], "on")
        self.assertIn("skills", ficha["details"])
        self.assertNotIn("hunts", ficha["details"])

        # desliga: os detalhes somem na hora
        self.client.post("/api/vip/Alvo%20Vip/share", json={"on": False}, headers=self.dono)
        ficha = self.client.get("/api/vip/view/Alvo%20Vip", headers=self.dono).json()
        self.assertEqual(ficha["state"], "off")
        self.assertEqual(ficha["details"], {})

        # religa: precisa pedir de novo (resposta zerada)
        self.client.post("/api/vip/Alvo%20Vip/share", json={"on": True, "scopes": ["skills"]}, headers=self.dono)
        self.assertEqual(self.entry()["state"], "pending")
        self.assertEqual(len(self.client.get("/api/vip/list", headers=self.alvo).json()["incoming"]), 1)

    def test_decline_and_permissions(self):
        self.client.post("/api/vip/add", json={"character": "Alvo Vip"}, headers=self.dono)
        self.client.post("/api/vip/Alvo%20Vip/share", json={"on": True, "scopes": ["xp"]}, headers=self.dono)
        link_id = self.client.get("/api/vip/list", headers=self.alvo).json()["incoming"][0]["id"]
        # o próprio dono não pode responder ao convite dele
        self.assertEqual(self.client.post(f"/api/vip/invites/{link_id}/answer", json={"accept": True, "scopes": ["xp"]},
                                          headers=self.dono).status_code, 404)
        self.client.post(f"/api/vip/invites/{link_id}/answer", json={"accept": False, "scopes": []}, headers=self.alvo)
        self.assertEqual(self.entry()["state"], "declined")
        self.assertEqual(self.entry()["effective"], [])

    def test_cannot_add_own_character_or_invalid_name(self):
        self.assertEqual(self.client.post("/api/vip/add", json={"character": "Dono Vip"}, headers=self.dono).status_code, 422)
        self.assertEqual(self.client.post("/api/vip/add", json={"character": "x<y"}, headers=self.dono).status_code, 422)

    def test_amigos_tab_has_me_and_vip_entries_even_without_consent(self):
        self.client.post("/api/vip/add", json={"character": "Alvo Vip"}, headers=self.dono)
        linhas = self.client.get("/api/rank/amigos?sort=level", headers=self.dono).json()["rows"]
        nomes = {l["name"]: l["origin"] for l in linhas}
        self.assertEqual(nomes["Dono Vip"], "mine")
        self.assertEqual(nomes["Alvo Vip"], "vip")  # sem pedido aceito, ainda aparece


if __name__ == "__main__":
    unittest.main()
