"""0.15.0: uma chave por conta (personagem em uma chave só), até 50 personagens, validação manual do adm,
chave nova sempre com 7 dias e renovação grátis só com menos de 3 dias."""
import unittest
from datetime import timedelta

from artemis.server import app as server
from artemis.server.db import _iso, utcnow
from tests import test_server as ts


class V015Tests(unittest.TestCase):
    setUp = ts.ServerTests.setUp
    tearDown = ts.ServerTests.tearDown
    h = ts.ServerTests.h
    verify = ts.ServerTests.verify
    admin = property(lambda self: {"X-Admin-Token": server.CONFIG["admin_token"]})

    def test_character_belongs_to_one_key(self):
        self.assertEqual(self.verify("Hilay")[1].status_code, 200)
        other = server.store.create_key(7, "outra")["key"]
        r = self.client.post("/api/verify/start", json={"character": "Hilay"}, headers={"X-Access-Key": other})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"], {"message": server.CHAR_TAKEN, "reason": "char_taken"})
        # o adm também não consegue pôr na outra chave sem tirar da primeira
        r = self.client.post(f"/api/admin/keys/{other}/chars", json={"character": "Hilay"}, headers=self.admin)
        self.assertEqual(r.status_code, 409)
        r = self.client.post(f"/api/admin/keys/{other}/trust", json={"character": "Hilay"}, headers=self.admin)
        self.assertEqual(r.status_code, 409)

    def test_verify_check_blocks_if_taken_meanwhile(self):
        r = self.client.post("/api/verify/start", json={"character": "Hilay"}, headers=self.h())
        code = r.json()["code"]
        other = server.store.create_key(7, "outra")["key"]
        server.store.add_char_manual(other, "Hilay")
        ts.COMMENTS["hilay"] = code
        r = self.client.post("/api/verify/check", json={"code": code}, headers=self.h())
        self.assertEqual(r.status_code, 409)

    def test_max_50_characters(self):
        token = self.verify("Hilay")[1].json()["token"]
        for i in range(server.store.MAX_CHARS_PER_KEY - 1):
            server.store.add_char_manual(self.key, f"Alt {i}")
        r = self.client.post("/api/verify/start", json={"character": "Mais Um"}, headers=self.h(token))
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/admin/keys/{self.key}/chars", json={"character": "Mais Um"}, headers=self.admin)
        self.assertEqual(r.status_code, 400)
        # personagem que já está na chave continua podendo verificar (aparelho novo)
        r = self.client.post("/api/verify/start", json={"character": "Hilay"}, headers=self.h(token))
        self.assertEqual(r.status_code, 200)

    def test_admin_manual_validation(self):
        self.assertEqual(self.client.post(f"/api/admin/keys/{self.key}/chars", json={"character": "Hilay"}).status_code, 401)
        r = self.client.post(f"/api/admin/keys/{self.key}/chars", json={"character": "Hilay"}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([c["name"] for c in r.json()["chars"]], ["Hilay"])
        row = server.store.validate_key(self.key)
        self.assertEqual((row["main_char"], row["trusted"]), ("Hilay", 0))  # vira main, mas não é contato de confiança
        r = self.client.post(f"/api/admin/keys/{self.key}/chars", json={"character": "naoexiste"}, headers=self.admin)
        self.assertEqual(r.status_code, 404)

    def test_new_keys_always_7_days(self):
        r = self.client.post("/api/admin/keys", json={"label": "x", "days": 30}, headers=self.admin)
        exp = r.json()["expires_at"]
        self.assertGreater(exp, _iso(utcnow() + timedelta(days=6, hours=23)))
        self.assertLess(exp, _iso(utcnow() + timedelta(days=7, minutes=1)))

    def test_renew_free_has_nothing_to_do(self):
        """0.20.0: a chave não vence, então a renovação grátis nunca muda nada."""
        server.store._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?",
                                   (_iso(utcnow() + timedelta(days=1)), self.key))
        server.store.add_char_manual(self.key, "Hilay")
        self.assertFalse(server.store.renew_free(self.key)[0])


if __name__ == "__main__":
    unittest.main()
