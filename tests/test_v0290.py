"""0.29.0: link público do lootsplit, líder marca pagamento por outro, login direto no Início."""
import unittest
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from artemis.server import app as server
from tests import test_bosses as tb
from tests.test_v012 import PARTY

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"


class LinkPublicoTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _hunt(self):
        hilay = self.login("Hilay")
        r = self.client.post("/api/lootsplit", json={"raw_text": PARTY, "nickname": "Hilay"}, headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        return hilay, r.json()["hunt"]

    def test_criar_ler_e_cancelar(self):
        hilay, hunt = self._hunt()
        outsider = self.login("Fulano Fora")
        self.assertEqual(self.client.post(f"/api/hunt/{hunt['id']}/link", headers=outsider).status_code, 403)
        r = self.client.post(f"/api/hunt/{hunt['id']}/link", headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        path = r.json()["path"]
        self.assertTrue(path.startswith("/l/"))
        again = self.client.post(f"/api/hunt/{hunt['id']}/link", headers=hilay).json()["path"]
        self.assertEqual(path, again)  # um link por lootsplit
        token = path.split("/")[-1]
        pub = self.client.get(f"/api/public/split/{token}")  # sem login
        self.assertEqual(pub.status_code, 200)
        body = pub.json()
        self.assertEqual(body["profit_each"], hunt["profit_each"])
        self.assertEqual(len(body["transfers"]), len(hunt["transfers"]))
        flat = str(body)
        for secret in ("uploader", "fingerprint", "submitted_by", "content_hash", "name_key"):
            self.assertNotIn(secret, flat)
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertIn("og:description", page.text)
        self.assertIn("noindex", page.text)
        self.assertEqual(self.client.delete(f"/api/hunt/{hunt['id']}/link", headers=hilay).status_code, 200)
        self.assertEqual(self.client.get(f"/api/public/split/{token}").status_code, 404)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_token_invalido_e_vencido(self):
        self.assertEqual(self.client.get("/api/public/split/abc").status_code, 404)
        self.assertEqual(self.client.get("/api/public/split/..%2F..%2Fetc").status_code, 404)
        self.assertEqual(self.client.get("/l/nao-existe-123").status_code, 404)
        hilay, hunt = self._hunt()
        token = self.client.post(f"/api/hunt/{hunt['id']}/link", headers=hilay).json()["path"].split("/")[-1]
        with server.store._lock:
            server.store._conn.execute("UPDATE split_links SET expires_at = '2000-01-01T00:00:00+00:00' WHERE token = ?", (token,))
            server.store._conn.commit()
        self.assertEqual(self.client.get(f"/api/public/split/{token}").status_code, 404)

    def test_apagar_hunt_apaga_o_link(self):
        hilay, hunt = self._hunt()
        token = self.client.post(f"/api/hunt/{hunt['id']}/link", headers=hilay).json()["path"].split("/")[-1]
        self.assertEqual(self.client.delete(f"/api/hunt/{hunt['id']}", headers=hilay).status_code, 200)
        self.assertEqual(self.client.get(f"/api/public/split/{token}").status_code, 404)

    def test_lider_marca_pagamento_de_outros(self):
        hilay, hunt = self._hunt()
        others = [t for t in hunt["transfers"] if "Hilay" not in (t["payer"], t["receiver"])]
        self.assertTrue(others, "o exemplo precisa ter uma transferência entre outras pessoas")
        t = others[0]
        body = {"payer": t["payer"], "receiver": t["receiver"], "paid": True}
        r = self.client.post(f"/api/hunt/{hunt['id']}/paid", json=body, headers=hilay)  # Hilay enviou: é a líder
        self.assertEqual(r.status_code, 200, r.text)
        marked = next(x for x in r.json()["hunt"]["transfers"] if (x["payer"], x["receiver"]) == (t["payer"], t["receiver"]))
        self.assertIsNotNone(marked["paid_at"])
        outsider = self.login("Fulano Fora")
        self.assertEqual(self.client.post(f"/api/hunt/{hunt['id']}/paid", json=body, headers=outsider).status_code, 403)


class TelasTests(unittest.TestCase):
    def test_login_nao_pergunta_solo_ou_party(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("data-mode-pick", html)
        self.assertNotIn("Hoje você vai caçar", html)
        self.assertIn('openApp("home")', js)

    def test_pagina_publica_nao_embute_script(self):
        html = (WEB / "split.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/split.js">', html)
        self.assertNotIn("innerHTML", (WEB / "split.js").read_text(encoding="utf-8"))
        self.assertEqual(TestClient(server.app).get("/split.js").status_code, 200)

    def test_nome_do_boss_com_the_minusculo(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("small.has(w.toLowerCase())", js)  # "Unaz The Mean" -> Unaz_the_Mean.gif


if __name__ == "__main__":
    unittest.main()
