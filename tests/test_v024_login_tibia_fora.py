"""0.24.1: login não trava quando o TibiaData está fora do ar.

O código é gerado mesmo sem consultar o personagem (vale 4 horas), e só a conferência no comentário
depende do TibiaData. Personagem que não existe continua sendo recusado.
"""
import unittest
from datetime import datetime, timezone
from unittest import mock

from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.core.tibiadata import TibiaDataError
from artemis.server import app as server
from tests.test_server import COMMENTS, fake_fetch


def outage(*_a, **_k):
    raise TibiaDataError("O TibiaData não conseguiu responder por esse nome agora (HTTP 502).")


class LoginTibiaDownTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check):
            cache.clear()
        COMMENTS.clear()
        self.key = server.store.create_key(30, "login-fora")["key"]
        self.hdr = {"X-Access-Key": self.key}
        self.patches = [mock.patch.object(server, "fetch_experience", lambda *a, **k: None),
                        mock.patch.object(server.captcha, "verify", lambda *a, **k: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        mock.patch.stopall()

    def test_code_is_issued_while_tibiadata_is_down(self):
        with mock.patch.object(server, "fetch_character", outage):
            r = self.client.post("/api/verify/start", json={"character": "Fora Um"}, headers=self.hdr)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["unconfirmed"])
        self.assertTrue(body["code"].startswith("4RT3MI5-"))
        self.assertEqual(body["character"], "Fora Um")
        exp = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        left = (exp - datetime.now(timezone.utc)).total_seconds() / 60
        self.assertGreater(left, 200)  # ~240 minutos

    def test_check_waits_for_tibiadata_then_logs_in(self):
        with mock.patch.object(server, "fetch_character", outage):
            code = self.client.post("/api/verify/start", json={"character": "Fora Dois"}, headers=self.hdr).json()["code"]
        # TibiaData ainda fora: a conferência pede para tentar de novo, sem liberar o acesso
        with mock.patch.object(server, "fetch_character", outage):
            server._last_check.clear()
            r = self.client.post("/api/verify/check", json={"code": code}, headers=self.hdr)
        self.assertEqual(r.status_code, 503, r.text)
        self.assertNotIn("token", r.json())
        # TibiaData voltou e o código está no comentário: entra
        COMMENTS["fora dois"] = code
        server._char_cache.clear()
        server._last_check.clear()
        with mock.patch.object(server, "fetch_character", fake_fetch):
            r = self.client.post("/api/verify/check", json={"code": code}, headers=self.hdr)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("token", r.json())

    def test_nonexistent_character_is_still_refused(self):
        with mock.patch.object(server, "fetch_character", lambda *a, **k: None):
            r = self.client.post("/api/verify/start", json={"character": "Ninguem Existe"}, headers=self.hdr)
        self.assertEqual(r.status_code, 404, r.text)

    def test_invalid_name_is_refused_during_outage(self):
        # nome impossível no Tibia nem chega a consultar o TibiaData
        with mock.patch.object(server, "fetch_character", outage):
            r = self.client.post("/api/verify/start", json={"character": "xxx<script>"}, headers=self.hdr)
        self.assertEqual(r.status_code, 404, r.text)


if __name__ == "__main__":
    unittest.main()
