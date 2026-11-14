"""0.13.0: código vitalício ("amigo do adm"), histórico de entradas, uso das telas e loja (chave grátis)."""
import unittest
from datetime import timedelta

from artemis.server import app as server
from artemis.server.db import _iso, utcnow
from tests import test_server as ts


class V013Tests(unittest.TestCase):
    setUp = ts.ServerTests.setUp
    tearDown = ts.ServerTests.tearDown
    h = ts.ServerTests.h
    verify = ts.ServerTests.verify
    admin = property(lambda self: {"X-Admin-Token": server.CONFIG["admin_token"]})

    def test_lifetime_key_never_expires_and_hides_expiry(self):
        token = self.verify("Hilay")[1].json()["token"]
        self.assertEqual(self.client.post(f"/api/admin/keys/{self.key}/lifetime", json={"on": True}).status_code, 401)
        r = self.client.post(f"/api/admin/keys/{self.key}/lifetime", json={"on": True}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        server.store._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?",
                                   (_iso(utcnow() - timedelta(days=3)), self.key))
        server.store.purge_expired()
        auth = self.client.post("/api/auth", headers=self.h(token))
        self.assertEqual(auth.status_code, 200)
        self.assertIsNone(auth.json()["expires_at"])
        me = self.client.get("/api/me", headers=self.h(token)).json()
        self.assertIsNone(me["expires_at"])
        self.assertNotIn("lifetime", me)
        self.assertIsNone(self.client.get("/api/streak", headers=self.h(token)).json()["expires_at"])
        # renovar todos não mexe no vitalício
        self.client.post("/api/admin/keys/renew-all", json={"days": 30}, headers=self.admin)
        row = server.store._conn.execute("SELECT expires_at FROM access_keys WHERE key = ?", (self.key,)).fetchone()
        self.assertLess(row[0], _iso(utcnow()))
        # desligar um vitalício já vencido dá 7 dias (não some na hora)
        r = self.client.post(f"/api/admin/keys/{self.key}/lifetime", json={"on": False}, headers=self.admin)
        self.assertGreater(r.json()["expires_at"], _iso(utcnow() + timedelta(days=6)))

    def test_login_history(self):
        self.client.post("/api/auth", headers=self.h())  # sem aparelho liberado não conta
        self.assertEqual(server.store.logins(self.key), [])
        token = self.verify("Hilay")[1].json()["token"]  # verificar já conta como entrada
        self.client.post("/api/auth", headers={**self.h(token), "Origin": "http://127.0.0.1:5123"})  # em seguida: mesma entrada
        logins = self.client.get(f"/api/admin/keys/{self.key}/logins", headers=self.admin).json()
        self.assertEqual([x["client"] for x in logins], ["site"])
        server.store._conn.execute("UPDATE key_logins SET at = ?", (_iso(utcnow() - timedelta(hours=1)),))
        self.client.post("/api/auth", headers={**self.h(token), "Origin": "http://127.0.0.1:5123"})
        logins = self.client.get(f"/api/admin/keys/{self.key}/logins", headers=self.admin).json()
        self.assertEqual([x["client"] for x in logins], ["app", "site"])
        overview = {k["key"]: k for k in self.client.get("/api/admin/keys", headers=self.admin).json()}[self.key]
        self.assertEqual(overview["logins_7d"], 2)
        self.assertEqual(self.client.get(f"/api/admin/keys/{self.key}/logins").status_code, 401)

    def test_screen_stats(self):
        token = self.verify("Hilay")[1].json()["token"]
        self.assertEqual(self.client.post("/api/track", json={"page": "loot"}).status_code, 401)
        self.assertEqual(self.client.post("/api/track", json={"page": "<script>"}, headers=self.h(token)).status_code, 422)
        for body in ({"page": "loot"}, {"page": "loot"}, {"page": "loot", "action": True}, {"page": "news"}):
            self.assertEqual(self.client.post("/api/track", json=body, headers=self.h(token)).status_code, 200)
        rep = {s["page"]: s for s in self.client.get("/api/admin/screens?days=7", headers=self.admin).json()["screens"]}
        self.assertEqual((rep["loot"]["views"], rep["loot"]["actions"]), (2, 1))
        self.assertEqual(rep["news"]["actions"], 0)
        self.assertEqual(self.client.get("/api/admin/screens").status_code, 401)

    def test_renew_free_only_tops_up_to_7_days(self):
        token = self.verify("Hilay")[1].json()["token"]
        self.assertEqual(self.client.post("/api/key/renew-free", headers=self.h()).status_code, 401)
        # tem 30 dias: não mexe
        r = self.client.post("/api/key/renew-free", headers=self.h(token)).json()
        self.assertFalse(r["renewed"])
        self.assertGreaterEqual(r["days_left"], 29)
        # faltam 2 dias: volta para 7
        server.store._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?",
                                   (_iso(utcnow() + timedelta(days=2)), self.key))
        r = self.client.post("/api/key/renew-free", headers=self.h(token)).json()
        self.assertTrue(r["renewed"])
        self.assertEqual(r["days_left"], 6)  # 7 dias menos alguns segundos
        self.assertGreater(r["me"]["expires_at"], _iso(utcnow() + timedelta(days=6, hours=23)))
        # vitalício: nada a renovar e nada aparece
        server.store.set_lifetime(self.key, True)
        r = self.client.post("/api/key/renew-free", headers=self.h(token)).json()
        self.assertEqual((r["renewed"], r["me"]["expires_at"]), (False, None))

    def test_spoofed_forwarded_for_does_not_dodge_lockout(self):
        for i in range(server.FAIL_LIMIT):
            self.client.post("/api/auth", headers={"X-Access-Key": "ART-ERRA-DO00", "X-Forwarded-For": f"9.9.9.{i}, 5.5.5.5"})
        r = self.client.post("/api/auth", headers={"X-Access-Key": self.key, "X-Forwarded-For": "8.8.8.8, 5.5.5.5"})
        self.assertEqual(r.status_code, 429)

    def test_store_free_key(self):
        server.store._conn.execute("DELETE FROM store_claims")
        server.store.set_meta("store_free", "on")
        self.assertEqual(self.client.get("/api/store").json(), {"free": True, "free_days": 7})
        r = self.client.post("/api/store/free")
        self.assertEqual(r.status_code, 200, r.text)
        key = r.json()["key"]
        self.assertEqual(self.client.post("/api/auth", headers={"X-Access-Key": key}).status_code, 200)
        self.assertEqual(self.client.post("/api/store/free").status_code, 429)  # 1 por dia por pessoa
        server.store._conn.execute("DELETE FROM store_claims")
        self.client.post("/api/admin/store", json={"on": False}, headers=self.admin)
        self.assertEqual(self.client.post("/api/store/free").status_code, 403)
        self.assertFalse(self.client.get("/api/store").json()["free"])
        server.store.set_meta("store_free", "on")


if __name__ == "__main__":
    unittest.main()
