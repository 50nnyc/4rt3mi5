"""0.22.3: Lootsplit e 2 notícias sem conta e conta de visitante (só visualização)."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core import tibianews
from tests.test_core import EXAMPLE
from tests.test_server import server  # mesmo banco temporário dos testes do servidor
from tests.test_tibianews import LIST, fake_item

GUEST_PASS = "Visita_123"  # só do teste (a senha real fica no servidor)


def count(table):
    return server.store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class PublicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def test_public_lootsplit_calculates_without_saving(self):
        before = (count("hunts"), count("hunt_players"))
        r = self.client.post("/api/public/lootsplit", json={"raw_text": EXAMPLE})
        self.assertEqual(r.status_code, 200, r.text)
        h = r.json()
        self.assertTrue(h["players"])
        self.assertIn("transfers", h)
        self.assertNotIn("id", h)  # não virou registro
        self.assertEqual((count("hunts"), count("hunt_players")), before)
        self.assertEqual(self.client.post("/api/public/lootsplit", json={"raw_text": "não é analyser"}).status_code, 422)

    def test_public_news_only_two(self):
        with mock.patch.object(tibianews, "fetch_archive", lambda days, timeout=30: LIST), \
             mock.patch.object(tibianews, "fetch_item", fake_item):
            server.sync_tibia_news()
            d = self.client.get("/api/public/news").json()
        self.assertLessEqual(len(d["news"]), server.PUBLIC_NEWS)
        self.assertEqual(server.PUBLIC_NEWS, 2)
        self.assertTrue(all(n["type"] == "news" for n in d["news"]))
        self.assertEqual(self.client.get("/api/tibia/latest").status_code, 401)  # o resto continua pedindo a conta


class GuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        server.store.setup_guest("Visitante", GUEST_PASS, "Hilay")
        r = cls.client.post("/api/account/login", json={"username": "visitante", "password": GUEST_PASS})
        assert r.status_code == 200, r.text
        d = r.json()
        cls.acct = {"X-Account-Token": d["token"]}
        cls.h = {**cls.acct, "X-Access-Key": d["key"], "X-Device-Token": d["device_token"]}

    def test_guest_sees_but_cannot_write(self):
        me = self.client.get("/api/me", headers=self.h).json()
        self.assertTrue(me["readonly"])
        self.assertEqual(me["main_char"], "Hilay")
        self.assertEqual(me["chars"], [])  # o personagem não passa a ser do visitante
        self.assertEqual(self.client.get("/api/places", headers=self.h).status_code, 200)
        before = count("hunts")
        for method, path, body in [
            ("post", "/api/lootsplit", {"raw_text": EXAMPLE, "nickname": "Hilay"}),
            ("post", "/api/stacker", {"raw_text": EXAMPLE, "nickname": "Hilay"}),
            ("post", "/api/places", {"name": "Hunt de teste"}),
            ("post", "/api/prefs/player-type", {"player_type": "novato"}),
            ("post", "/api/items/price", {"item": "gold coin", "price": 1}),
            ("post", "/api/verify/start", {"character": "Hilay"}),
            ("post", "/api/key/renew-free", None),
            ("delete", "/api/hunt/1", None),
        ]:
            with self.subTest(path=path):
                r = getattr(self.client, method)(path, headers=self.h, **({"json": body} if body else {}))
                self.assertEqual(r.status_code, 403, r.text)
                self.assertEqual(r.json()["detail"]["reason"], "readonly")
        # rotas só de conta (sem a chave) também ficam fechadas
        for path in ("/api/store/free", "/api/account/renew", "/api/account/link"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, headers=self.acct).status_code, 403)
        self.assertEqual(count("hunts"), before)
        # só calcular continua valendo (é o que o app mostra quando o envio é recusado)
        self.assertEqual(self.client.post("/api/lootsplit/preview", json={"raw_text": EXAMPLE, "nickname": "Hilay"},
                                          headers=self.h).status_code, 200)
        before = count("screen_stats")
        self.assertEqual(self.client.post("/api/track", json={"page": "home"}, headers=self.h).status_code, 200)
        self.assertEqual(count("screen_stats"), before)  # nem os contadores de uso

    def test_guest_cannot_take_a_players_account(self):
        server.store.create_account("Jogador7", "senha123")
        key = server.store.create_key(30, "jogador")["key"]
        acc = server.store.account_by_name("jogador7")
        server.store.link_account_key(acc["id"], key)
        with self.assertRaises(ValueError):
            server.store.setup_guest("Jogador7", GUEST_PASS, "Hilay")
        self.assertIsNotNone(server.store.check_password("Jogador7", "senha123"))

    def test_normal_player_is_not_blocked(self):
        key = server.store.create_key(30, "normal")["key"]
        server.store.force_main(key, "Leitor Normal")
        h = {"X-Access-Key": key, "X-Device-Token": server.store.issue_device(key, "Leitor Normal")}
        r = self.client.post("/api/prefs/player-type", json={"player_type": "novato"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["readonly"])


class StoreTests(unittest.TestCase):
    def test_store_api_has_only_the_free_key(self):
        self.assertEqual(set(TestClient(server.app).get("/api/store").json()), {"free", "free_days"})


if __name__ == "__main__":
    unittest.main()
