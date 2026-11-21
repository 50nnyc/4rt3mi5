"""👑 Rotação de bosses: envio solo/party, lootsplit, vínculo automático e privacidade."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core import bosses as boss_core
from artemis.server import app as server
from tests import limpar_banco
from tests.test_core import EXAMPLE
from tests.test_server import COMMENTS, fake_fetch

BOSS_SOLO = """Session data: From 2026-11-04, 18:52:10 to 2026-11-04, 20:19:30
Session: 01:27h
Raw XP Gain: 120,000
XP Gain: 180,000
Loot: 900,000
Supplies: 300,000
Balance: 600,000
Damage: 2,000,000
Damage/h: 1,000,000
Healing: 500,000
Healing/h: 250,000
Killed Monsters:
  1x Grand Master Oberon
  4x falcon knight
Looted Items:
  1x falcon battleaxe
  2x platinum coins
"""

HUNT_WITH_BOSS = """Session data: From 2026-11-01, 10:00:00 to 2026-11-01, 11:00:00
Session: 01:00h
Raw XP Gain: 1,000,000
XP Gain: 1,500,000
Loot: 400,000
Supplies: 100,000
Balance: 300,000
Damage: 1,000,000
Damage/h: 1,000,000
Healing: 100,000
Healing/h: 100,000
Killed Monsters:
  80x dragon
  1x Demodras
Looted Items:
  1x dragon scale mail
  5x dragon ham
  1x golden mug
  30x platinum coins
"""


def session_for(nick_time: str) -> str:
    return BOSS_SOLO.replace("18:52:10", nick_time)


class BossCoreTests(unittest.TestCase):
    def test_recognizes_bosses(self):
        self.assertEqual(boss_core.boss_info("grand master oberon")["class"], "Archfoe")
        self.assertIsNotNone(boss_core.boss_info("the time guardian"))
        self.assertIsNone(boss_core.boss_info("dragon"))

    def test_hunt_loot_estimate_skips_common_and_coins(self):
        kills = [("dragon", 80), ("demodras", 1)]
        loot = [("dragon scale mail", 1), ("dragon ham", 5), ("golden mug", 1), ("platinum coins", 30)]
        split = boss_core.attribute_loot(kills, loot, whole_session=False)
        self.assertEqual(sorted(i for i, _ in split["demodras"]), ["dragon scale mail", "golden mug"])

    def test_rare_drops_by_rarity_and_value(self):
        kills = [("dragon", 80), ("demodras", 1)]
        loot = [("dragon scale mail", 1), ("dragon ham", 5), ("golden mug", 1), ("platinum coins", 30)]
        drops = boss_core.rare_drops(kills, loot, False, lambda k: 0)
        self.assertEqual([d["item"] for d in drops], ["dragon scale mail"])  # very rare; golden mug é só "rare"
        self.assertEqual(drops[0]["rarity"], "very rare")
        oberon = [("grand master oberon", 1), ("falcon knight", 4)]
        self.assertEqual(boss_core.rare_drops(oberon, [("falcon battleaxe", 1)], True, lambda k: 0), [])
        expensive = boss_core.rare_drops(oberon, [("falcon battleaxe", 1)], True, lambda k: 700_000)
        self.assertEqual(expensive[0]["boss"], "Grand Master Oberon")
        self.assertEqual(boss_core.rare_drops([("dragon", 9)], [("dragon scale mail", 1)], False, lambda k: 9**9), [])

    def test_overlap_tolerance(self):
        self.assertTrue(boss_core.overlaps("2026-11-04T18:52:10", "2026-11-04T20:19:30",
                                           "2026-11-04T18:50:49", "2026-11-04T20:21:07"))
        self.assertFalse(boss_core.overlaps("2026-11-05T18:52:10", "2026-11-05T20:19:30",
                                            "2026-11-04T18:50:49", "2026-11-04T20:21:07"))


class BossServerTests(unittest.TestCase):
    def setUp(self):
        limpar_banco(server.store._conn)
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails):
            cache.clear()
        COMMENTS.clear()
        server.store._conn.execute("DELETE FROM key_chars")  # 0.15.0: personagem em uma chave só
        self.patch = mock.patch.object(server, "fetch_character", fake_fetch)
        self.patch.start()
        self.hs = mock.patch.object(server, "fetch_experience", lambda *a, **k: None)
        self.hs.start()
        conn = server.store._conn
        for t in ("boss_kills", "boss_loot", "boss_sessions", "boss_hunt_players", "boss_hunts"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()

    def tearDown(self):
        self.patch.stop()
        self.hs.stop()

    def login(self, character):
        key = server.store.create_key(30, "boss")["key"]
        r = self.client.post("/api/verify/start", json={"character": character}, headers={"X-Access-Key": key})
        COMMENTS[character.lower()] = r.json()["code"]
        server._last_check.clear()
        r = self.client.post("/api/verify/check", json={"code": r.json()["code"]}, headers={"X-Access-Key": key})
        self.assertEqual(r.status_code, 200, r.text)
        return {"X-Access-Key": key, "X-Device-Token": r.json()["token"]}

    def test_solo_session_and_privacy(self):
        hilay = self.login("Hilay")
        r = self.client.post("/api/bosses/session", json={"raw_text": BOSS_SOLO, "nickname": "Hilay", "mode": "solo"},
                             headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([b["name"] for b in r.json()["bosses"]], ["Grand Master Oberon"])
        again = self.client.post("/api/bosses/session", json={"raw_text": BOSS_SOLO, "nickname": "Hilay", "mode": "solo"},
                                 headers=hilay)
        self.assertFalse(again.json()["created"])
        d = self.client.get("/api/bosses/Hilay", headers=hilay).json()
        self.assertEqual(d["totals"]["sessions"], 1)
        self.assertEqual(d["bosses"][0]["kills"], 1)
        self.assertEqual(d["totals"]["sessions_profit"], 600_000)
        # sessões de boss não aparecem no Stacker público nem em outra conta
        stacker = self.client.get("/api/stacker/Hilay", headers=hilay).json()["sessions"]
        self.assertFalse(any(s["started_at"] == "2026-11-04T18:52:10" for s in stacker))
        other = self.login("Jioe")
        r = self.client.get("/api/bosses/Hilay", headers=other)
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("Grand Master", r.text)
        # só quem enviou apaga
        sid = d["sessions"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/bosses/session/{sid}", headers=other).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/bosses/session/{sid}", headers=hilay).status_code, 200)

    def test_party_split_shows_for_party_and_links_sessions(self):
        hilay, jioe, outsider = self.login("Hilay"), self.login("Jioe"), self.login("Vcte Fora")
        # Jioe envia antes a sessão dele (disse "não" para o lootsplit)
        r = self.client.post("/api/bosses/session", json={"raw_text": session_for("18:55:00"), "nickname": "Jioe",
                                                          "mode": "party"}, headers=jioe)
        self.assertIsNone(r.json()["party"])
        # Hilay envia a sessão e o lootsplit da party
        r = self.client.post("/api/bosses/session", json={"raw_text": BOSS_SOLO, "nickname": "Hilay", "mode": "party"},
                             headers=hilay)
        sid = r.json()["session_id"]
        bad = self.client.post("/api/bosses/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay", "session_id": sid},
                               headers=jioe)
        self.assertEqual(bad.status_code, 403)  # nickname de outra conta
        r = self.client.post("/api/bosses/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay", "session_id": sid},
                             headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["linked"], 2)  # a de Hilay e a de Jioe (mesmo horário)
        self.assertNotIn("uploader_key", r.json()["hunt"])
        # aparece na aba de bosses de Jioe (que está na PT)
        d = self.client.get("/api/bosses/Jioe", headers=jioe).json()
        self.assertEqual(len(d["hunts"]), 1)
        self.assertEqual(sorted(d["hunts"][0]["members"]), ["Hilay", "Jioe"])
        self.assertEqual(d["sessions"][0]["party"]["profit_each"], 2_319_540)
        self.assertEqual(d["totals"]["party_profit"], 2_319_540)
        self.assertEqual(d["totals"]["sessions_profit"], 0)  # a sessão vinculada não conta em dobro
        # quem não estava na PT não consegue mandar o lootsplit em nome próprio
        r = self.client.post("/api/bosses/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Vcte Fora"}, headers=outsider)
        self.assertEqual(r.status_code, 403)
        # sessão enviada depois do lootsplit também se vincula sozinha
        atx = self.login("Bobeek")
        r = self.client.post("/api/bosses/session", json={"raw_text": session_for("18:51:00"), "nickname": "Bobeek",
                                                          "mode": "solo"}, headers=atx)
        self.assertEqual(r.json()["party"]["profit_each"], 2_319_540)
        # nada disso vaza para o Lootsplit comum
        self.assertEqual(self.client.get("/api/hunts/Jioe", headers=jioe).json()["hunts"], [])
        # apagar o lootsplit mantém as sessões
        hid = d["hunts"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/bosses/hunt/{hid}", headers=jioe).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/bosses/hunt/{hid}", headers=hilay).status_code, 200)
        self.assertEqual(self.client.get("/api/bosses/Jioe", headers=jioe).json()["totals"]["sessions"], 1)

    def test_boss_in_normal_hunt_counts_in_bosses_tab(self):
        kaio = self.login("Kaio Boss")
        r = self.client.post("/api/stacker", json={"raw_text": HUNT_WITH_BOSS, "nickname": "Kaio Boss"}, headers=kaio)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["key"] for x in r.json()["rare"]], ["dragon scale mail"])  # 💎 comemoração no envio
        d = self.client.get("/api/bosses/Kaio Boss", headers=kaio).json()
        self.assertEqual([(x["key"], x["source"]) for x in d["rare_drops"]], [("dragon scale mail", "hunt")])
        self.assertEqual(len(d["from_hunts"]), 1)
        keys = {it["key"] for it in d["from_hunts"][0]["items"]}
        self.assertIn("dragon scale mail", keys)
        self.assertNotIn("dragon ham", keys)
        self.assertNotIn("platinum coin", keys)
        demodras = next(b for b in d["bosses"] if b["name"] == "Demodras")
        self.assertEqual(demodras["from_hunts"], 1)
        self.assertEqual(d["totals"]["profit"], d["totals"]["hunts_value"])

    def test_item_without_npc_asks_price_and_becomes_rare(self):
        nara = self.login("Nara Boss")
        text = session_for("07:00:00").replace("2026-11-04", "2026-10-20")
        r = self.client.post("/api/bosses/session", json={"raw_text": text, "nickname": "Nara Boss", "mode": "solo"},
                             headers=nara)
        self.assertEqual(r.json()["rare"], [])
        d = self.client.get("/api/bosses/Nara Boss", headers=nara).json()
        self.assertIn("falcon battleaxe", d["no_npc"])
        self.assertNotIn("platinum coin", d["no_npc"])
        self.assertGreaterEqual(d["unpriced"], 1)
        r = self.client.post("/api/items/price", json={"item": "falcon battleaxe", "price": 800_000}, headers=nara)
        self.assertEqual(r.status_code, 200, r.text)
        d = self.client.get("/api/bosses/Nara Boss", headers=nara).json()
        self.assertEqual(d["prices"]["falcon battleaxe"]["unit_price"], 800_000)
        self.assertEqual([(x["key"], x["value"]) for x in d["rare_drops"]], [("falcon battleaxe", 800_000)])

    def test_validation(self):
        hilay = self.login("Hilay")
        r = self.client.post("/api/bosses/session", json={"raw_text": BOSS_SOLO, "nickname": "Hilay", "mode": "outro"},
                             headers=hilay)
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/bosses/session", json={"raw_text": EXAMPLE, "nickname": "Hilay", "mode": "solo"},
                             headers=hilay)
        self.assertEqual(r.status_code, 422)  # Party Hunt Analyser no lugar da sessão
        r = self.client.post("/api/bosses/session", json={"raw_text": BOSS_SOLO, "nickname": "Hilay", "mode": "solo"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
