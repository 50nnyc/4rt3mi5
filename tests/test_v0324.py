"""0.32.4: trocar imbuement, validação ao editar o item e o reinício que não perde o imbuement."""
import unittest
from unittest import mock

from artemis.server import app as server
from tests import test_bosses as tb
from tests.test_core import EXAMPLE


class TrocaDeImbuementTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _start(self, slots=2):
        h = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        self.h = h
        self.gid = self._post("/item", {"name": "Teste Axe", "kind": "axe", "slots": slots}).json()["items"][0]["id"]
        return h

    def _post(self, path, body=None):
        return self.client.post(f"/api/gear/Hilay{path}", json=body or {}, headers=self.h)

    def _item(self):
        return self.client.get("/api/gear/Hilay", headers=self.h).json()["items"][0]

    def test_trocar_troca_o_tipo_e_o_nivel_e_zera_o_contador(self):
        self._start()
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "vampirism", "tier": 3})
        cid = self._item()["charges"][0]["id"]
        self.assertEqual(self._post(f"/charge/{cid}/hours", {"hours": 3}).status_code, 200)
        r = self._post(f"/charge/{cid}/swap", {"imbuement": "void", "tier": 2, "hours": 1})
        self.assertEqual(r.status_code, 200, r.text)
        it = self._item()
        self.assertEqual([(c["imbuement"], c["tier"], c["hours_used"]) for c in it["charges"]], [("void", 2, 0)])
        # o acumulado do equipamento guarda o que o antigo já tinha usado (3 h + 1 h informada na troca)
        life = {x["imbuement"]: x["hours"] for x in it["lifetime"]}
        self.assertAlmostEqual(life["vampirism"], 4, places=2)
        self.assertNotIn("void", life)

    def test_trocar_so_o_nivel_do_mesmo_imbuement(self):
        self._start()
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "vampirism", "tier": 1})
        cid = self._item()["charges"][0]["id"]
        self.assertEqual(self._post(f"/charge/{cid}/swap", {"imbuement": "vampirism", "tier": 3}).status_code, 200)
        self.assertEqual(self._item()["charges"][0]["tier"], 3)

    def test_trocar_por_um_que_ja_esta_em_outro_slot_nao_pode(self):
        self._start()
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "vampirism", "tier": 3})
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "void", "tier": 3})
        first = self._item()["charges"][0]["id"]
        r = self._post(f"/charge/{first}/swap", {"imbuement": "void", "tier": 3})
        self.assertEqual(r.status_code, 422)
        self.assertEqual([c["imbuement"] for c in self._item()["charges"]], ["vampirism", "void"])  # nada mudou

    def test_trocar_respeita_o_efeito_de_fabrica(self):
        self._start()
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "vampirism", "tier": 3})
        self.client.put(f"/api/gear/Hilay/item/{self.gid}", json={"name": "Teste Axe", "kind": "axe", "slots": 2, "elements": ["fire"]}, headers=self.h)
        cid = self._item()["charges"][0]["id"]
        r = self._post(f"/charge/{cid}/swap", {"imbuement": "scorch", "tier": 1})
        self.assertEqual(r.status_code, 422)
        self.assertIn("já traz", r.text)

    def test_editar_item_nao_deixa_ficar_incoerente(self):
        self._start()
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "vampirism", "tier": 3})
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "void", "tier": 3})
        put = lambda **kw: self.client.put(f"/api/gear/Hilay/item/{self.gid}", headers=self.h,
                                           json={"name": "Teste Axe", "kind": "axe", "slots": 2, "elements": [], **kw})
        self.assertEqual(put(slots=1).status_code, 422)  # 2 imbuements não cabem em 1 slot
        self.assertEqual(put(slots=3).status_code, 200)
        self.assertEqual(put(elements=["fire"]).status_code, 200)  # fogo não bloqueia nada que está no item

    def test_elemento_que_bloqueia_imbuement_ativo_e_recusado(self):
        self._start()
        for item in ("Fiery Heart", "Green Dragon Scale", "Demon Horn"):
            self._post("/price", {"item": item, "price": 1000})
        self.assertEqual(self._post(f"/item/{self.gid}/imbue", {"imbuement": "scorch", "tier": 1}).status_code, 200)
        r = self.client.put(f"/api/gear/Hilay/item/{self.gid}", headers=self.h,
                            json={"name": "Teste Axe", "kind": "axe", "slots": 2, "elements": ["fire"]})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self._item()["elements"], [])

    def test_reiniciar_sem_preco_nao_perde_o_imbuement(self):
        self._start()
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "vampirism", "tier": 3})
        cid = self._item()["charges"][0]["id"]
        with mock.patch.object(server.imbuing, "best_plan", return_value={"total": None, "missing": ["x"]}):
            self.assertEqual(self._post(f"/charge/{cid}/restart", {"hours": 2}).status_code, 422)
            self.assertEqual(self._post(f"/charge/{cid}/swap", {"imbuement": "void", "tier": 3}).status_code, 422)
        it = self._item()
        self.assertEqual([c["id"] for c in it["charges"]], [cid])  # continua lá, e as 2 h não foram somadas
        self.assertEqual(it["lifetime_hours"], 0)

    def test_ciclo_completo_tirar_e_voltar_a_imbuir(self):
        # põe, usa numa hunt, tira, põe de novo, apaga a hunt: nada quebra e o acumulado só diminui pelo que a hunt tinha
        self._start()
        self._post(f"/item/{self.gid}/imbue", {"imbuement": "vampirism", "tier": 3})
        st = self._post("/set", {"name": "S", "gear_ids": [self.gid]}).json()["sets"][0]
        hunt = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=self.h).json()["hunt"]
        a = self._post("/assign", {"kind": "hunt", "ref_id": hunt["id"], "set_id": st["id"]}).json()
        self.assertGreater(a["hours"], 0)
        cid = self._item()["charges"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/gear/Hilay/charge/{cid}", headers=self.h).status_code, 200)
        self.assertEqual(self._item()["charges"], [])
        self.assertEqual(self._post(f"/item/{self.gid}/imbue", {"imbuement": "vampirism", "tier": 3}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/hunt/{hunt['id']}", headers=self.h).status_code, 200)
        it = self._item()
        self.assertEqual(len(it["charges"]), 1)
        self.assertEqual(it["charges"][0]["hours_used"], 0)
        self.assertEqual(it["lifetime_hours"], 0)  # a hunt apagada devolveu as horas
        # sair e entrar de novo: tudo continua no servidor
        again = self.client.get("/api/gear/Hilay", headers=self.h).json()
        self.assertEqual(len(again["items"][0]["charges"]), 1)
        self.assertEqual(len(again["sets"]), 1)


if __name__ == "__main__":
    unittest.main()

