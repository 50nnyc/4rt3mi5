"""0.26.1: rankings (geral por métrica e janela de cada jogador) e cálculo de HP/mana/cap a partir do level 8."""
import unittest
from datetime import date, timedelta
from unittest import mock

from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.core import vocation
from artemis.core import rankscan
from artemis.server import app as server
from artemis.server.db import name_key
from tests import limpar_banco
from tests.test_server import COMMENTS, fake_fetch


class VocationCalcTests(unittest.TestCase):
    def test_level_8_is_the_anchor_for_everyone(self):
        for voc in ("Knight", "Elite Knight", "Royal Paladin", "Elder Druid", "Master Sorcerer", "Exalted Monk"):
            self.assertEqual(vocation.calcular(8, voc), {"vocacao": vocation.vocacao_base(voc), "hp": 185, "mana": 90, "cap": 470})

    def test_formula_above_8(self):
        # Knight level 3000: 185 + 15*2992 = 45065 hp; 90 + 5*2992 = 15050 mana; 470 + 25*2992 = 75270 cap
        self.assertEqual(vocation.calcular(3000, "Knight"), {"vocacao": "Knight", "hp": 45065, "mana": 15050, "cap": 75270})
        # Druid de level 100: 185 + 5*92 hp; 90 + 30*92 mana; 470 + 10*92 cap
        self.assertEqual(vocation.calcular(100, "Elder Druid"), {"vocacao": "Druid", "hp": 645, "mana": 2850, "cap": 1390})

    def test_nothing_below_level_8(self):
        self.assertIsNone(vocation.calcular(7, "Knight"))
        self.assertIsNone(vocation.calcular(1, "Royal Paladin"))

    def test_unknown_vocation_gets_no_calc(self):
        self.assertIsNone(vocation.calcular(50, "None"))
        self.assertIsNone(vocation.calcular(50, None))


class RankingTests(unittest.TestCase):
    def setUp(self):
        limpar_banco(server.store._conn)
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails,
                      server._captcha_used):
            cache.clear()
        COMMENTS.clear()
        self.key = server.store.create_key(30, "v0261")["key"]
        self.patches = [mock.patch.object(server, "fetch_character", fake_fetch),
                        mock.patch.object(server, "fetch_experience", lambda *a, **k: None),
                        mock.patch.object(server.captcha, "verify", lambda *a, **k: None),
                        mock.patch.object(server, "XP_TRACK_START", date(2000, 1, 1))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        mock.patch.stopall()

    def login(self, character):
        hdr = {"X-Access-Key": self.key}
        code = self.client.post("/api/verify/start", json={"character": character}, headers=hdr).json()["code"]
        COMMENTS[character.lower()] = code
        server._last_check.clear()
        return self.client.post("/api/verify/check", json={"code": code}, headers=hdr).json()["token"]

    def test_geral_orders_each_metric_and_pages(self):
        def fetch_page(w, c, p, **_k):
            if p != 1 or w != "Antica":
                return []
            if c == "experience":
                return [{"name": "Topo Um", "level": 900, "vocation": "Knight", "value": 5},
                        {"name": "Topo Dois", "level": 800, "vocation": "Druid", "value": 9}]
            if c == "magiclevel":
                return [{"name": "Topo Dois", "level": 800, "vocation": "Druid", "value": 80}]
            return []
        with mock.patch.object(server, "fetch_highscore_page", fetch_page):
            rankscan.run_scan(server.store, day="2026-11-21", tracked={}, fetch_page=fetch_page,
                              fetch_worlds=lambda: ["Antica"], key_fn=name_key,
                              categories=("experience", "magiclevel"), workers=2, pages=2)
        token = self.login("Fora Geral")
        hdr = {"X-Access-Key": self.key, "X-Device-Token": token}
        lvl = self.client.get("/api/rank/geral?metric=level", headers=hdr).json()["rows"]
        self.assertEqual([r["name"] for r in lvl], ["Topo Um", "Topo Dois"])  # 900 > 800
        mag = self.client.get("/api/rank/geral?metric=magiclevel", headers=hdr).json()["rows"]
        self.assertEqual(mag[0]["name"], "Topo Dois")
        self.assertEqual(self.client.get("/api/rank/geral?metric=xyz", headers=hdr).json()["metric"], "level")

    def test_player_window_has_calc_and_monthly_charts_from_the_track_start(self):
        token = self.login("Fora Janela")
        hdr = {"X-Access-Key": self.key, "X-Device-Token": token}
        # o jogador precisa estar acompanhado (rank_players): a varredura cria essa linha
        rankscan.run_scan(server.store, day=date.today().isoformat(), tracked={name_key("Fora Janela"): "Fora Janela"},
                          fetch_page=lambda w, c, p, **_k: [{"name": "Fora Janela", "level": 200, "vocation": "Royal Paladin",
                                                              "value": 1000}] if (c, p) == ("experience", 1) else [],
                          fetch_worlds=lambda: ["Antica"], key_fn=name_key, categories=("experience",), workers=2, pages=2)
        hoje = date.today()
        for dias, xp in ((2, 1_000), (1, 1_500), (0, 2_200)):
            server.store.xp_save("Fora Janela", (hoje - timedelta(days=dias)).isoformat(), xp)
        r = self.client.get("/api/rank/player/Fora%20Janela", headers=hdr)
        self.assertEqual(r.status_code, 200, r.text)
        corpo = r.json()
        self.assertEqual(corpo["calc"]["hp"], 185 + 10 * 192)   # Paladin de level 200
        self.assertNotIn("total", corpo["xp"])                   # XP total do personagem nunca aparece no ranking
        self.assertNotIn("experience", server.RANK_METRICS)      # nem como métrica do ranking geral
        self.assertEqual([d["gain"] for d in corpo["charts"]["daily"]], [500, 700])
        self.assertEqual(corpo["charts"]["monthly"][-1]["gain"], 1200)
        self.assertTrue(corpo["charts"]["quarterly"])
        self.assertEqual(self.client.get("/api/rank/player/Ninguem%20Acompanha", headers=hdr).status_code, 404)


if __name__ == "__main__":
    unittest.main()
