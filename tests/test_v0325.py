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

    def test_quem_nao_e_hardcore_nao_recebe(self):
        h = self.login("Hilay")
        place = self.client.post("/api/places", json={"name": "Outro Lugar"}, headers=h).json()["id"]
        r = self.client.post("/api/stacker", json={"raw_text": solo(2), "nickname": "Hilay", "place_id": place}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
