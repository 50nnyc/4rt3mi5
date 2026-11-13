import os
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

os.environ["ARTEMIS_DATA_DIR"] = tempfile.mkdtemp(prefix="artemis_test_")

from fastapi.testclient import TestClient  # noqa: E402

from artemis.core.tibiadata import CharacterInfo  # noqa: E402
from artemis.server import app as server  # noqa: E402
from artemis.server.db import _iso, utcnow  # noqa: E402
from tests.test_core import EXAMPLE  # noqa: E402
from tests.test_session import SOLO  # noqa: E402

COMMENTS: dict[str, str] = {}


def fake_fetch(name, timeout=10):
    if name.lower() == "naoexiste":
        return None
    return CharacterInfo(name=name.title(), level=100, vocation="Knight", world="Celebra",
                         comment=COMMENTS.get(name.lower(), ""))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server._char_cache.clear()
        server._last_check.clear()
        COMMENTS.clear()
        self.patch = mock.patch.object(server, "fetch_character", fake_fetch)
        self.patch.start()
        self.key = server.store.create_key(30, "teste")["key"]

    def tearDown(self):
        self.patch.stop()

    def h(self, token=""):
        return {"X-Access-Key": self.key, "X-Device-Token": token}

    def verify(self, character, token="", put_in_comment=True):
        r = self.client.post("/api/verify/start", json={"character": character}, headers=self.h(token))
        self.assertEqual(r.status_code, 200, r.text)
        code = r.json()["code"]
        if put_in_comment:
            COMMENTS[character.lower()] = f"meu char :) {code}"
        server._last_check.clear()
        return code, self.client.post("/api/verify/check", json={"code": code}, headers=self.h(token))

    def test_key_rules(self):
        bad = self.client.post("/api/auth", headers={"X-Access-Key": "ART-NAO-EXISTE"})
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(bad.json()["detail"]["message"], server.INVALID_KEY)
        self.assertEqual(self.client.post("/api/auth", headers={"X-Access-Key": self.key.lower()}).status_code, 200)
        with self.assertRaises(ValueError):
            server.store.create_key(31)
        server.store._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?",
                                   (_iso(utcnow() - timedelta(seconds=1)), self.key))
        self.assertEqual(self.client.post("/api/auth", headers=self.h()).status_code, 401)
        self.assertNotIn(self.key, [k["key"] for k in server.store.list_keys()])

    def test_needs_verification_before_use(self):
        r = self.client.get("/api/hunts/Hilay", headers=self.h())
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"]["reason"], "device")
        self.assertEqual(self.client.post("/api/verify/start", json={"character": "naoexiste"}, headers=self.h()).status_code, 404)
        code, r = self.verify("Hilay", put_in_comment=False)
        self.assertEqual(r.status_code, 409)  # código ainda não está no comentário

    def test_main_char_binding_blocks_copied_key(self):
        _, r = self.verify("Hilay")
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        self.assertEqual(r.json()["me"]["main_char"], "Hilay")
        self.assertEqual(self.client.get("/api/me", headers=self.h(token)).status_code, 200)
        # outra pessoa com o código copiado tenta usar o próprio personagem
        r = self.client.post("/api/verify/start", json={"character": "Intruso"}, headers=self.h())
        self.assertEqual(r.status_code, 403)
        # ...ou o personagem do dono, mas não consegue mexer no comentário dele
        COMMENTS.clear()
        _, r = self.verify("Hilay", put_in_comment=False)
        self.assertEqual(r.status_code, 409)
        # o dono, num segundo aparelho, consegue (verificando de novo)
        _, r = self.verify("Hilay")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["token"], token)

    def test_link_alt_and_change_main(self):
        token = self.verify("Hilay")[1].json()["token"]
        r = self.verify("Jioe", token=token)[1]
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["token"], token)  # mesmo aparelho
        names = {c["name"]: c["is_main"] for c in r.json()["me"]["chars"]}
        self.assertEqual(names, {"Hilay": True, "Jioe": False})
        me = self.client.post("/api/chars/main", json={"character": "jioe"}, headers=self.h(token)).json()
        self.assertEqual(me["main_char"], "Jioe")
        self.assertEqual(self.client.delete("/api/chars/Jioe", headers=self.h(token)).status_code, 400)  # main
        self.assertEqual(self.client.delete("/api/chars/Hilay", headers=self.h(token)).status_code, 200)

    def test_upload_only_for_linked_chars(self):
        token = self.verify("Hilay")[1].json()["token"]
        body = {"raw_text": EXAMPLE, "nickname": "Vcte"}
        r = self.client.post("/api/lootsplit", json=body, headers=self.h(token))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["message"], server.FORBIDDEN_UPLOAD)
        r = self.client.post("/api/lootsplit", json={**body, "nickname": "hilay"}, headers=self.h(token))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["hunt"]["profit_each"], 2_319_540)
        # qualquer aparelho liberado vê as hunts de qualquer jogador
        hunts = self.client.get("/api/hunts/atx buubo", headers=self.h(token)).json()["hunts"]
        self.assertTrue(any(h["profit_each"] == 2_319_540 for h in hunts))

    def test_stacker(self):
        token = self.verify("Jioe")[1].json()["token"]
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "jioe"}, headers=self.h(token))
        self.assertEqual(r.status_code, 200, r.text)
        again = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Jioe"}, headers=self.h(token))
        self.assertFalse(again.json()["created"])
        data = self.client.get("/api/stacker/Jioe", headers=self.h(token)).json()
        self.assertEqual(data["day"], "2026-11-04")
        self.assertEqual(data["lifetime"]["xp_per_hour"], round(7_684_000 / 1.5))
        self.assertEqual(self.client.get("/api/stacker/Ninguem", headers=self.h(token)).json()["lifetime"]["xp"], 0)

    def test_admin_requires_token_and_local_access(self):
        admin = {"X-Admin-Token": server.CONFIG["admin_token"]}
        self.assertEqual(self.client.get("/api/admin/keys").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/keys", headers={"X-Admin-Token": "errada"}).status_code, 401)
        # pela internet (ngrok manda X-Forwarded-For) é recusado mesmo com a senha certa
        via_tunnel = self.client.get("/api/admin/keys", headers={**admin, "X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(via_tunnel.status_code, 403)
        self.assertEqual(self.client.get("/admin", headers={"X-Forwarded-For": "1.2.3.4"}).status_code, 404)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/keys", headers=admin).status_code, 200)

    def test_admin_create_renew_and_trusted_contact(self):
        admin = {"X-Admin-Token": server.CONFIG["admin_token"]}
        k = self.client.post("/api/admin/keys", json={"label": "Amigo", "days": 7}, headers=admin).json()
        self.assertEqual(self.client.post("/api/admin/keys", json={"days": 31}, headers=admin).status_code, 422)
        r = self.client.post(f"/api/admin/keys/{k['key']}/renew", json={"days": 15}, headers=admin)
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()["expires_at"], k["expires_at"])
        # forçar main: o contato entra só com código + nick, sem código de verificação
        r = self.client.post(f"/api/admin/keys/{k['key']}/trust", json={"character": "hilay"}, headers=admin)
        self.assertEqual(r.json(), {"key": k["key"], "main_char": "Hilay", "trusted": True})
        h = {"X-Access-Key": k["key"]}
        start = self.client.post("/api/verify/start", json={"character": "Hilay"}, headers=h).json()
        self.assertIn("token", start)
        self.assertEqual(self.client.get("/api/me", headers={**h, "X-Device-Token": start["token"]}).json()["main_char"], "Hilay")
        # outro personagem continua bloqueado
        self.assertEqual(self.client.post("/api/verify/start", json={"character": "Intruso"}, headers=h).status_code, 403)
        overview = {x["key"]: x for x in self.client.get("/api/admin/keys", headers=admin).json()}[k["key"]]
        self.assertTrue(overview["trusted"])
        self.assertEqual(overview["devices"], 1)
        # sem confiança volta a exigir código de verificação
        self.client.post(f"/api/admin/keys/{k['key']}/untrust", headers=admin)
        self.assertIn("code", self.client.post("/api/verify/start", json={"character": "Hilay"}, headers=h).json())
        self.assertEqual(self.client.delete(f"/api/admin/keys/{k['key']}", headers=admin).status_code, 200)
        self.assertEqual(self.client.post("/api/auth", headers=h).status_code, 401)

    def test_renew_keeps_chars(self):
        self.verify("Hilay")
        k = server.store.renew_key(self.key, 10)
        self.assertEqual(k["main_char"], "Hilay")
        with self.assertRaises(ValueError):
            server.store.renew_key(self.key, 31)


if __name__ == "__main__":
    unittest.main()
