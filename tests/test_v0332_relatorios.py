"""0.33.2: períodos dos Relatórios (7 a 360 dias e Tudo) e exatidão dos números."""
import io
import re
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from tests import test_bosses as tb
from tests.test_core import EXAMPLE
from tests.test_revamp import solo
from artemis.server import app as server


def entry(days_ago: int, net: int = 100, xp: int = 0, seconds: int = 3600, xp_seconds: int | None = None) -> dict:
    day = (datetime.now(server.BRT).date() - timedelta(days=days_ago)).isoformat()
    e = {"day": day, "net": net, "gear": 0, "xp": xp, "seconds": seconds}
    if xp_seconds is not None:
        e["xp_seconds"] = xp_seconds
    return e


class PeriodosTests(unittest.TestCase):
    def _rows(self, entries):
        return {r["days"]: r for r in server._periods(entries)}

    def test_botoes_pedidos(self):
        self.assertEqual(server.REPORT_DAYS, (7, 15, 30, 45, 90, 180, 360, 0))

    def test_cada_periodo_tem_exatamente_n_dias(self):
        for days in server.REPORT_DAYS[:-1]:
            with self.subTest(days=days):
                dentro, fora = entry(days - 1, net=10), entry(days, net=1000)
                row = self._rows([dentro, fora])[days]
                self.assertEqual((row["n"], row["net"]), (1, 10))
                # o primeiro dia fora cai no período anterior, que também tem exatamente N dias
                self.assertEqual((row["prev"]["n"], row["prev"]["net"]), (1, 1000))
                antes = self._rows([entry(2 * days - 1), entry(2 * days)])[days]["prev"]
                self.assertEqual(antes["n"], 1)
                self.assertTrue(antes["complete"])

    def test_periodo_anterior_incompleto_e_tudo_sem_comparacao(self):
        rows = self._rows([entry(1), entry(8)])
        self.assertFalse(rows[7]["prev"]["complete"])
        self.assertIsNone(rows[0]["prev"])
        self.assertEqual(rows[0]["n"], 2)

    def test_dias_jogados_nao_conta_o_mesmo_dia_duas_vezes(self):
        row = self._rows([entry(1), entry(1), entry(2)])[7]
        self.assertEqual((row["n"], row["active_days"]), (3, 2))

    def test_xp_por_hora_ignora_o_tempo_sem_hunt_analyser(self):
        row = self._rows([entry(1, xp=2_000_000), entry(2, xp=0, xp_seconds=0)])[7]
        self.assertEqual((row["xp_h"], row["xp_n"], row["n"]), (2_000_000, 1, 2))
        self.assertEqual(row["net_h"], 100)  # o lucro por hora continua usando as duas


class RelatorioNumerosTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _hardcore(self):
        h = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        self.h = h
        return h

    def _rep(self, kind, days=0):
        r = self.client.get(f"/api/reports/Hilay?kind={kind}&days={days}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_todas_as_abas_aceitam_os_periodos_e_batem_com_o_panorama(self):
        h = self._hardcore()
        self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h)
        self.client.post("/api/bosses/session", json={"raw_text": tb.BOSS_SOLO, "nickname": "Hilay", "mode": "solo"}, headers=h)
        for kind in server.REPORT_KINDS:
            for days in server.REPORT_DAYS:
                with self.subTest(kind=kind, days=days):
                    d = self._rep(kind, days)
                    self.assertEqual(d["days"], days)
                    self.assertEqual([p["days"] for p in d["periods"]], list(server.REPORT_DAYS))
                    row = next(p for p in d["periods"] if p["days"] == days)
                    if kind == "drops":
                        self.assertEqual(row["net"], d["totals"]["loot_value"] + d["totals"]["boss_value"])
                        self.assertEqual(row["n"], d["totals"]["n"])
                    else:
                        self.assertEqual((row["n"], row["net"], row["xp_h"]),
                                         (d["totals"]["n"], d["totals"]["net"], d["totals"]["xp_h"]))

    def test_aba_tudo_respeita_as_regras_de_divisao_e_mostra_a_party(self):
        h = self._hardcore()
        hunt = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h).json()["hunt"]
        mine = {"duration_seconds": 5400, "raw_xp": 1_000_000, "xp": 1_500_000, "supplies": 0, "balance": 0, "damage": 1,
                "damage_h": 1, "healing": 1, "healing_h": 1, "started_at": hunt["started_at"], "ended_at": hunt["ended_at"],
                "kills": [], "loot": []}
        server.store.add_party_session(hunt["id"], "Hilay", mine, h["X-Access-Key"])
        rules = {"excluded": ["Hilay"], "fixed": {}}
        r = self.client.post(f"/api/hunt/{hunt['id']}/rules", json=rules, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        every, party = self._rep("all"), self._rep("party")
        self.assertEqual(party["totals"]["net"], 0)  # fora da divisão: termina com zero
        self.assertEqual(every["totals"]["net"], party["totals"]["net"])
        self.assertEqual([m["name"] for m in every["mates"]], [m["name"] for m in party["mates"]])
        self.assertTrue(every["mates"])

    def test_relatorio_soma_mais_de_500_lootsplits(self):
        self._hardcore()
        seen = []
        original = server.store.hunts_for_player

        def spy(name, limit=500):
            seen.append(limit)
            return original(name, limit)

        server.store.hunts_for_player = spy
        try:
            for kind in ("all", "party", "solo"):
                self._rep(kind)
        finally:
            server.store.hunts_for_player = original
        self.assertTrue(seen)
        self.assertEqual(set(seen), {-1})


class FiltroPorHuntTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login
    _hardcore = RelatorioNumerosTests._hardcore
    _rep = RelatorioNumerosTests._rep

    def test_filtra_numeros_periodos_gasto_e_excel(self):
        h = self._hardcore()
        a = self.client.post("/api/places", json={"name": "Hunt A de Teste"}, headers=h).json()["id"]
        b = self.client.post("/api/places", json={"name": "Hunt B de Teste"}, headers=h).json()["id"]
        gear = lambda path, body: self.client.post(f"/api/gear/Hilay{path}", json=body, headers=h)
        axe = gear("/item", {"name": "Axe", "kind": "axe", "slots": 2}).json()["items"][0]["id"]
        gear(f"/item/{axe}/imbue", {"imbuement": "vampirism", "tier": 3})
        st = gear("/set", {"name": "Set", "gear_ids": [axe]}).json()["sets"][0]["id"]
        ids = []
        for n, place in ((2, a), (5, b)):
            r = self.client.post("/api/stacker", json={"raw_text": solo(n), "nickname": "Hilay", "place_id": place}, headers=h)
            ids.append(r.json()["session"]["id"])
            gear("/assign", {"kind": "solo", "ref_id": ids[-1], "set_id": st})
        every = self._rep("all")
        self.assertEqual([o["place"] for o in every["place_options"]], ["Hunt A de Teste", "Hunt B de Teste"])
        only = {}
        for name in ("Hunt A de Teste", "Hunt B de Teste"):
            r = self.client.get("/api/reports/Hilay", params={"kind": "all", "days": 0, "place": name}, headers=h).json()
            self.assertEqual((r["place"], r["totals"]["n"]), (name, 1))
            self.assertEqual({row["place"] for row in r["rows"]}, {name})
            self.assertEqual(next(p for p in r["periods"] if p["days"] == 0)["n"], 1)
            self.assertEqual(len(r["place_options"]), 2)  # a lista continua com todas
            self.assertGreater(r["gear"]["total"], 0)
            only[name] = r
        for key in ("n", "net", "xp", "gear"):
            self.assertEqual(sum(r["totals"][key] for r in only.values()), every["totals"][key], key)
        vazio = self.client.get("/api/reports/Hilay", params={"kind": "party", "place": "Hunt A de Teste"}, headers=h).json()
        self.assertTrue(vazio["empty"])
        x = self.client.get("/api/export/Hilay", params={"sections": "sessions,gear_spend", "place": "Hunt A de Teste"}, headers=h)
        self.assertEqual(x.status_code, 200, x.text)
        z = zipfile.ZipFile(io.BytesIO(x.content))
        todo = " ".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
        self.assertIn("Hunt A de Teste", todo)
        self.assertNotIn("Hunt B de Teste", todo)


class VisitasDasTelasTests(unittest.TestCase):
    def test_toda_tela_do_menu_e_contada_e_tem_nome_no_painel(self):
        web = Path(__file__).resolve().parent.parent / "artemis" / "web"
        pages = set(re.findall(r'data-page="([a-z]+)"', (web / "index.html").read_text(encoding="utf-8")))
        self.assertTrue(pages)
        self.assertEqual(pages - server.TRACK_PAGES, set())
        admin = (web / "admin.js").read_text(encoding="utf-8")
        labels = admin[admin.index("const PAGE_PT"):admin.index("};", admin.index("const PAGE_PT"))]
        self.assertEqual({p for p in server.TRACK_PAGES if not re.search(rf"\b{p}:", labels)}, set())


if __name__ == "__main__":
    unittest.main()
