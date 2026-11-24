"""0.31.0: o mesmo Party Hunt Analyser enviado por mais de um membro vira um lootsplit só."""
import unittest
from pathlib import Path

from artemis.core import samesession
from artemis.server import app as server
from tests import test_bosses as tb
from tests.test_core import EXAMPLE

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"

# a mesma sessão copiada por outro membro, com a sessão ainda rodando (fim 10 minutos antes, loot menor)
PARCIAL = (EXAMPLE.replace("to 2026-11-04, 20:21:07", "to 2026-11-04, 20:11:07").replace("Session: 01:30h", "Session: 01:20h")
           .replace("Loot: 10,423,400", "Loot: 9,000,000").replace("Balance: 9,278,162", "Balance: 7,854,762"))
# a mesma PT, outra hunt logo depois (nada a ver com a primeira)
SEGUINTE = (EXAMPLE.replace("From 2026-11-04, 18:50:49 to 2026-11-04, 20:21:07", "From 2026-11-04, 20:40:00 to 2026-11-04, 21:40:00")
            .replace("Session: 01:30h", "Session: 01:00h"))
# a versão mais completa (a sessão terminou depois)
COMPLETO = (EXAMPLE.replace("to 2026-11-04, 20:21:07", "to 2026-11-04, 21:21:07").replace("Session: 01:30h", "Session: 02:30h")
            .replace("Loot: 10,423,400", "Loot: 12,000,000").replace("Balance: 9,278,162", "Balance: 10,854,762"))


def rep(text):
    from artemis.core.report import report_from_text
    return report_from_text(text)


class RegraTests(unittest.TestCase):
    def test_mesma_sessao_com_fim_diferente(self):
        self.assertTrue(samesession.same_session(rep(EXAMPLE), rep(PARCIAL)))

    def test_hunts_seguidas_da_mesma_pt_sao_diferentes(self):
        self.assertFalse(samesession.same_session(rep(EXAMPLE), rep(SEGUINTE)))

    def test_outra_pt_nao_e_a_mesma(self):
        outra = EXAMPLE.replace("Bobeek", "Zeca").replace("Jioe", "Mara")
        self.assertFalse(samesession.same_session(rep(EXAMPLE), rep(outra)))

    def test_mais_completa(self):
        self.assertTrue(samesession.is_more_complete(rep(COMPLETO), rep(EXAMPLE)))
        self.assertFalse(samesession.is_more_complete(rep(PARCIAL), rep(EXAMPLE)))
        self.assertFalse(samesession.is_more_complete(rep(EXAMPLE), rep(EXAMPLE)))


class EnvioTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _send(self, hdr, nick, text):
        r = self.client.post("/api/lootsplit", json={"raw_text": text, "nickname": nick}, headers=hdr)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_segundo_membro_nao_duplica(self):
        hilay, vcte = self.login("Hilay"), self.login("Vcte")
        a = self._send(hilay, "Hilay", EXAMPLE)
        self.assertTrue(a["created"])
        self.assertIsNone(a["same"])
        b = self._send(vcte, "Vcte", PARCIAL)  # fim diferente: a impressão digital exata não pegaria
        self.assertFalse(b["created"])
        self.assertEqual(b["hunt"]["id"], a["hunt"]["id"])
        self.assertEqual(b["same"]["kind"], "same")
        self.assertEqual(b["same"]["by"], "Hilay")
        self.assertEqual(len(server.store.hunts_for_player("Vcte")), 1)
        self.assertEqual(b["hunt"]["balance"], a["hunt"]["balance"])  # a versão menor não troca a oficial

    def test_versao_mais_completa_atualiza_no_lugar(self):
        hilay, vcte = self.login("Hilay"), self.login("Vcte")
        a = self._send(hilay, "Hilay", EXAMPLE)
        server.store.set_paid("hunt", a["hunt"]["id"], "Jioe", "Hilay", 1, "x", True)  # um pagamento qualquer
        b = self._send(vcte, "Vcte", COMPLETO)
        self.assertEqual(b["same"]["kind"], "updated")
        self.assertEqual(b["hunt"]["id"], a["hunt"]["id"])
        self.assertEqual(b["hunt"]["duration_seconds"], rep(COMPLETO)["duration_seconds"])  # ficou a versão mais longa
        self.assertEqual(len(server.store.hunts_for_player("Hilay")), 1)

    def test_texto_identico_continua_igual(self):
        hilay, vcte = self.login("Hilay"), self.login("Vcte")
        self._send(hilay, "Hilay", EXAMPLE)
        b = self._send(vcte, "Vcte", EXAMPLE)
        self.assertFalse(b["created"])
        self.assertEqual(len(server.store.hunts_for_player("Vcte")), 1)

    def test_hunt_seguinte_da_mesma_pt_e_outra_hunt(self):
        hilay = self.login("Hilay")
        self._send(hilay, "Hilay", EXAMPLE)
        b = self._send(hilay, "Hilay", SEGUINTE)
        self.assertTrue(b["created"])
        self.assertEqual(len(server.store.hunts_for_player("Hilay")), 2)

    def test_input_do_segundo_membro_vai_na_hunt_unica(self):
        hilay, vcte = self.login("Hilay"), self.login("Vcte")
        a = self._send(hilay, "Hilay", EXAMPLE)
        b = self._send(vcte, "Vcte", PARCIAL)
        self.assertEqual(b["hunt"]["id"], a["hunt"]["id"])
        self.assertIn("inputs", b["hunt"])  # o card traz os passos de cada um (Input Analyser e Hunt Analyser)


class UnirTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _duas(self):
        """Duas cópias já salvas (como estava antes da 0.31.0): entram direto pelo banco."""
        a = server.store.add_hunt(rep(EXAMPLE), EXAMPLE, "Hilay", None)[0]
        b = server.store.add_hunt(rep(PARCIAL), PARCIAL, "Vcte", None)[0]
        self.assertNotEqual(a["id"], b["id"])
        return a, b

    def test_lista_marca_as_parecidas(self):
        a, b = self._duas()
        hilay = self.login("Hilay")
        d = self.client.get("/api/hunts/Hilay", headers=hilay).json()
        self.assertEqual(len(d["hunts"]), 2)
        for h in d["hunts"]:
            self.assertEqual(len(h["similar"]), 1)
        self.assertEqual({h["similar"][0]["id"] for h in d["hunts"]}, {a["id"], b["id"]})

    def test_unir_fica_com_a_mais_completa(self):
        a, b = self._duas()
        server.store.set_paid("hunt", b["id"], "Jioe", "Hilay", 1, "x", True)
        hilay = self.login("Hilay")
        self.login("Vcte")
        # as duas têm o Hilay e o Vcte, então quem está na PT pode unir
        r = self.client.post(f"/api/hunt/{b['id']}/merge", json={"other_id": a["id"]}, headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["kept"], a["id"])  # a completa (1h30) vence a parcial
        self.assertEqual(r.json()["removed"], b["id"])
        self.assertIsNone(server.store.hunt(b["id"]))
        self.assertEqual(len(server.store.hunts_for_player("Hilay")), 1)

    def test_unir_leva_input_e_local_da_que_sai(self):
        a, b = self._duas()
        server.store.add_input("hunt", b["id"], "Hilay", {"total": 10, "types": [], "sources": []}, "k1")
        hilay = self.login("Hilay")
        self.client.post(f"/api/hunt/{a['id']}/merge", json={"other_id": b["id"]}, headers=hilay)
        self.assertEqual([i["name"] for i in server.store.inputs_for("hunt", [a["id"]])[a["id"]]], ["Hilay"])

    def test_quem_nao_esta_na_pt_nao_une(self):
        a, b = self._duas()
        fora = self.login("Fulano Fora")
        self.assertEqual(self.client.post(f"/api/hunt/{a['id']}/merge", json={"other_id": b["id"]}, headers=fora).status_code, 403)

    def test_nao_une_hunts_diferentes(self):
        a = server.store.add_hunt(rep(EXAMPLE), EXAMPLE, "Hilay", None)[0]
        c = server.store.add_hunt(rep(SEGUINTE), SEGUINTE, "Hilay", None)[0]
        hilay = self.login("Hilay")
        self.assertEqual(self.client.post(f"/api/hunt/{a['id']}/merge", json={"other_id": c["id"]}, headers=hilay).status_code, 422)
        self.assertEqual(self.client.post(f"/api/hunt/{a['id']}/merge", json={"other_id": a["id"]}, headers=hilay).status_code, 422)


class TelaTests(unittest.TestCase):
    def test_tela_tem_busca_e_aviso(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        tudo = js + (WEB / "index.html").read_text(encoding="utf-8")
        for peca in ("/merge", "data-merge", "huntSearch", "possível duplicata", 'id="huntList"'):
            self.assertTrue(peca in tudo, f"falta na tela: {peca}")


if __name__ == "__main__":
    unittest.main()
