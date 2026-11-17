"""0.22.2: tradução automática das notícias, do News Archive e do calendário (guardada no banco, uma vez por idioma)."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core import tibianews
from artemis.core import translate as tr
from tests.test_server import server  # mesmo banco temporário dos testes do servidor
from tests.test_tibiacal import SAMPLE
from tests.test_tibianews import LIST, fake_item

CALLS = []


def fake_translate(key, texts, lang, html=False, timeout=20):
    CALLS.append((lang, len(texts), html))
    # o "serviço" devolve até um script: o servidor tem que limpar de novo
    return [f"[{lang}] {t}" + ("<script>alert(1)</script>" if html else "") for t in texts]


class TranslateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        key = server.store.create_key(30, "tr")["key"]
        server.store.force_main(key, "Leitor Traducao")
        cls.h = {"X-Access-Key": key, "X-Device-Token": server.store.issue_device(key, "Leitor Traducao")}
        with mock.patch.object(tibianews, "fetch_archive", lambda days, timeout=30: LIST), \
             mock.patch.object(tibianews, "fetch_item", fake_item):
            server.sync_tibia_news()
        cls.client.post("/api/admin/calendar", json={"raw_html": SAMPLE}, headers={"X-Admin-Token": server.CONFIG["admin_token"]})

    def setUp(self):
        CALLS.clear()
        self.p1 = mock.patch.object(server, "TRANSLATE_KEY", "chave-teste:fx")
        self.p2 = mock.patch.object(tr, "translate", fake_translate)
        self.p1.start(); self.p2.start()
        self.addCleanup(self.p1.stop); self.addCleanup(self.p2.stop)

    def test_news_translated_once_and_cleaned(self):
        d = self.client.get("/api/tibia/latest?lang=pl", headers=self.h).json()
        n = d["news"][0]
        self.assertTrue(n["translated"])
        self.assertTrue(n["title"].startswith("[pl] "))
        self.assertIn("[pl]", n["content_html"])
        self.assertNotIn("script", n["content_html"])  # o que volta da tradução passa pela limpeza
        calls = len(CALLS)
        self.client.get("/api/tibia/latest?lang=pl", headers=self.h)
        self.assertEqual(len(CALLS), calls)  # segunda vez sai do banco
        en = self.client.get("/api/tibia/latest?lang=en", headers=self.h).json()["news"][0]
        self.assertFalse(en["translated"])
        self.assertFalse(en["title"].startswith("["))
        head = self.client.get("/api/tibia/headline?lang=pl", headers=self.h).json()
        self.assertTrue(head["title"].startswith("[pl] "))

    def test_archive_titles_item_and_calendar(self):
        arc = self.client.get("/api/tibia/archive?lang=fr", headers=self.h).json()
        self.assertTrue(all(r["title"].startswith("[fr] ") for r in arc["rows"]))
        self.assertTrue(all(not html for _, _, html in CALLS))  # na lista só os títulos
        item = self.client.get("/api/tibia/news/9101?lang=fr", headers=self.h).json()
        self.assertIn("[fr]", item["content_html"])
        cal = self.client.get("/api/tibia/calendar?month=2026-11&lang=de", headers=self.h).json()
        self.assertTrue(cal["translated"])
        self.assertTrue(cal["calendar"]["events"]["Lightbearer"]["description"].startswith("[de] "))
        self.assertIn("Lightbearer", cal["calendar"]["events"])  # o nome do evento fica como no jogo

    def test_without_key_or_quota_keeps_english(self):
        with mock.patch.object(server, "TRANSLATE_KEY", ""):
            n = self.client.get("/api/tibia/latest?lang=ru", headers=self.h).json()["news"][0]
        self.assertFalse(n["translated"])
        with mock.patch.object(server, "TRANSLATE_MONTHLY", 10):
            n = self.client.get("/api/tibia/latest?lang=ja", headers=self.h).json()["news"][0]
        self.assertFalse(n["translated"])
        self.assertEqual(CALLS, [])

    def test_free_key_uses_free_endpoint(self):
        self.assertIn("api-free", tr.endpoint("abc:fx"))
        self.assertNotIn("api-free", tr.endpoint("abc"))


if __name__ == "__main__":
    unittest.main()
