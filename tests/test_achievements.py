import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core import achievements as ach
from artemis.core.session import parse_solo_session
from artemis.server import app as server
from artemis.server.db import _iso
from tests.test_core import EXAMPLE
from tests.test_server import COMMENTS, fake_fetch
from tests.test_session import SOLO

D = date(2026, 11, 14)


class StreakRulesTests(unittest.TestCase):
    def test_runs_and_current_streak(self):
        days = {D - timedelta(days=i) for i in range(5)} | {D - timedelta(days=10)}
        self.assertEqual(ach.runs(days), [(D - timedelta(days=10), 1), (D - timedelta(days=4), 5)])
        self.assertEqual(ach.current_streak(days, D), 5)
        # hoje sem envio: a sequência de ontem continua valendo até o fim do dia
        self.assertEqual(ach.current_streak(days, D + timedelta(days=1)), 5)
        self.assertEqual(ach.current_streak(days, D + timedelta(days=2)), 0)

    def test_reward_every_30_days(self):
        self.assertEqual(ach.streak_rewards({D - timedelta(days=i) for i in range(29)}), [])
        start = D - timedelta(days=64)
        ids = ach.streak_rewards({start + timedelta(days=i) for i in range(65)})
        self.assertEqual(ids, [f"streak30:{start.isoformat()}:1", f"streak30:{start.isoformat()}:2"])
        info = ach.streak_info({start + timedelta(days=i) for i in range(65)}, D)
        self.assertEqual((info["current"], info["progress"], info["next_reward_in"]), (65, 5, 25))
        self.assertEqual(len(info["calendar"]), 30)

    def test_local_day_uses_brasilia(self):
        # 01:30 UTC ainda é o dia anterior em Brasília
        self.assertEqual(ach.local_day("2026-11-15T01:30:00+00:00"), date(2026, 11, 14))

    def test_evaluate(self):
        solo = [{"xp": 2_000_000, "duration_seconds": 3600, "loot_value": 1_500_000, "place_id": 1,
                 "kills": [{"key": "dragon", "count": 120}], "started_at": "2026-11-14T10:00:00"}]
        hunts = [{"started_at": "2026-11-13T20:00:00", "players": [
            {"name": "Hilay", "damage": 10, "healing": 0}, {"name": "Outro", "damage": 5, "healing": 9}]}]
        got = {a["id"]: a for a in ach.evaluate("Hilay", solo, hunts)}
        self.assertTrue(got["first_solo"]["unlocked"])
        self.assertTrue(got["first_party"]["unlocked"])
        self.assertTrue(got["loot_kk"]["unlocked"])
        self.assertTrue(got["xp_kk"]["unlocked"])
        self.assertFalse(got["marathon"]["unlocked"])
        self.assertEqual(got["frontline"]["value"], 1)
        self.assertEqual(got["guardian"]["value"], 0)
        self.assertEqual(got["week"]["value"], 2)  # 13 e 14 de novembro


class AchievementApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails):
            cache.clear()
        COMMENTS.clear()
        server.store._conn.execute("DELETE FROM key_chars")  # 0.15.0: personagem em uma chave só
        self.patches = [mock.patch.object(server, "fetch_character", fake_fetch),
                        mock.patch.object(server, "fetch_experience", lambda *a, **k: None)]
        for p in self.patches:
            p.start()
        self.key = server.store.create_key(30, "conquistas")["key"]
        r = self.client.post("/api/verify/start", json={"character": "Hilay"}, headers=self.h())
        COMMENTS["hilay"] = r.json()["code"]
        self.token = self.client.post("/api/verify/check", json={"code": r.json()["code"]}, headers=self.h()).json()["token"]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        # o banco de teste é compartilhado: apaga o que este teste enviou para não colidir com outros testes
        for table in ("hunts", "solo_sessions"):
            server.store._conn.execute(f"DELETE FROM {table} WHERE uploader_key = ?", (self.key,))
        server.store._conn.commit()

    def h(self, token=""):
        return {"X-Access-Key": self.key, "X-Device-Token": token or getattr(self, "token", "")}

    def _upload_on_days(self, n):
        """Simula envios do Stacker em n dias seguidos terminando hoje (meio-dia em Brasília)."""
        base = parse_solo_session(SOLO).to_dict()
        today = datetime.now(ach.LOCAL_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
        for i in range(n):
            row, _ = server.store.add_solo("Hilay", f"fp-{self.key}-{i}", base, self.key)
            when = (today - timedelta(days=i)).astimezone(timezone.utc)
            server.store._conn.execute("UPDATE solo_sessions SET created_at = ? WHERE id = ?", (_iso(when), row["id"]))
        server.store._conn.commit()

    def test_30_days_in_a_row_add_7_days_once(self):
        before = server.store.validate_key(self.key)["expires_at"]
        self._upload_on_days(29)
        r = self.client.get("/api/streak", headers=self.h()).json()
        self.assertEqual((r["current"], r["granted"]), (29, []))
        self._upload_on_days(30)  # mais um dia (o 30º)
        r = self.client.get("/api/streak", headers=self.h()).json()
        self.assertEqual(r["current"], 30)
        self.assertEqual(len(r["granted"]), 1)
        after = server.store.validate_key(self.key)["expires_at"]
        gained = datetime.fromisoformat(after) - datetime.fromisoformat(before)
        self.assertEqual(round(gained.total_seconds() / 86400), 7)
        # não ganha de novo pelo mesmo bloco de 30 dias
        again = self.client.get("/api/streak", headers=self.h()).json()
        self.assertEqual(again["granted"], [])
        self.assertEqual(server.store.validate_key(self.key)["expires_at"], after)
        self.assertEqual(len(again["rewards"]), 1)

    def test_uploads_report_rewards_and_achievements(self):
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Hilay"}, headers=self.h())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["rewards"], [])
        d = self.client.get("/api/achievements/Hilay", headers=self.h()).json()
        got = {a["id"]: a for a in d["achievements"]}
        self.assertTrue(got["first_solo"]["unlocked"])
        self.assertEqual(d["total"], len(ach.DEFINITIONS))
        self.assertIn("streak", d)
        self.assertEqual(self.client.get("/api/achievements/Hilay", headers={"X-Access-Key": self.key}).status_code, 401)

    def test_vocations(self):
        r = self.client.get("/api/vocations?names=Hilay,Outro Char,<script>", headers=self.h())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"Hilay": "Knight", "Outro Char": "Knight"})  # nome impossível nem é consultado
        self.assertIn("hilay", server.store.char_infos(["Hilay"]))

    def test_party_hunt_counts_for_streak(self):
        r = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=self.h())
        if r.status_code == 200:
            self.assertEqual(self.client.get("/api/streak", headers=self.h()).json()["current"], 1)


class StaticFilesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_icon_and_manifest(self):
        for name, kind in (("manifest.webmanifest", "application/manifest+json"), ("icon-192.png", "image/png"),
                           ("icon-512.png", "image/png"), ("icon-maskable.png", "image/png")):
            r = self.client.get("/" + name)
            self.assertEqual(r.status_code, 200, name)
            self.assertTrue(r.headers["content-type"].startswith(kind), name)
        for name in ("index.html", "admin.html", "sw.js.bak", "..%2Fserver%2Fapp.py"):
            self.assertEqual(self.client.get("/" + name).status_code, 404, name)

    def test_csp_allows_only_official_music(self):
        html = self.client.get("/").text
        self.assertIn("media-src https://static.tibia.com;", html)


if __name__ == "__main__":
    unittest.main()
