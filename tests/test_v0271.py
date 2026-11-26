"""0.27.1: XP das sessões solo entra no controle de XP quando não há highscore do personagem (fora do top 1000),
e adicionar na VIP List avisa se o personagem não tem cadastro no site (para oferecer o convite por WhatsApp)."""
import unittest
from datetime import datetime
from unittest import mock

from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.server import app as server
from tests import limpar_banco
from tests.test_server import COMMENTS, fake_fetch


def sessao(dia: str, xp: int, inicio: str = "10:00:00") -> dict:
    fim = "11:00:00"
    return {"started_at": f"{dia}T{inicio}", "ended_at": f"{dia}T{fim}", "duration_seconds": 3600,
            "session_label": "01:00h", "raw_xp": xp, "xp": xp, "supplies": 0, "balance": 0, "damage": 0,
            "damage_h": 0, "healing": 0, "healing_h": 0, "kills": [], "loot": []}


class XpSessaoTests(unittest.TestCase):
    def setUp(self):
        limpar_banco(server.store._conn)

    def test_sessoes_solo_contam_sem_highscore(self):
        hoje = datetime.now(server.BRT).date().isoformat()
        for i, xp in enumerate((1500, 2500)):
            d = sessao(hoje, xp, f"1{i}:00:00")
            server.store.add_solo("Sem Snap", f"fp-{i}", d)
        linhas = server._xp_rows(["Sem Snap"], 30)
        self.assertEqual(linhas[0]["gain"], 4000)
        self.assertEqual(linhas[0]["source"], "sessoes")
        self.assertIsNone(linhas[0]["xp"])  # sem highscore não existe XP total

    def test_highscore_tem_prioridade(self):
        hoje = datetime.now(server.BRT).date().isoformat()
        server.store.xp_save("Com Snap", "2026-11-21", 1000000)
        server.store.xp_save("Com Snap", hoje, 1000500)
        server.store.add_solo("Com Snap", "fp-x", sessao(hoje, 9999))
        linha = server._xp_rows(["Com Snap"], 30)[0]
        self.assertEqual(linha["source"], "highscore")
        self.assertEqual(linha["gain"], 500)

    def test_sem_sessao_nem_highscore_fica_vazio(self):
        linha = server._xp_rows(["Ninguem"], 30)[0]
        self.assertIsNone(linha["gain"])
        self.assertIsNone(linha["source"])


class VipConviteTests(unittest.TestCase):
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
        key = server.store.create_key(30, "convite-dono")["key"]
        self.dono = {"X-Access-Key": key, "X-Device-Token": self.login(key, "Dono Convite")}
        key2 = server.store.create_key(30, "convite-alvo")["key"]
        self.login(key2, "Alvo Convite")

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

    def test_add_avisa_quando_nao_tem_cadastro(self):
        r = self.client.post("/api/vip/add", json={"character": "Sem Cadastro"}, headers=self.dono)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIs(r.json()["has_account"], False)

    def test_add_com_cadastro_avisa_true(self):
        r = self.client.post("/api/vip/add", json={"character": "Alvo Convite"}, headers=self.dono)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIs(r.json()["has_account"], True)


if __name__ == "__main__":
    unittest.main()
