"""0.22.0: notícias do Tibia (Latest News / News Archive) guardadas no banco, filtro e leitura offline."""
import unittest
from datetime import date, timedelta
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core import tibianews
from tests import limpar_banco
from tests.test_server import server  # mesmo banco temporário dos testes do servidor

TODAY = date.today()
D = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
LIST = [
    {"id": 9101, "date": D(1), "title": "Double XP Event", "category": "community", "type": "news"},
    {"id": 9102, "date": D(2), "title": "Server save will take longer...", "category": "technical", "type": "ticker"},
    {"id": 9103, "date": D(3), "title": "The Challenger", "category": "development", "type": "article"},
    {"id": 9104, "date": D(20), "title": "Old Fixes", "category": "support", "type": "news"},
]
BODY = {9101: '<p>Between <b>November 20</b> and 23 <img src="https://static.tibia.com/images/news/x_small.png" '
              "onclick=\"ImageInNewWindow('https://static.tibia.com/images/news/x_big.png', 'x');\"/>"
              '<script>alert(1)</script><a href="javascript:alert(1)" onclick="x()">mau</a>'
              '<a href="/news/?subtopic=latestnews">bom</a></p>'}


def fake_item(nid, timeout=15):
    raw = BODY.get(nid, f"<p>Texto completo {nid} com dragon lord</p>")
    return {"id": nid, "title": "", "content_html": tibianews.sanitize(raw), "content_text": f"texto {nid} dragon lord"}


class SanitizeTests(unittest.TestCase):
    def test_removes_scripts_events_and_external_images(self):
        out = tibianews.sanitize(BODY[9101])
        self.assertNotIn("script", out)
        self.assertNotIn("onclick", out)
        self.assertNotIn("javascript:", out)
        self.assertNotIn("<img", out)
        self.assertIn('href="https://static.tibia.com/images/news/x_big.png"', out)  # imagem vira link (a grande)
        self.assertIn('href="https://www.tibia.com/news/?subtopic=latestnews"', out)  # link relativo vira absoluto
        self.assertIn("<b>November 20</b>", out)

    def test_closes_open_tags(self):
        self.assertEqual(tibianews.sanitize("<p><b>oi"), "<p><b>oi</b></p>")


class TibiaNewsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        limpar_banco(server.store._conn)
        cls.client = TestClient(server.app)
        key = server.store.create_key(30, "news")["key"]
        server.store.force_main(key, "Leitor Noticias")
        cls.h = {"X-Access-Key": key, "X-Device-Token": server.store.issue_device(key, "Leitor Noticias")}

    def test_sync_latest_archive_and_offline(self):
        with mock.patch.object(tibianews, "fetch_archive", lambda days, timeout=30: LIST), \
             mock.patch.object(tibianews, "fetch_item", fake_item):
            r = server.sync_tibia_news()
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(r["fetched"], 4)
        # fonte fora do ar: tudo continua saindo do banco
        def down(*a, **k):
            raise tibianews.TibiaNewsError("fora")
        with mock.patch.object(tibianews, "fetch_archive", down), mock.patch.object(tibianews, "fetch_item", down):
            self.assertFalse(server.sync_tibia_news()["ok"])
            latest = self.client.get("/api/tibia/latest", headers=self.h).json()
            self.assertTrue(latest["offline"])
            self.assertEqual(latest["news"][0]["title"], "Double XP Event")
            self.assertIn("Ver imagem", latest["news"][0]["content_html"])
            self.assertEqual(latest["tickers"][0]["id"], 9102)
            self.assertEqual(latest["featured"]["id"], 9103)
            # padrão do filtro: última semana, tudo marcado
            arc = self.client.get("/api/tibia/archive", headers=self.h).json()
            self.assertEqual({x["id"] for x in arc["rows"]} & {9101, 9102, 9103, 9104}, {9101, 9102, 9103})
            self.assertEqual((arc["from"], arc["to"]), (D(7), D(0)))
            only = self.client.get("/api/tibia/archive?types=ticker&categories=technical", headers=self.h).json()
            self.assertEqual([x["id"] for x in only["rows"]], [9102])
            none = self.client.get("/api/tibia/archive?types=", headers=self.h).json()
            self.assertEqual(none["rows"], [])
            old = self.client.get(f"/api/tibia/archive?from={D(30)}&q=fixes", headers=self.h).json()
            self.assertEqual([x["id"] for x in old["rows"]], [9104])
            words = self.client.get(f"/api/tibia/archive?from={D(30)}&q=dragon%20lord", headers=self.h).json()
            self.assertGreaterEqual(words["count"], 4)  # pesquisa também no texto guardado
            item = self.client.get("/api/tibia/news/9101", headers=self.h).json()
            self.assertIn("<b>November 20</b>", item["content_html"])
        self.assertEqual(self.client.get("/api/tibia/news/1", headers=self.h).status_code, 404)
        self.assertEqual(self.client.get("/api/tibia/archive?from=ontem", headers=self.h).status_code, 422)
        self.assertEqual(self.client.get("/api/tibia/latest").status_code, 401)


if __name__ == "__main__":
    unittest.main()
