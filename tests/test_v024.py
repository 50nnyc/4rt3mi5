"""0.24.0: 👥 parties registradas (titulares + substitutos) e 🗃️ cofre da party (sacolinhas, preço editável,
compra para o craft, craft com faixa de preço e venda com divisão entre os titulares)."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core import party as party_core
from artemis.server import app as server
from tests.test_core import EXAMPLE
from tests.test_server import COMMENTS, fake_fetch

KK = 1_000_000
RUNES = ["Ancient Crypt Rune", "Icy Crypt Rune", "Fiery Crypt Rune", "Deathly Crypt Rune", "Necromantic Crypt Rune"]


class CoreTests(unittest.TestCase):
    def test_craft_range_example(self):
        # o exemplo do pedido: Ancient drop 12kk, Icy compra 12kk, Fiery drop 14kk, Deathly compra 40kk, Necro drop 75kk
        used = [{"origin": "drop", "cost_each": None, "price": 12 * KK}, {"origin": "buy", "cost_each": 12 * KK, "price": 12 * KK},
                {"origin": "drop", "cost_each": None, "price": 14 * KK}, {"origin": "buy", "cost_each": 40 * KK, "price": 40 * KK},
                {"origin": "drop", "cost_each": None, "price": 75 * KK}]
        self.assertEqual(party_core.craft_range(used), {"min": 52 * KK, "max": 153 * KK, "cost": 52 * KK})

    def test_service_uses_agreed_value(self):
        self.assertEqual(party_core.unit_range("service", 5 * KK, 9 * KK), (5 * KK, 5 * KK))
        self.assertEqual(party_core.unit_range("service", None, 9 * KK), (0, 9 * KK))

    def test_sale_refunds_buyer_then_splits(self):
        s = party_core.sale(100 * KK, False, None, ["A", "B"], "A", [("C", 10 * KK)])
        self.assertEqual((s["net"], s["each"]), (90 * KK, 45 * KK))
        self.assertEqual({(t["receiver"], t["amount"]) for t in s["transfers"]}, {("B", 45 * KK), ("C", 10 * KK)})

    def test_subs_from_parties(self):
        parties = [{"kind": "both", "members": [{"name": n, "role": "main"} for n in ("A", "B", "C", "D")]
                    + [{"name": "S", "role": "sub"}]}]
        self.assertEqual(party_core.subs_from_parties(["A", "B", "C", "S"], parties, "hunt"), {"S": "D"})
        self.assertEqual(party_core.subs_from_parties(["A", "B", "C", "D"], parties, "boss"), {})
        self.assertEqual(party_core.subs_from_parties(["A", "X", "Y", "Z"], parties, "hunt"), {})  # não bate
        hunt_only = [{**parties[0], "kind": "hunt"}]
        self.assertEqual(party_core.subs_from_parties(["A", "B", "C", "S"], hunt_only, "boss"), {})


class PartyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails,
                      server._captcha_used):
            cache.clear()
        COMMENTS.clear()
        conn = server.store._conn
        for t in ("key_chars", "hunt_players", "hunts", "hunt_tags", "parties", "party_members", "party_items",
                  "party_crafts", "party_prices", "hunt_payments"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.patches = [mock.patch.object(server, "fetch_character", fake_fetch),
                        mock.patch.object(server, "fetch_experience", lambda *a, **k: None),
                        mock.patch.object(server.captcha, "verify", lambda *a, **k: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def login(self, *characters):
        key = server.store.create_key(30, "v024")["key"]
        token = None
        for character in characters:
            hdr = {"X-Access-Key": key, **({"X-Device-Token": token} if token else {})}
            r = self.client.post("/api/verify/start", json={"character": character}, headers=hdr)
            self.assertEqual(r.status_code, 200, r.text)
            COMMENTS[character.lower()] = r.json()["code"]
            server._last_check.clear()
            r = self.client.post("/api/verify/check", json={"code": r.json()["code"]}, headers=hdr)
            self.assertEqual(r.status_code, 200, r.text)
            token = token or r.json()["token"]
        return {"X-Access-Key": key, "X-Device-Token": token}

    def make_party(self, h, rotation="graveborn"):
        members = [{"name": n, "role": "main"} for n in ("Hilay", "Bobeek", "Vcte", "Jioe")] + [{"name": "Reserva", "role": "sub"}]
        r = self.client.post("/api/parties", json={"name": "Graveborn da semana", "kind": "both", "rotation": rotation,
                                                   "members": members}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["party"]["id"]

    def test_create_needs_own_char_and_auth(self):
        h = self.login("Hilay")
        self.assertEqual(self.client.get("/api/parties").status_code, 401)
        r = self.client.post("/api/parties", json={"name": "PT", "members": [{"name": "Outro Cara"}]}, headers=h)
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/parties", json={"name": "PT", "members": [{"name": "Hilay", "role": "sub"}]}, headers=h)
        self.assertEqual(r.status_code, 422)  # sem titular
        pid = self.make_party(h)
        self.assertEqual([p["id"] for p in self.client.get("/api/parties", headers=h).json()["parties"]], [pid])

    def test_outsider_cannot_see_vault(self):
        pid = self.make_party(self.login("Hilay"))
        other = self.login("Fulano Fora")
        self.assertEqual(self.client.get(f"/api/parties/{pid}/vault", headers=other).status_code, 403)
        self.assertEqual(self.client.post(f"/api/parties/{pid}/vault/prices", json={"item": "Icy Crypt Rune", "price": 1},
                                          headers=other).status_code, 403)

    def test_member_can_edit_but_not_roster(self):
        pid = self.make_party(self.login("Hilay"))
        jioe = self.login("Jioe")
        r = self.client.post(f"/api/parties/{pid}/vault/prices", json={"item": "icy crypt rune", "price": 12 * KK}, headers=jioe)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["stock"][0]["item"], "Icy Crypt Rune")
        r = self.client.post(f"/api/parties/{pid}", json={"name": "x y", "members": [{"name": "Jioe"}]}, headers=jioe)
        self.assertEqual(r.status_code, 403)

    def test_buy_needs_price_and_holder_in_party(self):
        h = self.login("Hilay")
        pid = self.make_party(h)
        url = f"/api/parties/{pid}/vault/items"
        self.assertEqual(self.client.post(url, json={"item": "Icy Crypt Rune", "origin": "buy", "holder": "Hilay"}, headers=h).status_code, 422)
        self.assertEqual(self.client.post(url, json={"item": "Icy Crypt Rune", "holder": "Fulano Fora"}, headers=h).status_code, 422)

    def test_graveborn_craft_range_and_sale(self):
        h = self.login("Hilay")
        pid = self.make_party(h)
        base = f"/api/parties/{pid}/vault"
        for item, price in zip(RUNES, (12, 12, 14, 40, 75)):
            self.client.post(f"{base}/prices", json={"item": item, "price": price * KK}, headers=h)
        add = lambda item, origin, cost=None, who="Hilay": self.client.post(  # noqa: E731
            f"{base}/items", json={"item": item, "origin": origin, "cost_each": cost, "holder": who}, headers=h)
        add("Ancient Crypt Rune", "drop")
        add("Icy Crypt Rune", "buy", 12 * KK, "Bobeek")
        add("Fiery Crypt Rune", "drop")
        add("Deathly Crypt Rune", "buy", 40 * KK, "Vcte")
        v = add("Necromantic Crypt Rune", "drop").json()
        self.assertEqual({(i["item"], i["origin"]) for i in v["items"]} >= {("Icy Crypt Rune", "buy")}, True)
        self.assertEqual(v["totals"]["units"], 5)
        self.assertEqual((v["totals"]["min"], v["totals"]["max"]), (52 * KK, 153 * KK))
        self.assertEqual(v["craft_set"]["missing"], [])
        ids = [i["id"] for i in v["items"]]
        # craft sem um dos itens: recusado
        r = self.client.post(f"{base}/crafts", json={"set": "crypt", "item_ids": ids[:4], "holder": "Hilay"}, headers=h)
        self.assertEqual(r.status_code, 422)
        r = self.client.post(f"{base}/crafts", json={"set": "crypt", "item_ids": ids, "holder": "Hilay", "result": "Crypt Bile"},
                             headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        c = r.json()["crafts"][0]
        self.assertEqual((c["min"], c["max"], c["cost"], c["sold_total"]), (52 * KK, 153 * KK, 52 * KK, None))
        self.assertEqual(r.json()["totals"]["units"], 0)
        # mudar o preço depois não muda a faixa guardada do craft
        self.client.post(f"{base}/prices", json={"item": "Necromantic Crypt Rune", "price": 1}, headers=h)
        # venda: o valor só é pedido agora
        r = self.client.post(f"{base}/crafts/{c['id']}", json={"sold_total": 120 * KK}, headers=h)
        c = r.json()["crafts"][0]
        self.assertEqual((c["max"], c["refund"], c["net"], c["each"]), (153 * KK, 52 * KK, 68 * KK, 17 * KK))
        got = {(t["receiver"], t["amount"]) for t in c["transfers"]}
        self.assertEqual(got, {("Bobeek", 29 * KK), ("Vcte", 57 * KK), ("Jioe", 17 * KK)})
        # já paguei (só quem paga/recebe)
        r = self.client.post(f"{base}/paid", json={"kind": "craft", "id": c["id"], "payer": "Hilay", "receiver": "Jioe"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(next(t for t in r.json()["crafts"][0]["transfers"] if t["receiver"] == "Jioe")["paid_at"])
        # desfazer o craft devolve as runas ao estoque
        r = self.client.delete(f"{base}/crafts/{c['id']}", headers=h)
        self.assertEqual(r.json()["totals"]["units"], 5)

    def test_service_rune_half_split_among_mains(self):
        # o exemplo: runa de 75kk no service → metade (37,5kk) ÷ 5 titulares = 7,5kk de cada um para o serviçado
        self.assertEqual(party_core.service_shares(party_core.service_half(75 * KK), 1, list("ABCDE"), "Cli")["each"],
                         7_500_000)
        h = self.login("Hilay")
        members = [{"name": n, "role": "main"} for n in ("Hilay", "Bobeek", "Vcte", "Jioe", "Kael Monge")]
        pid = self.client.post("/api/parties", json={"name": "GB", "rotation": "graveborn", "members": members},
                               headers=h).json()["party"]["id"]
        base = f"/api/parties/{pid}/vault"
        # sem serviçado ou sem valor: recusa
        r = self.client.post(f"{base}/items", json={"item": "Necromantic Crypt Rune", "origin": "service", "holder": "Hilay"}, headers=h)
        self.assertEqual(r.status_code, 422)
        r = self.client.post(f"{base}/items", json={"item": "Necromantic Crypt Rune", "origin": "service", "holder": "Hilay",
                                                    "client": "Cliente Serv"}, headers=h)
        self.assertEqual(r.status_code, 422)
        self.client.post(f"{base}/prices", json={"item": "Necromantic Crypt Rune", "price": 75 * KK}, headers=h)
        r = self.client.post(f"{base}/items", json={"item": "Necromantic Crypt Rune", "origin": "service", "holder": "Hilay",
                                                    "client": "Cliente Serv", "qty": 3}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        it = r.json()["items"][0]
        self.assertEqual((it["qty"], it["cost_each"], it["min"], it["max"]), (1, 37_500_000, 37_500_000, 37_500_000))
        sv = it["service"]
        self.assertEqual((sv["half"], sv["each"], len(sv["transfers"])), (37_500_000, 7_500_000, 5))
        self.assertEqual({t["receiver"] for t in sv["transfers"]}, {"Cliente Serv"})
        r = self.client.post(f"{base}/paid", json={"kind": "service", "id": it["id"], "payer": "Hilay", "receiver": "Cliente Serv"},
                             headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(next(t for t in r.json()["items"][0]["service"]["transfers"] if t["payer"] == "Hilay")["paid_at"])

    def test_craft_only_for_graveborn_party(self):
        h = self.login("Hilay")
        pid = self.make_party(h, rotation=None)
        r = self.client.post(f"/api/parties/{pid}/vault/crafts", json={"set": "crypt", "item_ids": [1], "holder": "Hilay"}, headers=h)
        self.assertEqual(r.status_code, 422)

    def test_registered_party_marks_sub_in_lootsplit(self):
        h = self.login("Hilay")
        members = [{"name": n, "role": "main"} for n in ("Hilay", "Bobeek", "Vcte", "Outro Main")] + [{"name": "Jioe", "role": "sub"}]
        self.client.post("/api/parties", json={"name": "PT fixa", "kind": "hunt", "members": members}, headers=h)
        r = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        tags = self.client.get("/api/hunts/Hilay", headers=h).json()["hunts"][0]["tags"]
        self.assertEqual(tags["Jioe"]["sub"], {"auto": True, "for": "Outro Main"})

    def test_item_sale_splits_among_mains(self):
        h = self.login("Hilay")
        pid = self.make_party(h)
        v = self.client.post(f"/api/parties/{pid}/vault/items", json={"item": "Gold Token", "qty": 4, "holder": "Hilay"},
                             headers=h).json()
        iid = v["items"][0]["id"]
        r = self.client.post(f"/api/parties/{pid}/vault/items/{iid}", json={"action": "sell", "sold_total": 400_000}, headers=h)
        it = r.json()["items"][0]
        self.assertEqual((it["each"], len(it["transfers"])), (100_000, 3))  # o substituto não entra na divisão
        # quem guarda item não sai da party
        r = self.client.post(f"/api/parties/{pid}/vault/items/{iid}", json={"action": "stock"}, headers=h)
        r = self.client.post(f"/api/parties/{pid}", json={"name": "Nova", "members": [{"name": "Bobeek"}, {"name": "Hilay", "role": "sub"}]},
                             headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post(f"/api/parties/{pid}", json={"name": "Nova", "members": [{"name": "Bobeek"}]}, headers=h)
        self.assertEqual(r.status_code, 403)  # sem personagem seu


if __name__ == "__main__":
    unittest.main()
