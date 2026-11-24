"""0.32.5: o set da hunt entra sozinho nas sessões solo (como na party)."""
import unittest

from tests import test_bosses as tb
from tests.test_revamp import solo


class SetAutomaticoSoloTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _prep(self):
        h = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        self.h = h
        place = self.client.post("/api/places", json={"name": "Crypts de Teste"}, headers=h).json()["id"]
        gid = self._post("/item", {"name": "Teste Axe", "kind": "axe", "slots": 2}).json()["items"][0]["id"]
        self._post(f"/item/{gid}/imbue", {"imbuement": "vampirism", "tier": 3})
        st = self._post("/set", {"name": "Crypts", "gear_ids": [gid], "place_id": place}).json()["sets"][0]
        return place, st["id"]

    def _post(self, path, body=None):
        return self.client.post(f"/api/gear/Hilay{path}", json=body or {}, headers=self.h)

    def _hours(self):
        return self.client.get("/api/gear/Hilay", headers=self.h).json()["items"][0]["charges"][0]["hours_used"]

    def test_envio_com_local_aplica_o_set(self):
        place, set_id = self._prep()
        r = self.client.post("/api/stacker", json={"raw_text": solo(2), "nickname": "Hilay", "place_id": place}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertGreater(self._hours(), 0)
        sid = r.json()["session"]["id"]
        # tirou o set à mão: trocar o local não volta a aplicar
        self._post("/assign", {"kind": "solo", "ref_id": sid, "set_id": None})
        self.assertEqual(self._hours(), 0)
        self.client.post(f"/api/stacker/session/{sid}/place", json={"place_id": place}, headers=self.h)
        self.assertEqual(self._hours(), 0)

    def test_definir_o_local_depois_aplica_o_set(self):
        place, set_id = self._prep()
        sid = self.client.post("/api/stacker", json={"raw_text": solo(3), "nickname": "Hilay"}, headers=self.h).json()["session"]["id"]
        self.assertEqual(self._hours(), 0)
        self.client.post(f"/api/stacker/session/{sid}/place", json={"place_id": place}, headers=self.h)
        self.assertGreater(self._hours(), 0)

    def test_set_lembrado_por_hunt_so_vale_sozinho_depois_de_confirmar(self):
        h = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        self.h = h
        place = self.client.post("/api/places", json={"name": "Lugar do Set"}, headers=h).json()["id"]
        gid = self._post("/item", {"name": "Teste Axe", "kind": "axe", "slots": 2}).json()["items"][0]["id"]
        self._post(f"/item/{gid}/imbue", {"imbuement": "vampirism", "tier": 3})
        a = self._post("/set", {"name": "A", "gear_ids": [gid]}).json()["sets"][0]["id"]  # set sem local
        b = self._post("/set", {"name": "B", "gear_ids": [gid]}).json()["sets"][-1]["id"]
        up = lambda n: self.client.post("/api/stacker", json={"raw_text": solo(n), "nickname": "Hilay", "place_id": place}, headers=self.h).json()["session"]["id"]
        suggest = lambda sid: self.client.get(f"/api/gear/Hilay/suggest?place_id={place}&kind=solo&ref_id={sid}", headers=self.h).json()
        s1 = up(2)
        self.assertEqual(self._hours(), 0)  # primeira vez: nada entra sozinho, o app pergunta
        self.assertIsNone(suggest(s1)["set"])
        self._post("/assign", {"kind": "solo", "ref_id": s1, "set_id": a})
        sug = suggest(s1)
        self.assertEqual((sug["set"]["id"], sug["confirmed"]), (a, False))  # lembrou, mas ainda não confirmou
        used = self._hours()
        s2 = up(3)
        self.assertEqual(self._hours(), used)  # sem confirmação, segunda sessão não entra sozinha
        self._post("/assign", {"kind": "solo", "ref_id": s2, "set_id": a, "confirm": True})
        self.assertTrue(suggest(s2)["confirmed"])
        before = self._hours()
        s3 = up(4)
        self.assertGreater(self._hours(), before)  # confirmado: o set entra sozinho
        # trocar para o set B volta a perguntar nas próximas vezes
        self._post("/assign", {"kind": "solo", "ref_id": s3, "set_id": b})
        sug = suggest(s3)
        self.assertEqual((sug["set"]["id"], sug["confirmed"]), (b, False))
        # tirar o set apaga a preferência
        self._post("/assign", {"kind": "solo", "ref_id": s3, "set_id": None})
        self.assertIsNone(suggest(s3)["set"])

    def test_quem_nao_e_hardcore_nao_recebe(self):
        h = self.login("Hilay")
        place = self.client.post("/api/places", json={"name": "Outro Lugar"}, headers=h).json()["id"]
        r = self.client.post("/api/stacker", json={"raw_text": solo(2), "nickname": "Hilay", "place_id": place}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
