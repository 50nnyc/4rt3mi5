"""0.33.0: 📑 Relatórios (party, solo, boss, drops e tudo), só para o Player Hardcore, com o gasto invisível por fonte."""
import io
import unittest
import zipfile

from tests import test_bosses as tb
from tests.test_bosses import BOSS_SOLO
from tests.test_core import EXAMPLE
from tests.test_revamp import solo


class RelatoriosTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _hardcore(self):
        h = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        self.h = h
        return h

    def _g(self, path, body=None):
        return self.client.post(f"/api/gear/Hilay{path}", json=body or {}, headers=self.h)

    def _seed(self):
        """Um personagem com imbuement, anel e amuleto num set, usado numa sessão solo, num lootsplit e num boss."""
        h = self._hardcore()
        place = self.client.post("/api/places", json={"name": "Crypts de Teste"}, headers=h).json()["id"]
        axe = self._g("/item", {"name": "Axe", "kind": "axe", "slots": 2}).json()["items"][0]["id"]
        self._g(f"/item/{axe}/imbue", {"imbuement": "vampirism", "tier": 3})
        ring = self._g("/item", {"name": "-", "kind": "ring", "catalog": "ethereal"}).json()["items"][-1]["id"]
        self._g(f"/item/{ring}/recharge")
        amu = self._g("/item", {"name": "-", "kind": "amulet", "catalog": "turtle"}).json()["items"][-1]["id"]
        self._g(f"/item/{amu}/recharge")
        st = self._g("/set", {"name": "Tudo", "gear_ids": [axe, ring, amu]}).json()["sets"][0]["id"]
        sid = self.client.post("/api/stacker", json={"raw_text": solo(2), "nickname": "Hilay", "place_id": place}, headers=h).json()["session"]["id"]
        self.client.post("/api/stacker", json={"raw_text": solo(5), "nickname": "Hilay", "place_id": place}, headers=h)
        hunt = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h).json()["hunt"]
        self.client.post(f"/api/hunt/{hunt['id']}/place", json={"place_id": place}, headers=h)
        boss = self.client.post("/api/bosses/session", json={"raw_text": BOSS_SOLO, "nickname": "Hilay", "mode": "solo"}, headers=h).json()
        self._g("/assign", {"kind": "solo", "ref_id": sid, "set_id": st})
        self._g("/assign", {"kind": "hunt", "ref_id": hunt["id"], "set_id": st})
        self._g("/assign", {"kind": "boss", "ref_id": boss["session_id"], "set_id": st})
        return place

    def _rep(self, kind, days=0):
        r = self.client.get(f"/api/reports/Hilay?kind={kind}&days={days}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_so_hardcore_e_so_o_dono(self):
        h = self.login("Hilay")  # tipo comum
        for kind in ("party", "solo", "boss", "drops", "all"):
            self.assertEqual(self.client.get(f"/api/reports/Hilay?kind={kind}", headers=h).status_code, 403, kind)
        self.assertEqual(self.client.get("/api/party-report/Hilay", headers=h).status_code, 403)
        self.assertEqual(self.client.get("/api/export/Hilay", headers=h).status_code, 403)
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        self.assertEqual(self.client.get("/api/reports/Hilay?kind=all", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/reports/Hilay?kind=outro", headers=h).status_code, 422)
        other = self.login("Jioe")
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=other)
        self.assertEqual(self.client.get("/api/reports/Hilay?kind=all", headers=other).status_code, 403)

    def test_relatorios_vazios_nao_quebram(self):
        self._hardcore()
        for kind in ("party", "solo", "boss", "drops", "all"):
            r = self._rep(kind)
            self.assertTrue(r["empty"], kind)
            self.assertEqual(r["gear"]["total"], 0)

    def test_todos_os_relatorios_com_dados(self):
        self._seed()
        solo_r, party_r, all_r = self._rep("solo"), self._rep("party"), self._rep("all")
        self.assertFalse(solo_r["empty"])
        self.assertEqual(solo_r["totals"]["n"], 2)
        self.assertEqual(party_r["totals"]["n"], 1)
        self.assertEqual(all_r["totals"]["n"], 3)  # 2 sessões solo + 1 lootsplit
        self.assertEqual(all_r["totals"]["n"], solo_r["totals"]["n"] + party_r["totals"]["n"])
        for r in (solo_r, party_r, all_r):
            self.assertEqual(r["totals"]["net"], sum(d["net"] for d in r["daily"]))
            self.assertTrue(r["highlights"])
        # o líquido do dia fecha com a soma das linhas
        self.assertEqual(all_r["totals"]["net"], sum(x["net"] for x in all_r["rows"]))
        self.assertTrue(party_r["mates"])
        boss_r = self._rep("boss")
        self.assertGreater(boss_r["totals"]["n"], 0)
        self.assertTrue(boss_r["bosses"])
        drops_r = self._rep("drops")
        self.assertFalse(drops_r["empty"])
        self.assertTrue(drops_r["items"])
        self.assertIn("vault_stock", drops_r["totals"])

    def test_gasto_invisivel_por_fonte(self):
        self._seed()
        g = self._rep("all")["gear"]
        self.assertGreater(g["total"], 0)
        t = g["by_type"]
        self.assertGreater(t["imbuement"], 0)
        self.assertGreater(t["ring"], 0)
        self.assertGreater(t["amulet"], 0)
        self.assertEqual(t["imbuement"] + t["ring"] + t["amulet"], g["total"])
        self.assertEqual(sum(s["cost"] for s in g["sources"]), g["total"])
        self.assertAlmostEqual(sum(s["share"] for s in g["sources"]), 100, delta=0.5)
        self.assertEqual(sum(d["cost"] for d in g["by_day"]), g["total"])
        # cada escopo só conta o seu: o solo não vê o gasto do lootsplit nem o do boss
        solo_g, party_g, boss_g = self._rep("solo")["gear"], self._rep("party")["gear"], self._rep("boss")["gear"]
        self.assertGreater(solo_g["total"], 0)
        self.assertGreater(party_g["total"], 0)
        self.assertGreater(boss_g["total"], 0)
        self.assertEqual(solo_g["total"] + party_g["total"], g["total"])

    def test_periodo_filtra(self):
        self._seed()
        self.assertEqual(self._rep("all", 0)["totals"]["n"], self._rep("all", 0)["totals"]["n"])
        old = self._rep("all", 0)["totals"]["n"]
        self.assertLessEqual(self._rep("all", 7)["totals"]["n"], old)
        self.assertEqual(self.client.get("/api/reports/Hilay?kind=all&days=999", headers=self.h).status_code, 200)  # cai no padrão

    def test_excel_um_clique_traz_o_gasto_por_fonte(self):
        self._seed()
        secs = "sessions,days,places,loot,party,party_weekly,gear_spend,boss_items,vault,rare"
        r = self.client.get(f"/api/export/Hilay?sections={secs}&days=0", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertIsNone(z.testzip())
        wb = z.read("xl/workbook.xml").decode()
        for sheet in ("Gasto invisível", "Gasto invisível por dia", "Itens de boss", "Cofre de drops", "Drops raros", "Lootsplits"):
            self.assertIn(sheet, wb)
        # com período, ainda gera
        self.assertEqual(self.client.get("/api/export/Hilay?sections=sessions,gear_spend&days=7", headers=self.h).status_code, 200)

    def test_gasto_manual_fica_separado(self):
        self._seed()
        item = self.client.get("/api/gear/Hilay", headers=self.h).json()["items"][0]
        cid = item["charges"][0]["id"]
        self._g(f"/charge/{cid}/hours", {"hours": 2})
        g = self._rep("all")["gear"]
        self.assertGreater(g["manual"]["cost"], 0)
        self.assertEqual(g["manual"]["hours"], 2)
        self.assertEqual(g["by_type"]["imbuement"] + g["by_type"]["ring"] + g["by_type"]["amulet"], g["total"])  # fora do total das hunts


if __name__ == "__main__":
    unittest.main()
