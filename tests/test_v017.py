"""0.17.0: senhas Argon2id + pepper fora do banco, "Esqueceu conta/senha", código de nova senha pelo adm,
chave vencida de conta (não é apagada, renova a qualquer momento) e sequência congelada enquanto vencida."""
import secrets
import unittest
from datetime import date, timedelta

from artemis.core import achievements as ach
from artemis.server import app as server
from artemis.server.db import _iso, utcnow
from tests import test_server as ts

PW = "Senha_1!"


class StreakFreezeTests(unittest.TestCase):
    D = date(2026, 11, 10)

    def days(self, *offsets):
        return {self.D + timedelta(days=o) for o in offsets}

    def test_missed_day_breaks(self):
        self.assertEqual(ach.current_streak(self.days(0, 1, 3, 4), ref=self.D + timedelta(days=4)), 2)

    def test_frozen_days_pause_without_breaking(self):
        days = self.days(0, 1, 5, 6)
        frozen = self.days(2, 3, 4)  # chave vencida do dia 2 ao 4
        self.assertEqual(ach.current_streak(days, ref=self.D + timedelta(days=6), frozen=frozen), 4)
        self.assertEqual(ach.runs(days, frozen), [(self.D, 4)])
        # sem o congelamento seriam duas sequências
        self.assertEqual(ach.runs(days), [(self.D, 2), (self.D + timedelta(days=5), 2)])

    def test_freeze_does_not_save_a_real_miss(self):
        days = self.days(0, 1, 5, 6)
        frozen = self.days(2, 3)  # dia 4 não estava vencida e não teve envio: perdeu
        self.assertEqual(ach.current_streak(days, ref=self.D + timedelta(days=6), frozen=frozen), 2)

    def test_reward_counts_across_pause(self):
        days = {self.D + timedelta(days=i) for i in range(35) if not 10 <= i < 15}  # 30 dias com envio
        frozen = self.days(10, 11, 12, 13, 14)
        self.assertEqual(len(ach.streak_rewards(days, frozen)), 1)
        self.assertEqual(ach.streak_rewards(days), [])


class V017Tests(unittest.TestCase):
    setUp = ts.ServerTests.setUp
    h = ts.ServerTests.h
    verify = ts.ServerTests.verify
    admin = property(lambda self: {"X-Admin-Token": server.CONFIG["admin_token"]})

    def tearDown(self):
        ts.ServerTests.tearDown(self)
        server._login_fails.clear()
        server._login_blocked.clear()
        server._lost_login_hits.clear()

    def register(self):
        name = "conta" + secrets.token_hex(4)
        r = self.client.post("/api/account/register", json={"username": name, "password": PW, "confirm": PW})
        self.assertEqual(r.status_code, 200, r.text)
        return name, r.json()

    def test_password_hash_is_argon2_with_pepper_outside_db(self):
        name, _ = self.register()
        stored = server.store._conn.execute("SELECT pw_hash FROM accounts WHERE username = ?", (name,)).fetchone()[0]
        self.assertTrue(stored.startswith("argon2p$$argon2id$"))
        self.assertNotIn(PW, stored)
        self.assertNotIn(server.store.pepper, stored)
        # o pepper não está em lugar nenhum do banco
        for (table,) in server.store._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in server.store._conn.execute(f"SELECT * FROM {table}").fetchall():
                self.assertNotIn(server.store.pepper, " ".join(str(v) for v in row), table)
        # com outro pepper (banco copiado sem o server.json) a senha certa não confere
        real = server.store.pepper
        try:
            server.store.pepper = secrets.token_hex(32)
            self.assertIsNone(server.store.check_password(name, PW))
        finally:
            server.store.pepper = real
        self.assertIsNotNone(server.store.check_password(name, PW))

    def test_old_pbkdf2_hash_still_works_and_is_upgraded(self):
        name, _ = self.register()
        salt = "ab" * 16
        old = f"pbkdf2_sha256$1000${salt}${server.store._hash_pw(PW, salt, 1000)}"
        server.store._conn.execute("UPDATE accounts SET pw_hash = ? WHERE username = ?", (old, name))
        self.assertIsNotNone(server.store.check_password(name, PW))
        stored = server.store._conn.execute("SELECT pw_hash FROM accounts WHERE username = ?", (name,)).fetchone()[0]
        self.assertTrue(stored.startswith("argon2p$"))

    def test_forgot_login_request_and_reset_code(self):
        name, acc = self.register()
        r = self.client.post("/api/recovery/login", json={"whatsapp": "+56 9 1234 5678", "username": name.upper()})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.post("/api/recovery/login", json={"whatsapp": "12"}).status_code, 422)
        items = [x for x in self.client.get("/api/admin/recovery", headers=self.admin).json() if x["kind"] == "login"]
        item = next(x for x in items if x["whatsapp"] == "56912345678")
        self.assertEqual(item["reason_label"], "Conta/senha: esqueceu a conta ou a senha")
        self.assertEqual([c["username"] for c in item["candidates"]], [name])
        # adm gera o código; nunca vê a senha
        self.assertEqual(self.client.post(f"/api/admin/accounts/{item['candidates'][0]['id']}/reset-code").status_code, 401)
        code = self.client.post(f"/api/admin/accounts/{item['candidates'][0]['id']}/reset-code", headers=self.admin).json()["code"]
        self.assertTrue(code.startswith("SENHA-"))
        bad = self.client.post("/api/account/reset", json={"username": name, "code": "SENHA-ERRAD-OOOOO", "password": "nova_123"})
        self.assertEqual(bad.status_code, 401)
        ok = self.client.post("/api/account/reset", json={"username": name, "code": code.lower(), "password": "nova_123",
                                                           "confirm": "nova_123"})
        self.assertEqual(ok.status_code, 200, ok.text)
        # sessões antigas caem; a senha velha não entra mais; o código não serve duas vezes
        self.assertEqual(self.client.post("/api/account/resume", json={}, headers={"X-Account-Token": acc["token"]}).status_code, 401)
        self.assertEqual(self.client.post("/api/account/login", json={"username": name, "password": PW}).status_code, 401)
        self.assertEqual(self.client.post("/api/account/login", json={"username": name, "password": "nova_123"}).status_code, 200)
        again = self.client.post("/api/account/reset", json={"username": name, "code": code, "password": "outra_123"})
        self.assertEqual(again.status_code, 401)

    def test_forgot_login_limit_per_ip(self):
        for _ in range(server.LOST_LOGIN_PER_IP):
            self.assertEqual(self.client.post("/api/recovery/login", json={"whatsapp": "5521999990000"},
                                              headers={"X-Forwarded-For": "6.6.6.6"}).status_code, 200)
        self.assertEqual(self.client.post("/api/recovery/login", json={"whatsapp": "5521999990000"},
                                          headers={"X-Forwarded-For": "6.6.6.6"}).status_code, 429)

    def test_expired_account_key_is_kept_and_renews(self):
        name, acc = self.register()
        a = {"X-Account-Token": acc["token"]}
        token = self.verify("Hilay")[1].json()["token"]
        self.client.post("/api/account/link", headers={**self.h(token), **a})
        expired = _iso(utcnow() - timedelta(days=2))
        server.store._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?", (expired, self.key))
        server.store.purge_expired()
        self.assertIsNotNone(server.store.get_key(self.key))  # não foi apagada
        self.assertEqual(server.store.char_owner("Hilay"), self.key)  # personagens continuam
        self.assertEqual(self.client.get("/api/me", headers=self.h(token)).status_code, 401)  # mas sem acesso
        r = self.client.post("/api/account/login", json={"username": name, "password": PW}).json()
        self.assertTrue(r["key_expired"])
        self.assertIsNone(r["device_token"])
        r = self.client.post("/api/account/renew", headers={"X-Account-Token": r["token"]}).json()
        self.assertTrue(r["renewed"])
        self.assertFalse(r["key_expired"])
        self.assertTrue(r["device_token"])
        self.assertGreater(r["expires_at"], _iso(utcnow() + timedelta(days=6, hours=23)))
        # os dias vencidos ficaram guardados para congelar a sequência
        self.assertIn(ach.local_day(expired), server.store.pause_days(self.key))
        self.assertIn(ach.today(), server.store.pause_days(self.key))

    def test_orphan_expired_key_still_purged(self):
        k = server.store.create_key(1, "sem conta")["key"]
        server.store._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?", (_iso(utcnow() - timedelta(days=1)), k))
        server.store.purge_expired()
        self.assertIsNone(server.store.get_key(k))


if __name__ == "__main__":
    unittest.main()
