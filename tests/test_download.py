"""0.23.0: o app para Windows foi descontinuado — sem download e o app instalado não usa mais o servidor."""
import os
import tempfile
import unittest

os.environ.setdefault("ARTEMIS_DATA_DIR", tempfile.mkdtemp(prefix="artemis_test_"))

from fastapi.testclient import TestClient  # noqa: E402

from artemis.server import app as server  # noqa: E402

DESKTOP = {"Origin": "http://127.0.0.1:51234"}  # a tela do app abre num endereço local e chama o servidor


class DiscontinuedTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url="https://artemishunt.com.br")
        server._hits.clear()

    def test_no_download(self):
        d = self.client.get("/api/download").json()
        self.assertFalse(d["available"])
        self.assertTrue(d["discontinued"])
        r = self.client.get("/download", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (302, "/"))
        html = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('data-page="download"', html)

    def test_installed_app_gets_the_message(self):
        r = self.client.post("/api/account/login", json={"username": "x", "password": "y"}, headers=DESKTOP)
        self.assertEqual(r.status_code, 410)
        self.assertEqual(r.json()["detail"]["message"], server.DESKTOP_GONE)
        self.assertEqual(r.headers.get("access-control-allow-origin"), DESKTOP["Origin"])  # o app consegue ler a mensagem
        self.assertEqual(self.client.get("/api/me", headers=DESKTOP).status_code, 410)
        self.assertEqual(self.client.get("/api/health", headers=DESKTOP).status_code, 200)

    def test_site_still_works(self):
        self.assertNotEqual(self.client.post("/api/account/login", json={"username": "x", "password": "y"}).status_code, 410)
        # o site aberto no próprio PC (mesma origem) continua funcionando
        local = TestClient(server.app, base_url="http://localhost:8765")
        r = local.post("/api/account/login", json={"username": "x", "password": "y"}, headers={"Origin": "http://localhost:8765"})
        self.assertNotEqual(r.status_code, 410)


if __name__ == "__main__":
    unittest.main()
