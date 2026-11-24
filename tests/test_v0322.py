"""0.32.2: efeito de fábrica, imbuements na party, relatório da party, Tibia Coin e exportação para Excel."""
import io
import unittest
import zipfile

from artemis.core import imbuing, xlsx
from artemis.core.session import parse_solo_session
from artemis.server import app as server
from tests import test_bosses as tb
from tests.test_core import EXAMPLE
from tests.test_revamp import solo


class EfeitoDeFabricaTests(unittest.TestCase):
    def test_elemento_bloqueia_o_mesmo_imbuement(self):
        # item com proteção de fogo não aceita Dragon Hide, mas aceita as outras proteções
        err = imbuing.check_imbue("armor", 3, [], [], "dragon_hide", 3, ["fire"])
        self.assertTrue(err)
        self.assertIsNone(imbuing.check_imbue("armor", 3, [], [], "quara_scale", 3, ["fire"]))
        # arma com dano de gelo não aceita Frost
        self.assertTrue(imbuing.check_imbue("axe", 2, [], [], "frost", 3, ["ice"]))
        self.assertIsNone(imbuing.check_imbue("axe", 2, [], [], "scorch", 3, ["ice"]))
        # físico não bloqueia nada
        self.assertIsNone(imbuing.check_imbue("armor", 3, [], [], "dragon_hide", 3, ["physical"]))

    def test_cada_elemento_aponta_para_imbuements_que_existem(self):
        for e, keys in imbuing.ELEMENT_BLOCKS.items():
            self.assertIn(e, imbuing.ELEMENTS)
            for k in keys:
                self.assertIn(k, imbuing.CATALOG)

    def test_lista_de_itens_conhecidos(self):
        known = imbuing.known_items()
        self.assertGreater(len(known), 300)
        for it in known:
            self.assertIn(it["kind"], imbuing.GEAR_KINDS)
            self.assertIn(it["slots"], (1, 2, 3))
            self.assertTrue(set(it["elements"]) <= set(imbuing.ELEMENTS))
        self.assertTrue(any(it["elements"] for it in known))


class ImbuementsNaPartyTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _hardcore(self, name):
        h = self.login(name)
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        return h

    def _setup_set(self, name, h, place_id=None):
        post = lambda path, body=None: self.client.post(f"/api/gear/{name}{path}", json=body or {}, headers=h)
        gid = post("/item", {"name": "Magic Plate Armor", "kind": "armor", "slots": 3, "elements": ["fire"]}).json()["items"][0]["id"]
        self.assertEqual(post(f"/item/{gid}/imbue", {"imbuement": "dragon_hide", "tier": 3}).status_code, 422)  # fogo de fábrica
        self.assertEqual(post(f"/item/{gid}/imbue", {"imbuement": "vampirism", "tier": 3}).status_code, 200)
        st = post("/set", {"name": "Crypts", "gear_ids": [gid], "place_id": place_id}).json()["sets"][0]
        return gid, st["id"]

    def _hours(self, name, h):
        return self.client.get(f"/api/gear/{name}", headers=h).json()["items"][0]["charges"][0]["hours_used"]

    def test_apagar_hunt_party_devolve_as_horas(self):
        h = self._hardcore("Hilay")
        gid, set_id = self._setup_set("Hilay", h)
        hunt = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h).json()["hunt"]
        a = self.client.post("/api/gear/Hilay/assign", json={"kind": "hunt", "ref_id": hunt["id"], "set_id": set_id}, headers=h).json()
        self.assertGreater(a["cost"], 0)
        self.assertGreater(self._hours("Hilay", h), 0)
        life = lambda: self.client.get("/api/gear/Hilay", headers=h).json()["items"][0]["lifetime_hours"]
        used = life()
        self.assertAlmostEqual(used, self._hours("Hilay", h), places=2)
        # refazer o imbuement zera o ciclo, mas o acumulado do equipamento só cresce (inclui as horas extras)
        cid = self.client.get("/api/gear/Hilay", headers=h).json()["items"][0]["charges"][0]["id"]
        self.client.post(f"/api/gear/Hilay/charge/{cid}/restart", json={"hours": 2}, headers=h)
        self.assertEqual(self._hours("Hilay", h), 0)
        self.assertAlmostEqual(life(), used + 2, places=2)
        item = self.client.get("/api/gear/Hilay", headers=h).json()["items"][0]
        self.assertEqual(item["lifetime"][0]["label"], "Vampirism")
        self.assertTrue(self.client.get("/api/gear/Hilay/report", headers=h).json()["lifetime"])
        # apagar a hunt tira do acumulado só o que ela tinha somado
        self.assertEqual(self.client.delete(f"/api/hunt/{hunt['id']}", headers=h).status_code, 200)
        self.assertAlmostEqual(life(), 2, places=2)

    def test_quem_tem_set_para_o_local_paga_sozinho_e_aparece_no_relatorio(self):
        h = self._hardcore("Hilay")
        j = self._hardcore("Jioe")
        place = self.client.post("/api/places", json={"name": "Crypts de Teste"}, headers=h).json()["id"]
        _, set_id = self._setup_set("Jioe", j, place)  # só o Jioe tem set para esse local
        hunt = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h).json()["hunt"]
        server.store.add_party_session(hunt["id"], "Jioe", parse_solo_session(solo(7)).to_dict(), "k")  # o Hunt Analyser dele
        self.assertEqual(self._hours("Jioe", j), 0)
        self.assertEqual(self.client.post(f"/api/hunt/{hunt['id']}/place", json={"place_id": place}, headers=h).status_code, 200)
        self.assertGreater(self._hours("Jioe", j), 0)  # entrou o tempo do imbuement dele
        # entra no saldo dele (Início) e na hunt dele; o Hilay não tem set e não paga nada
        s = self.client.get("/api/stacker/Jioe?source=party", headers=j).json()["sessions"][0]
        self.assertGreater(s["gear_cost"], 0)
        self.assertEqual(s["net_profit"], s["profit_each"] - s["gear_cost"])
        mine = next(x for x in self.client.get("/api/hunts/Jioe", headers=j).json()["hunts"] if x["id"] == hunt["id"])
        self.assertEqual(mine["my_gear"][0]["cost"], s["gear_cost"])
        self.assertEqual(server.store.session_gear_one("Hilay", "hunt", hunt["id"]), None)  # quem não tem set não paga
        # relatório semanal da party
        rep = self.client.get("/api/party-report/Jioe", headers=j).json()
        self.assertTrue(rep["gear"])
        w = rep["weeks"][0]
        self.assertEqual(w["hunts"], 1)
        self.assertEqual(w["gear_cost"], s["gear_cost"])
        self.assertEqual(w["net"], w["profit"] - w["gear_cost"])
        self.assertTrue(w["mates"])
        # escolher outro set à mão vale mais que o automático (e sem set tira o custo)
        self.client.post("/api/gear/Jioe/assign", json={"kind": "hunt", "ref_id": hunt["id"], "set_id": None}, headers=j)
        self.assertEqual(self._hours("Jioe", j), 0)
        self.client.post(f"/api/hunt/{hunt['id']}/place", json={"place_id": place}, headers=h)
        self.assertEqual(self._hours("Jioe", j), 0)
        # só o dono vê o relatório
        self.assertEqual(self.client.get("/api/party-report/Jioe", headers=h).status_code, 403)

    def test_apagar_sessao_de_boss_nao_devolve(self):
        db = server.store
        db.usage_add("Hilay", "boss", 99, None, "x", 1.0, 10, "2026-11-24")
        db.release_ref_gear("hunt", 99)  # outra referência: o uso do boss continua
        self.assertEqual(len(db.usage_for_session("Hilay", "boss", 99)), 1)


class TibiaCoinTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def test_valor_por_personagem(self):
        h = self.login("Hilay")
        self.assertEqual(self.client.get("/api/coin/Hilay", headers=h).json()["gold"], 0)
        r = self.client.post("/api/coin/Hilay", json={"gold": 38_000}, headers=h).json()
        self.assertEqual((r["x1"], r["x25"], r["x250"]), (38_000, 950_000, 9_500_000))
        me = self.client.get("/api/me", headers=h).json()
        self.assertEqual(next(c for c in me["chars"] if c["name"] == "Hilay")["tc_gold"], 38_000)
        self.assertEqual(self.client.post("/api/coin/Hilay", json={"gold": -1}, headers=h).status_code, 422)
        j = self.login("Jioe")
        self.assertEqual(self.client.post("/api/coin/Hilay", json={"gold": 1}, headers=j).status_code, 403)
        self.client.post("/api/coin/Hilay", json={"gold": 0}, headers=h)
        self.assertEqual(self.client.get("/api/coin/Hilay", headers=h).json()["gold"], 0)


class ExportarExcelTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def test_xlsx_basico(self):
        data = xlsx.build([("Teste: [1]", ["Nome", "Valor"], [["A & B <c>", 1234], ["x", 1.5], ["y", None]])])
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIsNone(z.testzip())
        for part in ("[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/styles.xml"):
            self.assertIn(part, z.namelist())
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("A &amp; B &lt;c&gt;", sheet)
        self.assertIn("<v>1234</v>", sheet)
        self.assertNotIn("[", z.read("xl/workbook.xml").decode().split("<sheets>")[1])  # nome de aba sem caracteres proibidos
        from xml.etree import ElementTree as ET
        for part in z.namelist():  # todo XML precisa ser bem formado, senão o Excel pede para "reparar" o arquivo
            ET.fromstring(z.read(part))

    def test_exporta_o_que_foi_pedido(self):
        h = self.login("Hilay")
        self.client.post("/api/stacker", json={"raw_text": solo(2), "nickname": "Hilay"}, headers=h)
        self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h)
        r = self.client.get("/api/export/Hilay?sections=sessions,days,party,party_weekly,xp,loot", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("spreadsheetml", r.headers["content-type"])
        z = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertIsNone(z.testzip())
        wb = z.read("xl/workbook.xml").decode()
        for name in ("Sessões", "Por dia", "Lootsplits", "Party por semana", "XP por dia", "Itens coletados"):
            self.assertIn(name, wb)
        self.assertEqual(self.client.get("/api/export/Hilay", headers=self.login("Jioe")).status_code, 403)
        # sem tipo Hardcore, as abas de equipamento ficam de fora
        self.client.post("/api/prefs/player-type", json={"player_type": "comum"}, headers=h)
        names = [s["key"] for s in self.client.get("/api/export/sections", headers=h).json()["sections"]]
        self.assertNotIn("gear_items", names)
        self.assertIn("sessions", names)

    def test_exporta_equipamentos_do_hardcore(self):
        h = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        self.client.post("/api/gear/Hilay/item", json={"name": "Magic Plate Armor", "kind": "armor", "slots": 2, "elements": ["fire"]}, headers=h)
        r = self.client.get("/api/export/Hilay?sections=gear_items,gear_weekly", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertIn("Equipamentos", z.read("xl/workbook.xml").decode())
        self.assertIn("fire", z.read("xl/worksheets/sheet1.xml").decode())


if __name__ == "__main__":
    unittest.main()
