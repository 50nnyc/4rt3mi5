"""0.25.0: login com a porta de confiança (30 dias e verificação manual), XP do TibiaData em 30/90 dias
e ranking pessoal (lista privada de cada conta)."""
import unittest
from datetime import date, timedelta
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core.tibiadata import TibiaDataError
from artemis.server import app as server
from artemis.server.db import _iso, name_key, utcnow
from tests import limpar_banco
from tests.test_server import COMMENTS, fake_fetch


def outage(*_a, **_k):
    raise TibiaDataError("O TibiaData não conseguiu responder por esse nome agora (HTTP 502).")


class TrustAndRankingTests(unittest.TestCase):
    def setUp(self):
        limpar_banco(server.store._conn)
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails,
                      server._captcha_used):
            cache.clear()
        COMMENTS.clear()
        self.key = server.store.create_key(30, "v025")["key"]
        self.patches = [mock.patch.object(server, "fetch_character", fake_fetch),
                        mock.patch.object(server, "fetch_experience", lambda *a, **k: None),
                        mock.patch.object(server.captcha, "verify", lambda *a, **k: None),
                        # os testes de XP usam datas relativas a hoje: o início da contagem (21/11/2026) fica antes delas
                        mock.patch.object(server, "XP_TRACK_START", date(2000, 1, 1))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        mock.patch.stopall()

    def login(self, character):
        """Entra pelo fluxo normal (com o comentário) e devolve o token do aparelho."""
        hdr = {"X-Access-Key": self.key}
        code = self.client.post("/api/verify/start", json={"character": character}, headers=hdr).json()["code"]
        COMMENTS[character.lower()] = code
        server._last_check.clear()
        r = self.client.post("/api/verify/check", json={"code": code}, headers=hdr)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"]

    def start(self, character, token=None):
        hdr = {"X-Access-Key": self.key, **({"X-Device-Token": token} if token else {})}
        return self.client.post("/api/verify/start", json={"character": character}, headers=hdr)

    # ---------------------------------------------------------------- porta de confiança
    def test_known_device_skips_check_while_tibiadata_is_down(self):
        token = self.login("Fora Um")
        with mock.patch.object(server, "fetch_character", outage):
            r = self.start("Fora Um", token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["trusted"])
        self.assertNotIn("code", r.json())

    def test_recheck_after_30_days(self):
        token = self.login("Fora Dois")
        server.store._conn.execute("UPDATE char_trust SET verified_at = ? WHERE name_key = ?",
                                   (_iso(utcnow() - timedelta(days=31)), name_key("Fora Dois")))
        server.store._conn.commit()
        with mock.patch.object(server, "fetch_character", outage):
            r = self.start("Fora Dois", token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("code", r.json())  # voltou a pedir verificação (o código fica pendente com o TibiaData fora)

    def test_copied_key_on_new_device_still_needs_the_comment(self):
        self.login("Fora Tres")
        with mock.patch.object(server, "fetch_character", outage):
            r = self.start("Fora Tres")  # sem token de aparelho
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("code", r.json())

    def test_manual_verification_always_lets_in(self):
        self.login("Fora Quatro")
        r = self.client.post("/api/admin/char-trust", json={"character": "Fora Quatro", "manual": True},
                             headers={"X-Admin-Token": server.CONFIG["admin_token"]})
        self.assertEqual(r.status_code, 200, r.text)
        server.store._conn.execute("UPDATE char_trust SET verified_at = ? WHERE name_key = ?",
                                   (_iso(utcnow() - timedelta(days=400)), name_key("Fora Quatro")))
        server.store._conn.commit()
        with mock.patch.object(server, "fetch_character", outage):
            r = self.start("Fora Quatro")  # aparelho novo, TibiaData fora, verificação de anos atrás
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["trusted"])

    def test_manual_flag_is_not_undone_by_automatic_check(self):
        self.login("Fora Cinco")
        server.store.trust_upsert("Fora Cinco", manual=True)
        server.store.trust_upsert("Fora Cinco", manual=False)
        self.assertTrue(server.store.trust_info("Fora Cinco")["manual"])

    def test_admin_endpoint_needs_admin_token(self):
        r = self.client.post("/api/admin/char-trust", json={"character": "Fora Seis"})
        self.assertIn(r.status_code, (401, 403))

    # ---------------------------------------------------------------- XP 30/90 dias
    def test_xp_gain_over_30_and_90_days(self):
        token = self.login("Fora Sete")
        self.client.post("/api/xp-ranking/mine", json={"character": "Fora Sete"},
                         headers={"X-Access-Key": self.key, "X-Device-Token": token})
        today = date.today()
        s = server.store
        s.xp_save("Fora Sete", (today - timedelta(days=100)).isoformat(), 1_000)
        s.xp_save("Fora Sete", (today - timedelta(days=40)).isoformat(), 4_000)
        s.xp_save("Fora Sete", today.isoformat(), 10_000)
        r30 = self.client.get("/api/xp-ranking?days=30&scope=mine", headers={"X-Access-Key": self.key, "X-Device-Token": token})
        r90 = self.client.get("/api/xp-ranking?days=90&scope=mine", headers={"X-Access-Key": self.key, "X-Device-Token": token})
        self.assertEqual(r30.status_code, 200, r30.text)
        self.assertEqual(r30.json()["rows"][0]["gain"], 10_000 - 4_000)   # o ponto de 40 dias é o mais recente até 30 dias atrás
        self.assertEqual(r90.json()["rows"][0]["gain"], 10_000 - 1_000)   # 90 dias: a referência é o ponto de 100 dias
        self.assertFalse(r90.json()["rows"][0]["partial"])

    def test_xp_partial_when_history_is_shorter_than_window(self):
        token = self.login("Fora Oito")
        add = self.client.post("/api/xp-ranking/mine", json={"character": "Fora Oito"},
                               headers={"X-Access-Key": self.key, "X-Device-Token": token})
        self.assertEqual(add.status_code, 200, add.text)
        server.store.xp_save("Fora Oito", date.today().isoformat(), 5_000)
        server.store.xp_save("Fora Oito", (date.today() - timedelta(days=10)).isoformat(), 3_000)
        r = self.client.get("/api/xp-ranking?days=90&scope=mine", headers={"X-Access-Key": self.key, "X-Device-Token": token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["rows"]), 1, r.json())
        row = r.json()["rows"][0]
        self.assertTrue(row["partial"])
        self.assertEqual(row["gain"], 2_000)

    # ---------------------------------------------------------------- ranking pessoal
    def test_custom_ranking_is_private_to_the_account(self):
        token = self.login("Fora Nove")
        hdr = {"X-Access-Key": self.key, "X-Device-Token": token}
        r = self.client.post("/api/xp-ranking/mine", json={"character": "Amigo Um"}, headers=hdr)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["names"], ["Amigo Um"])
        self.assertEqual(self.client.post("/api/xp-ranking/mine", json={"character": "x<y"}, headers=hdr).status_code, 422)
        # outra conta não vê a lista desta
        other = server.store.create_key(30, "outra")["key"]
        self.assertEqual(server.store.custom_list(other), [])  # a lista é de cada conta
        self.assertEqual([c["name"] for c in server.store.custom_list(self.key)], ["Amigo Um"])
        r3 = self.client.delete("/api/xp-ranking/mine/Amigo%20Um", headers=hdr)
        self.assertEqual(r3.json()["names"], [])

    # ---------------------------------------------------------------- regras de 0.25.1
    def test_points_before_21_11_are_not_counted(self):
        token = self.login("Fora Dez")
        self.client.post("/api/xp-ranking/mine", json={"character": "Fora Dez"},
                         headers={"X-Access-Key": self.key, "X-Device-Token": token})
        hoje = date.today()
        cutoff = hoje - timedelta(days=20)
        s = server.store
        s.xp_save("Fora Dez", (cutoff - timedelta(days=5)).isoformat(), 1_000)  # antes do início: não conta
        s.xp_save("Fora Dez", cutoff.isoformat(), 3_000)
        s.xp_save("Fora Dez", hoje.isoformat(), 5_000)
        with mock.patch.object(server, "XP_TRACK_START", cutoff):
            r = self.client.get("/api/xp-ranking?days=30&scope=mine", headers={"X-Access-Key": self.key, "X-Device-Token": token})
        row = r.json()["rows"][0]
        self.assertEqual(row["gain"], 2_000)
        self.assertEqual(row["since"], cutoff.isoformat())
        self.assertTrue(row["partial"])

    def test_board_lists_every_registered_character(self):
        token = self.login("Fora Onze")
        r = self.client.get("/api/xp-ranking?days=30&scope=board", headers={"X-Access-Key": self.key, "X-Device-Token": token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("Fora Onze", [row["name"] for row in r.json()["rows"]])
        self.assertEqual(r.json()["update"]["hour"], 9)

    def test_note_disappears_after_90_days(self):
        token = self.login("Fora Doze Dois")
        hdr = {"X-Access-Key": self.key, "X-Device-Token": token}
        with mock.patch.object(server, "XP_NOTE_UNTIL", date.today() + timedelta(days=1)):
            on = self.client.get("/api/xp-ranking?scope=board", headers=hdr).json()
        with mock.patch.object(server, "XP_NOTE_UNTIL", date.today() - timedelta(days=1)):
            off = self.client.get("/api/xp-ranking?scope=board", headers=hdr).json()
        self.assertTrue(on["note_visible"])
        self.assertFalse(off["note_visible"])

    def test_next_update_is_0900_brasilia(self):
        from datetime import datetime
        brt = server.BRT
        self.assertEqual(server._seconds_until_next_update(datetime(2026, 11, 21, 8, 0, tzinfo=brt)), 3600)
        self.assertEqual(server._seconds_until_next_update(datetime(2026, 11, 21, 10, 0, tzinfo=brt)), 23 * 3600)

    def test_admin_can_take_the_snapshot_now(self):
        self.login("Fora Treze")
        with mock.patch.object(server, "fetch_experience", lambda *a, **k: (777, 0)):
            r = self.client.post("/api/admin/xp-snapshot", headers={"X-Admin-Token": server.CONFIG["admin_token"]})
            again = self.client.post("/api/admin/xp-snapshot", headers={"X-Admin-Token": server.CONFIG["admin_token"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertGreaterEqual(r.json()["saved"], 1)
        self.assertEqual(again.json()["saved"], 0)  # mesmo dia: nada duplicado
        self.assertEqual(self.client.post("/api/admin/xp-snapshot").status_code, 401)

    def test_daily_snapshot_saves_registered_characters(self):
        self.login("Fora Doze")
        with mock.patch.object(server, "fetch_experience", lambda *a, **k: (123_456, 0)):
            guardados = server._xp_snapshot_all()
        self.assertGreaterEqual(guardados, 1)
        hoje = server.datetime.now(server.BRT).date().isoformat()
        self.assertTrue(server.store.xp_has("Fora Doze", hoje))


if __name__ == "__main__":
    unittest.main()
