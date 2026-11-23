"""0.20.0: tipo de player, Input Analyser, local da hunt com 2 trocas, dados da PT e privacidade."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core import damage
from artemis.core.parser import ParseError
from tests.test_server import COMMENTS, fake_fetch, server  # mesmo banco temporário dos testes do servidor
from tests.test_core import EXAMPLE as _EXAMPLE
from tests.test_session import SOLO as _SOLO

# Nomes e datas só destes testes: o banco temporário é o mesmo dos testes do servidor.
NAMES = {"Hilay": "Rvhilay", "Jioe": "Rvjioe", "Bobeek": "Rvatx", "Vcte": "Rvvcte"}


def _iso(text: str) -> str:
    for a, b in NAMES.items():
        text = text.replace(a, b)
    return text.replace("2026-11-04", "2026-09-04")


EXAMPLE, SOLO = _iso(_EXAMPLE), _iso(_SOLO)

INPUT_1 = """Received Damage
Total: 868
Max-DPS: 67
Damage Types
  Physical 459 (52.9%)
  Fire 275 (31.7%)
  Energy 67 (7.7%)
  Death 67 (7.7%)
Damage Sources
  elf scout 389 (44.8%)
  witch 227 (26.2%)
  elf arcanist 134 (15.4%)
  (other) 48 (5.5%)
  valkyrie 43 (5.0%)
"""

INPUT_2 = """Received Damage
Total: 220,388
Max-DPS: 6,143
Damage Types
  Physical 81,976 (37.2%)
  Ice 56,033 (25.4%)
  Death 52,861 (24.0%)
  Mana Drain 9,716 (4.4%)
  Life Drain 8,034 (3.6%)
  Energy 6,362 (2.9%)
  Fire 5,406 (2.5%)
Damage Sources
  The Moonsnow Magnolia 67,009 (30.4%)
  rogue naga 31,001 (14.1%)
  corrupt naga 22,623 (10.3%)
  true frost flower asura 22,072 (10.0%)
  true frostnight asura 21,252 (9.6%)
"""


def solo(day: int) -> str:
    """A sessão de exemplo num dia só dela (o banco de teste é compartilhado com os outros testes)."""
    return SOLO.replace("2026-09-04", f"2026-10-{day:02d}")


class InputParserTests(unittest.TestCase):
    def test_reads_both_examples(self):
        a = damage.parse_input(INPUT_1)
        self.assertEqual((a["total"], a["max_dps"]), (868, 67))
        self.assertEqual(a["types"][0], {"name": "Physical", "value": 459, "pct": 52.9})
        self.assertEqual(len(a["sources"]), 5)
        other = next(s for s in a["sources"] if s["name"] == "(other)")
        self.assertTrue(other["other"])
        s = damage.summary(a)
        self.assertEqual(s["top_type"]["name"], "Physical")
        self.assertEqual(s["top_mob"]["name"], "elf scout")
        b = damage.parse_input(INPUT_2)
        self.assertEqual((b["total"], b["max_dps"]), (220388, 6143))
        self.assertEqual([t["name"] for t in b["types"]][:3], ["Physical", "Ice", "Death"])
        self.assertEqual(b["types"][3]["name"], "Mana Drain")
        self.assertEqual(damage.summary(b)["top_mob"]["name"], "The Moonsnow Magnolia")

    def test_other_is_never_a_creature(self):
        c = damage.combine([damage.parse_input(INPUT_1)])
        self.assertNotIn("(other)", [m["name"] for m in c["mobs"]])
        self.assertEqual(c["other_pct"], 5.5)
        self.assertEqual(c["mobs"][0]["name"], "elf scout")

    def test_rejects_other_texts(self):
        for bad in ("", SOLO, EXAMPLE, "Received Damage\nDamage Types\n  Fire 1 (100%)"):
            with self.assertRaises(ParseError):
                damage.parse_input(bad)


class RevampServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails):
            cache.clear()
        COMMENTS.clear()
        self.patches = [mock.patch.object(server, "fetch_character", fake_fetch),
                        mock.patch.object(server, "fetch_experience", lambda *a, **k: None)]
        for p in self.patches:
            p.start()
        server.store._conn.execute("DELETE FROM key_chars")
        server.store.load_places({"imported_at": "t", "hunts": [
            ["Elvenbane", "Ab'Dendriel", "Norte", 30, None, True],
            ["Asura Palace", "Port Hope", "Sul", 250, None, True],
            ["Naga Caves", "Marapur", "Leste", 300, None, True]]})

    def tearDown(self):
        for p in self.patches:
            p.stop()
        # apaga o que estes testes criaram (o banco é o mesmo dos testes do servidor)
        c = server.store._conn
        mine = tuple(n.lower() for n in NAMES.values())
        marks = ",".join("?" * len(mine))
        c.execute(f"DELETE FROM hunts WHERE id IN (SELECT hunt_id FROM hunt_players WHERE name_key IN ({marks}))", mine)
        c.execute(f"DELETE FROM solo_sessions WHERE name_key IN ({marks})", mine)
        c.execute("DELETE FROM damage_inputs")
        c.execute("DELETE FROM party_sessions")
        c.commit()

    def account(self, name):
        key = server.store.create_key(30, name)["key"]
        server.store.force_main(key, name)
        return {"X-Access-Key": key, "X-Device-Token": server.store.issue_device(key, name)}

    def places(self, h):
        return {p["name"]: p["id"] for p in self.client.get("/api/places", headers=h).json()}

    def test_player_type_default_and_change(self):
        h = self.account("Rvhilay")
        me = self.client.get("/api/me", headers=h).json()
        self.assertEqual((me["player_type"], me["player_type_chosen"]), ("comum", False))
        self.assertEqual(me["player_types"], ["hardcore", "comum", "novato"])
        r = self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        self.assertEqual((r.json()["player_type"], r.json()["player_type_chosen"]), ("hardcore", True))
        self.assertEqual(self.client.post("/api/prefs/player-type", json={"player_type": "pro"}, headers=h).status_code, 422)
        # tipo extra: fora da lista e recusado, até ser ligado no servidor
        self.assertEqual(self.client.post("/api/prefs/player-type", json={"player_type": "tipo_extra"}, headers=h).status_code, 422)
        with mock.patch.dict("os.environ", {"ARTEMIS_EXTRA_PLAYER_TYPES": "tipo_extra"}):
            me = self.client.get("/api/me", headers=h).json()
            self.assertIn("tipo_extra", me["player_types"])
            self.assertIn("tipo_extra", me["hardcore_types"])  # tipo extra conta como Hardcore
            self.assertEqual(self.client.post("/api/prefs/player-type", json={"player_type": "tipo_extra"}, headers=h).status_code, 200)

    def test_db_survives_parallel_requests(self):
        """Várias requisições ao mesmo tempo usam a mesma conexão SQLite: cada comando espera a vez."""
        import concurrent.futures
        key = server.store.create_key(30, "paralelo")["key"]

        def work(i):
            for _ in range(40):
                assert server.store.validate_key(key)
                server.store.player_type(key)
                server.store.player_type_chosen(key)
                server.store.places()
            return True
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            self.assertTrue(all(ex.map(work, range(16))))

    def test_discrepancy_rules(self):
        h = {"started_at": "2026-09-04T18:00:00", "ended_at": "2026-09-04T19:00:00", "loot_type": "Market",
             "players": [{"name": "Rvhilay", "loot": 1000, "supplies": 300, "balance": 700}]}
        s = {"name": "Rvhilay", "started_at": "2026-09-04T18:00:20", "ended_at": "2026-09-04T19:00:10", "supplies": 300, "balance": 600}
        self.assertEqual(server._discrepancy(s, h), ["loot", "balance"])  # Market: olha tudo
        self.assertEqual(server._discrepancy(s, {**h, "loot_type": "Leader"}), [])  # Leader: só supplies (iguais)
        self.assertEqual(server._discrepancy({**s, "supplies": 299}, {**h, "loot_type": "Leader"}), ["supplies"])
        other_time = {**s, "ended_at": "2026-09-04T18:30:00"}
        self.assertEqual(server._discrepancy(other_time, h), [])  # outro período: não é ponto crítico

    def test_admin_sees_char_hunts_and_frees_place_changes(self):
        admin = {"X-Admin-Token": server.CONFIG["admin_token"]}
        h = self.account("Rvhilay")
        pl = self.places(h)
        sid = self.client.post("/api/stacker", json={"raw_text": solo(4), "nickname": "Rvhilay"}, headers=h).json()["session"]["id"]
        url = f"/api/stacker/session/{sid}/place"
        for p in ("Elvenbane", "Asura Palace", "Naga Caves"):
            self.client.post(url, json={"place_id": pl[p]}, headers=h)
        self.assertEqual(self.client.get("/api/admin/chars/Rvhilay/hunts").status_code, 401)
        d = self.client.get("/api/admin/chars/Rvhilay/hunts", headers=admin).json()
        row = next(s for s in d["sessions"] if s["id"] == sid)
        self.assertEqual((row["place"]["name"], row["place_edits"]), ("Naga Caves", 2))
        # o adm troca sem gastar as trocas da pessoa e libera as 2 trocas de novo
        r = self.client.post("/api/admin/place", json={"kind": "solo", "id": sid, "place_id": pl["Elvenbane"], "reset_edits": True},
                             headers=admin).json()
        self.assertEqual((r["place"]["name"], r["place_edits"]), ("Elvenbane", 0))
        self.assertEqual(self.client.post(url, json={"place_id": pl["Asura Palace"]}, headers=h).status_code, 200)
        self.assertEqual(self.client.post("/api/admin/place", json={"kind": "hunt", "id": 999999, "reset_edits": True},
                                          headers=admin).status_code, 404)

    def test_save_without_place_then_two_changes_only(self):
        h = self.account("Rvhilay")
        SOLO = solo(1)
        pl = self.places(h)
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Rvhilay"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["session"]["id"]
        s = next(x for x in self.client.get("/api/stacker/Rvhilay", headers=h).json()["sessions"] if x["id"] == sid)
        self.assertIsNone(s["place"])  # "hunt sem local"
        url = f"/api/stacker/session/{sid}/place"
        first = self.client.post(url, json={"place_id": pl["Elvenbane"]}, headers=h).json()
        self.assertEqual((first["place"]["name"], first["place_edits"], first["locked"]), ("Elvenbane", 0, False))
        self.assertEqual(self.client.post(url, json={"place_id": pl["Asura Palace"]}, headers=h).json()["place_edits"], 1)
        second = self.client.post(url, json={"place_id": pl["Naga Caves"]}, headers=h).json()
        self.assertEqual((second["place_edits"], second["locked"]), (2, True))
        third = self.client.post(url, json={"place_id": pl["Elvenbane"]}, headers=h)
        self.assertEqual(third.status_code, 403)
        self.assertEqual(third.json()["detail"], server.PLACE_LOCKED)
        # outra pessoa não mexe
        self.assertEqual(self.client.post(url, json={"place_id": pl["Elvenbane"]}, headers=self.account("Rvjioe")).status_code, 403)

    def test_input_not_for_novato_and_never_edited(self):
        h = self.account("Rvhilay")
        SOLO = solo(2)
        sid = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Rvhilay"}, headers=h).json()["session"]["id"]
        url = f"/api/stacker/session/{sid}/input"
        self.client.post("/api/prefs/player-type", json={"player_type": "novato"}, headers=h)
        self.assertEqual(self.client.post(url, json={"raw_text": INPUT_1}, headers=h).status_code, 403)  # novato
        self.client.post("/api/prefs/player-type", json={"player_type": "comum"}, headers=h)  # comum junta quando quiser
        self.assertEqual(self.client.post(url, json={"raw_text": SOLO}, headers=h).status_code, 422)
        r = self.client.post(url, json={"raw_text": INPUT_1}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["input"]["top_mob"]["name"], "elf scout")
        again = self.client.post(url, json={"raw_text": INPUT_2}, headers=h)
        self.assertEqual(again.status_code, 409)
        s = next(x for x in self.client.get("/api/stacker/Rvhilay", headers=h).json()["sessions"] if x["id"] == sid)
        self.assertEqual(s["input"]["total"], 868)

    def test_other_players_see_only_generic_data(self):
        h = self.account("Rvhilay")
        SOLO = solo(3)
        pl = self.places(h)
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Rvhilay", "place_id": pl["Elvenbane"]}, headers=h)
        self.assertEqual(r.status_code, 200)
        mine = self.client.get("/api/stacker/Rvhilay", headers=h).json()
        self.assertTrue(mine["sessions"][0]["kills"])
        self.assertIn("Elvenbane", [r["place"] for r in mine["by_place"]["rows"]])
        other = self.client.get("/api/stacker/Rvhilay", headers=self.account("Rvjioe")).json()
        s = other["sessions"][0]
        for k in ("kills", "loot", "loot_value", "net_profit", "input"):
            self.assertNotIn(k, s)
        self.assertEqual(s["xp"], 7_684_000)  # o geral continua
        self.assertEqual((other["period"]["kills"], other["period"]["items"], other["sell"]), ([], [], []))
        self.assertIsNone(other["by_place"])

    def test_party_place_member_session_and_input(self):
        h = self.account("Rvhilay")
        pl = self.places(h)
        hunt = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Rvhilay"}, headers=h).json()["hunt"]
        self.assertTrue(hunt["in_party"])
        self.assertIsNone(hunt["place"])
        hid = hunt["id"]
        r = self.client.post(f"/api/hunt/{hid}/place", json={"place_id": pl["Naga Caves"]}, headers=h).json()
        self.assertEqual(r["place"]["name"], "Naga Caves")
        # outro membro da PT (Jioe, Player Hardcore) junta a sessão e o Input Analyser dele
        hj = self.account("Rvjioe")
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/place", json={"place_id": pl["Elvenbane"]}, headers=hj).status_code, 403)
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=hj)
        r = self.client.post(f"/api/hunt/{hid}/session", json={"raw_text": SOLO, "nickname": "Rvjioe"}, headers=hj)
        self.assertEqual(r.status_code, 200, r.text)
        # mesmo período da party hunt e loot type Leader: só os supplies são comparados
        ms = next(m for m in r.json()["hunt"]["member_sessions"] if m["name"] == "Rvjioe")
        self.assertEqual(ms["discrepancy"], ["supplies"])
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/session", json={"raw_text": SOLO, "nickname": "Rvjioe"}, headers=hj).status_code, 409)
        r = self.client.post(f"/api/hunt/{hid}/input", json={"raw_text": INPUT_2, "nickname": "Rvjioe"}, headers=hj)
        self.assertEqual(r.status_code, 200, r.text)
        # Hilay (membro) vê o que o Jioe compartilhou, mas sem as criaturas e itens dele
        seen = self.client.get("/api/hunts/Rvhilay", headers=h).json()["hunts"][0]
        ms = seen["member_sessions"][0]
        self.assertEqual((ms["name"], ms["own"]), ("Rvjioe", False))
        self.assertNotIn("kills", ms)
        self.assertEqual(seen["inputs"][0]["top_type"]["name"], "Physical")
        own = self.client.get("/api/hunts/Rvjioe", headers=hj).json()["hunts"][0]["member_sessions"][0]
        self.assertTrue(own["own"] and own["kills"])
        # quem não estava na PT não vê o que foi compartilhado
        outsider = self.client.get("/api/hunts/Rvhilay", headers=self.account("Fora Da Pt")).json()["hunts"][0]
        self.assertEqual((outsider["inputs"], outsider["member_sessions"], outsider["in_party"]), ([], [], False))
        # comparação de hunts mostra o dano recebido ali, sem "(other)" como criatura
        # 0.22.0: party compara só com party; Input Analyser público só para o Player Hardcore
        url = f"/api/places/compare?ids={pl['Naga Caves']}&mode=party"
        cmp_ = self.client.get(url + "&nick=Rvjioe", headers=hj).json()[0]
        self.assertEqual(cmp_["damage"]["mobs"][0]["name"], "the moonsnow magnolia")
        self.assertEqual(cmp_["my_damage"]["mobs"][0]["name"], "the moonsnow magnolia")  # o dele, com detalhes
        self.assertTrue(cmp_["top_kills"] and "count" in cmp_["top_kills"][0])
        basic = self.client.get(url + "&nick=Rvhilay", headers=h).json()[0]
        self.assertIsNone(basic["damage"])  # Hilay não é hardcore
        self.assertEqual(basic["top_kills"], [])  # não juntou sessão: só o básico
        self.assertEqual(basic["mine"]["sessions"], 1)
        self.assertIsNone(self.client.get(f"/api/places/compare?ids={pl['Naga Caves']}", headers=hj).json()[0]["stats"])  # solo: nada
        rank = self.client.get("/api/places/ranking?mode=party", headers=h).json()["rows"]
        self.assertEqual([r["name"] for r in rank], ["Naga Caves"])
        mine = self.client.get("/api/places/mine?mode=party&nick=Rvhilay", headers=h).json()["rows"]
        self.assertEqual(mine[0]["sessions"], 1)
        self.assertEqual(self.client.get("/api/places/mine?mode=party&nick=Rvhilay", headers=hj).json()["rows"], [])
        # novato não junta sessão; quem não estava na PT também não
        hn = self.account("Rvatx")
        self.client.post("/api/prefs/player-type", json={"player_type": "novato"}, headers=hn)
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/session", json={"raw_text": SOLO, "nickname": "Rvatx"}, headers=hn).status_code, 403)
        hf = self.account("Fora Da Pt")
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/session", json={"raw_text": SOLO, "nickname": "Fora Da Pt"}, headers=hf).status_code, 403)


if __name__ == "__main__":
    unittest.main()
