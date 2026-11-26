"""0.31.2: aviso quando o Input Analyser vem com valores baixos demais (ex.: "Recent values")."""
import unittest
from pathlib import Path

from fastapi import HTTPException

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.core import damage
from artemis.core.report import report_from_text
from artemis.server import app as server
from tests import test_bosses as tb
from tests.test_core import EXAMPLE
from tests.test_revamp import INPUT_1 as INPUT, solo
from tests.test_v0310 import COMPLETO


def rep(text):
    return report_from_text(text)

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"


class RegraTests(unittest.TestCase):
    def test_total_baixo_numa_hunt_longa(self):
        # caso real: 140.241 em 2h14 (8033 s) = ~17 de dano por segundo
        self.assertTrue(damage.looks_low({"total": 140241}, 8033))

    def test_total_normal(self):
        self.assertFalse(damage.looks_low({"total": 5859794}, 8033))

    def test_hunt_curta_nao_avisa(self):
        self.assertFalse(damage.looks_low({"total": 3000}, 300))

    def test_compara_com_a_pt(self):
        self.assertTrue(damage.looks_low({"total": 400000}, None, [5000000, 6000000]))
        self.assertFalse(damage.looks_low({"total": 4000000}, None, [5000000, 6000000]))

    def test_sem_dados_nao_avisa(self):
        self.assertFalse(damage.looks_low({"total": 10}, None, []))


class AvisoTests(unittest.TestCase):
    def test_avisa_e_deixa_confirmar(self):
        with self.assertRaises(HTTPException) as cm:
            server._check_low_input({"total": 140241}, 8033, [], False)
        self.assertEqual(cm.exception.status_code, 409)
        d = cm.exception.detail
        self.assertEqual(d["reason"], "low_input")
        self.assertIn("Session values", d["hint"])
        self.assertIn("Recent values", d["hint"])
        server._check_low_input({"total": 140241}, 8033, [], True)  # confirmou: passa

    def test_tela_tem_o_botao(self):  # noqa: D102 (mantido abaixo)
        self._tela()

    def _tela(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("input-confirm", js)
        self.assertIn("low_input", js)


class AdminCorrigeTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def test_admin_corrige_input_party_e_sessao(self):
        adm = {"X-Admin-Token": server.CONFIG["admin_token"]}
        hilay = self.login("Hilay")
        a = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=hilay).json()
        hid = a["hunt"]["id"]
        # sem o token do administrador, nada disso funciona
        self.assertEqual(self.client.post(f"/api/admin/hunt/{hid}/party", json={"raw_text": COMPLETO}).status_code, 401)
        # Party Hunt Analyser: troca pelo texto corrigido, no mesmo registro
        r = self.client.post(f"/api/admin/hunt/{hid}/party", json={"raw_text": COMPLETO}, headers=adm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["hunt"]["id"], hid)
        self.assertEqual(r.json()["hunt"]["duration_seconds"], rep(COMPLETO)["duration_seconds"])
        # Input Analyser: corrige e apaga
        server.store.add_input("hunt", hid, "Hilay", damage.parse_input(INPUT), "k")
        novo = INPUT.replace("Total: 868", "Total: 5,000")
        r = self.client.post("/api/admin/input", json={"kind": "hunt", "ref_id": hid, "name": "Hilay", "raw_text": novo}, headers=adm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["input"]["total"], 5000)
        self.assertEqual(self.client.delete(f"/api/admin/input/hunt/{hid}/Hilay", headers=adm).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/admin/input/hunt/{hid}/Hilay", headers=adm).status_code, 404)
        # Hunt Analyser (solo)
        s1 = self.client.post("/api/stacker", json={"raw_text": solo(2), "nickname": "Hilay"}, headers=hilay).json()["session"]["id"]
        r = self.client.post(f"/api/admin/solo/{s1}/session", json={"raw_text": solo(3)}, headers=adm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["session"]["id"], s1)


if __name__ == "__main__":
    unittest.main()
