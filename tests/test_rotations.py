"""0.23.0: 👑 rotações de bosses (nome automático), taxa do Market e 🗃️ cofre da rotação."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core import rotations as rot
from artemis.server import app as server
from tests.test_core import EXAMPLE
from tests.test_server import COMMENTS, fake_fetch


class RotationNameTests(unittest.TestCase):
    def name(self, *bosses):
        r = rot.identify([(b, 1) for b in bosses])
        return r and r["name"]

    def test_examples_from_the_owner(self):
        self.assertEqual(self.name("Scarlett Etzel"), "Rotação Bastions: Cobra Bastion")
        self.assertEqual(self.name("scarlett etzel", "Grand Master Oberon"), "Rotação Bastions: Cobra + Falcon Bastion")
        self.assertEqual(self.name("Court Warlock", "Megasylvan Yselda"), "Rotação Bastions: Stag Bastion + Yselda")
        self.assertEqual(self.name("World Devourer", "Ferumbras Mortal Shell"), "Rotação Last room GT + Ferumbras")
        self.assertEqual(self.name("Rupture", "Anomaly", "Count Vlarkorth"), "Rotação GT + GD")
        self.assertEqual(self.name("Katex Blood Tongue", "Srezz Yellow Eyes", "Black Vixen"), "Rotação Werelion + Were")
        self.assertEqual(self.name("Ice Horror", "Bone Overlord"), "Rotação Graveborn + Last room Graveborn")
        self.assertEqual(self.name("Scarlett Etzel", "Duke Krule"), "Rotação GD + Bastions (Cobra Bastion)")
        self.assertIsNone(self.name("dragon"))

    def test_market_fee_rule_by_date(self):
        self.assertEqual(rot.market_fee(1_000_000, "2026-11-01T12:00:00"), 25_000)         # 2,5%
        self.assertEqual(rot.market_fee(500_000_000, "2026-11-01T12:00:00"), 2_500_000)    # teto novo
        self.assertEqual(rot.market_fee(1_000_000, "2026-09-01T12:00:00"), 20_000)         # 2% antes de 06/10/2026
        self.assertEqual(rot.market_fee(500_000_000, "2026-09-01T12:00:00"), 1_000_000)    # teto antigo
        self.assertEqual(rot.market_fee(100, "2026-11-01T12:00:00"), 20)                   # mínimo
        self.assertEqual(rot.market_fee(0), 0)


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails):
            cache.clear()
        COMMENTS.clear()
        conn = server.store._conn
        for t in ("key_chars", "boss_sessions", "boss_hunt_players", "boss_hunts", "vault_drops", "vault_crafts",
                  "hunt_payments", "hunt_tags"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.patches = [mock.patch.object(server, "fetch_character", fake_fetch),
                        mock.patch.object(server, "fetch_experience", lambda *a, **k: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def login(self, character):
        key = server.store.create_key(30, "vault")["key"]
        r = self.client.post("/api/verify/start", json={"character": character}, headers={"X-Access-Key": key})
        COMMENTS[character.lower()] = r.json()["code"]
        server._last_check.clear()
        r = self.client.post("/api/verify/check", json={"code": r.json()["code"]}, headers={"X-Access-Key": key})
        return {"X-Access-Key": key, "X-Device-Token": r.json()["token"]}

    def party(self):
        hilay, jioe = self.login("Hilay"), self.login("Jioe")
        r = self.client.post("/api/bosses/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=hilay)
        return hilay, jioe, r.json()["hunt"]["id"]

    def test_drop_sold_with_market_fee_split_among_the_party(self):
        hilay, jioe, hid = self.party()
        r = self.client.post(f"/api/vault/hunt/{hid}/drops", json={"item": "icy crypt rune", "dropped_by": "Jioe",
                                                                  "price_each": 9_000_000}, headers=jioe)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()["drops"][0]
        self.assertEqual((d["item"], d["set"], d["estimate"]), ("Icy Crypt Rune", "crypt", 9_000_000))
        # só quem registrou muda o preço / vende
        self.assertEqual(self.client.post(f"/api/vault/drops/{d['id']}", json={"action": "price", "price_each": 1},
                                          headers=hilay).status_code, 403)
        r = self.client.post(f"/api/vault/drops/{d['id']}", json={"action": "sell", "sold_total": 10_000_000, "market_fee": True},
                             headers=jioe)
        d = r.json()["drops"][0]
        fee = rot.market_fee(10_000_000)
        self.assertEqual((d["fee"], d["net"]), (fee, 10_000_000 - fee))
        self.assertEqual(d["each"], (10_000_000 - fee) // 4)                    # 4 jogadores no Party Hunt Analyser
        self.assertEqual({t["receiver"] for t in d["transfers"]}, {"Bobeek", "Hilay", "Vcte"})
        self.assertTrue(all(t["payer"] == "Jioe" for t in d["transfers"]))
        # sem a taxa, é como se tivesse vendido por aquele preço
        r = self.client.post(f"/api/vault/drops/{d['id']}", json={"action": "sell", "sold_total": 10_000_000}, headers=jioe)
        self.assertEqual(r.json()["drops"][0]["net"], 10_000_000)
        # "já paguei" de quem paga
        r = self.client.post("/api/vault/paid", json={"kind": "drop", "id": d["id"], "payer": "Jioe", "receiver": "Hilay",
                                                      "paid": True}, headers=jioe)
        t = next(t for t in r.json()["drops"][0]["transfers"] if t["receiver"] == "Hilay")
        self.assertIsNotNone(t["paid_at"])
        # quem não estava na PT não vê nem mexe
        fora = self.login("Fulano Fora")
        self.assertEqual(self.client.get(f"/api/vault/hunt/{hid}", headers=fora).status_code, 403)
        self.assertEqual(self.client.post(f"/api/vault/hunt/{hid}/drops", json={"item": "x item", "dropped_by": "Fulano Fora"},
                                          headers=hilay).status_code, 422)

    def test_crypt_set_with_bought_runes(self):
        hilay, jioe, hid = self.party()
        for item in ("Icy Crypt Rune", "Fiery Crypt Rune", "Deathly Crypt Rune"):
            self.client.post(f"/api/vault/hunt/{hid}/drops", json={"item": item, "dropped_by": "Hilay", "qty": 2 if item == "Icy Crypt Rune" else 1},
                             headers=hilay)
        v = self.client.get(f"/api/vault/hunt/{hid}", headers=jioe).json()
        self.assertEqual(sorted(v["sets"]["crypt"]["missing"]), ["Ancient Crypt Rune", "Necromantic Crypt Rune"])
        ids = [d["id"] for d in v["drops"]]
        bad = self.client.post(f"/api/vault/hunt/{hid}/crafts", json={"set": "crypt", "drop_ids": ids, "seller": "Hilay"}, headers=hilay)
        self.assertEqual(bad.status_code, 422)  # faltam as runas compradas
        r = self.client.post(f"/api/vault/hunt/{hid}/crafts", json={
            "set": "crypt", "drop_ids": ids, "seller": "Hilay", "result": "crypt slicer", "sold_total": 100_000_000, "market_fee": True,
            "bought": [{"item": "Ancient Crypt Rune", "cost": 5_000_000}, {"item": "Necromantic Crypt Rune", "cost": 5_000_000}]},
            headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        c = r.json()["crafts"][0]
        fee = rot.market_fee(100_000_000)
        self.assertEqual(c["result"], "Crypt Slicer")
        self.assertEqual(c["net"], 100_000_000 - fee - 10_000_000)
        self.assertEqual(c["per_item"], c["net"] // 5)
        self.assertEqual(c["each"], c["net"] // 4)
        stock = [d for d in r.json()["drops"] if d["status"] == "stock"]
        self.assertEqual([(d["item"], d["qty"]) for d in stock], [("Icy Crypt Rune", 1)])  # sobrou 1 das 2
        # desfazer o uso devolve as runas
        r = self.client.delete(f"/api/vault/crafts/{c['id']}", headers=hilay)
        self.assertEqual(sum(d["qty"] for d in r.json()["drops"] if d["status"] == "stock"), 4)

    def test_drops_have_a_key_and_the_chosen_unit_is_used(self):
        hilay, jioe, hid = self.party()
        for who, day in (("Hilay", "2026-11-15"), ("Jioe", "2026-11-17")):
            self.client.post(f"/api/vault/hunt/{hid}/drops", json={"item": "Icy Crypt Rune", "dropped_by": who, "dropped_on": day},
                             headers=hilay)
        r = self.client.post(f"/api/vault/hunt/{hid}/drops", json={"item": "Icy Crypt Rune", "dropped_by": "Hilay",
                                                                  "dropped_on": "2099-01-01"}, headers=hilay)
        self.assertEqual(r.status_code, 422)  # data do futuro
        drops = self.client.get(f"/api/vault/hunt/{hid}", headers=hilay).json()["drops"]
        self.assertEqual([(d["dropped_on"], d["code"]) for d in drops], [("2026-11-15", f"#{drops[0]['id']}"), ("2026-11-17", f"#{drops[1]['id']}")])
        second = drops[1]["id"]
        others = [{"item": i, "cost": 1} for i in ("Ancient Crypt Rune", "Deathly Crypt Rune", "Fiery Crypt Rune", "Necromantic Crypt Rune")]
        r = self.client.post(f"/api/vault/hunt/{hid}/crafts", json={"set": "crypt", "drop_ids": [second], "bought": others,
                                                                   "seller": "Hilay"}, headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        v = r.json()
        self.assertEqual([u["dropped_on"] for u in v["crafts"][0]["used"]], ["2026-11-17"])
        self.assertEqual([d["dropped_on"] for d in v["drops"] if d["status"] == "stock"], ["2026-11-15"])

    def test_overview_names_the_rotation(self):
        hilay = self.login("Hilay")
        raw = """Session data: From 2026-11-04, 18:52:10 to 2026-11-04, 20:19:30
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
  1x Scarlett Etzel
Looted Items:
  2x platinum coins
"""
        self.client.post("/api/bosses/session", json={"raw_text": raw, "nickname": "Hilay", "mode": "solo"}, headers=hilay)
        d = self.client.get("/api/bosses/Hilay", headers=hilay).json()
        self.assertEqual(d["sessions"][0]["rotation"]["name"], "Rotação Bastions: Cobra + Falcon Bastion")
        self.assertEqual(d["rotations"][0]["name"], "Rotação Bastions: Cobra + Falcon Bastion")
        self.assertIn("vault", d["sessions"][0])
        self.assertEqual(d["fee"]["pct"], 2.5)


if __name__ == "__main__":
    unittest.main()
