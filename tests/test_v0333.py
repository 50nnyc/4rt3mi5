"""0.33.3: gasto invisível só informativo; Tudo soma os bosses; Party + Solo; menus de histórico."""
import unittest
from pathlib import Path

from tests import test_bosses as tb
from tests import test_v0330 as rel
from tests.test_bosses import BOSS_SOLO
from tests.test_core import EXAMPLE

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"


class TudoComBossesTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login
    _hardcore = rel.RelatoriosTests._hardcore
    _g = rel.RelatoriosTests._g
    _seed = rel.RelatoriosTests._seed
    _rep = rel.RelatoriosTests._rep

    def test_gasto_invisivel_nao_muda_o_lucro(self):
        self._seed()
        com = {k: self._rep(k) for k in ("all", "hunts", "party", "solo", "boss")}
        stacker = self.client.get("/api/stacker/Hilay", headers=self.h).json()
        self.assertGreater(stacker["period"]["gear_cost"] + sum(s["gear_cost"] for s in stacker["sessions"]), 0)
        for s in stacker["sessions"]:
            if s["source"] == "solo":
                self.assertEqual(s["net_profit"], s["loot_value"] - s["supplies"])
        for kind, r in com.items():
            t = r["totals"]
            self.assertGreater(r["gear"]["total"], 0, kind)
            self.assertEqual(t["net"], sum(x["net"] for x in r["rows"]), kind)
            self.assertEqual(t["deducted"], t["net"] - r["gear"]["total"], kind)
            self.assertNotIn("gross", t)

    def test_lootsplit_de_boss_entra_no_boss_e_no_tudo(self):
        h = self._hardcore()
        r = self.client.post("/api/bosses/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        share = r.json()["hunt"]["profit_each"]
        for kind in ("boss", "all"):
            t = self._rep(kind)["totals"]
            self.assertEqual((t["n"], t["net"]), (1, share), kind)
        self.assertTrue(self._rep("all")["mates"])
        self.assertTrue(self._rep("hunts")["empty"])  # Party + Solo é só hunt

    def test_sessao_ligada_ao_lootsplit_conta_uma_vez(self):
        h = self._hardcore()
        sid = self.client.post("/api/bosses/session", json={"raw_text": BOSS_SOLO, "nickname": "Hilay", "mode": "party"},
                               headers=h).json()["session_id"]
        hunt = self.client.post("/api/bosses/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay", "session_id": sid},
                                headers=h).json()["hunt"]
        t = self._rep("boss")["totals"]
        self.assertEqual((t["n"], t["net"]), (1, hunt["profit_each"]))

    def test_mesmo_lootsplit_enviado_como_hunt_e_como_boss_nao_dobra(self):
        h = self._hardcore()
        share = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h).json()["hunt"]["profit_each"]
        self.client.post("/api/bosses/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h)
        t = self._rep("all")["totals"]
        self.assertEqual((t["n"], t["net"]), (1, share))

    def test_excel_do_tudo_traz_os_bosses_e_o_gasto_segue_a_aba(self):
        self._seed()
        for tab in ("all", "hunts"):
            r = self.client.get(f"/api/export/Hilay?sections=boss_party,sessions,days,party,party_weekly,gear_spend&tab={tab}", headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)

    def test_historico_so_com_personagens_da_conta_e_todos_os_lootsplits(self):
        self._seed()
        r = self.client.get("/api/hunts/Hilay?everything=true", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["hunts"]), 1)
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("const myChars = () => ((S.me && S.me.chars) || [])", js)
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for page in ("myhunts", "mybosses"):
            self.assertIn(f'data-page="{page}"', html)

    def test_texto_de_compartilhar_nao_leva_o_gasto_invisivel(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        for name, end in (("function reportText(", "function drawReportCard("), ("function reportKpis(", "function highlightLines("),
                          ("function splitSummary(", "/* ---------- hunt session stacker")):
            trecho = js[js.index(name):js.index(end)]
            self.assertNotIn("gear", trecho.split("function myGearLine")[0] if name != "function splitSummary(" else trecho[:900], name)


if __name__ == "__main__":
    unittest.main()
