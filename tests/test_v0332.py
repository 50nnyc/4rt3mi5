"""0.33.2: o link público de um lootsplit de bosses mostra o de bosses, não a hunt em party de mesmo número."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.server import app as server
from artemis.server.db import Store
from tests import test_bosses as tb
from tests.test_core import EXAMPLE
from tests.test_v012 import PARTY

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"


class LinkDeBossTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _mesmo_numero(self):
        """Uma hunt em party e um lootsplit de bosses com o mesmo número, cada um na sua tabela."""
        hilay = self.login("Hilay")
        hunt = self.client.post("/api/lootsplit", json={"raw_text": PARTY, "nickname": "Hilay"}, headers=hilay).json()["hunt"]
        r = self.client.post("/api/bosses/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        boss = r.json()["hunt"]
        conn = server.store._conn  # força o mesmo número, qualquer que seja a ordem da suíte
        with server.store._lock:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("UPDATE boss_hunts SET id = ? WHERE id = ?", (hunt["id"], boss["id"]))
            conn.execute("UPDATE boss_hunt_players SET hunt_id = ? WHERE hunt_id = ?", (hunt["id"], boss["id"]))
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON")
        boss["id"] = hunt["id"]
        self.assertNotEqual(hunt["started_at"], boss["started_at"])
        return hilay, hunt, boss

    def _token(self, base, headers):
        r = self.client.post(f"{base}/link", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["path"].split("/")[-1]

    def _aberto(self, token):
        return self.client.get(f"/api/public/split/{token}")

    def test_cada_link_abre_o_seu_lootsplit(self):
        hilay, hunt, boss = self._mesmo_numero()
        t_boss = self._token(f"/api/bosses/hunt/{boss['id']}", hilay)
        t_hunt = self._token(f"/api/hunt/{hunt['id']}", hilay)
        self.assertNotEqual(t_boss, t_hunt)
        for token, kind, esperado in ((t_boss, "boss", boss), (t_hunt, "hunt", hunt)):
            body = self._aberto(token).json()
            self.assertEqual((body["kind"], body["started_at"]), (kind, esperado["started_at"]))
        self.assertIn("Lootsplit de bosses · 4rt3mi5", self.client.get(f"/l/{t_boss}").text)
        self.assertNotIn("Lootsplit de bosses · 4rt3mi5", self.client.get(f"/l/{t_hunt}").text)
        outsider = self.login("Fulano Fora")
        self.assertEqual(self.client.post(f"/api/bosses/hunt/{boss['id']}/link", headers=outsider).status_code, 403)
        # cancelar um não cancela o outro
        self.assertEqual(self.client.delete(f"/api/bosses/hunt/{boss['id']}/link", headers=hilay).status_code, 200)
        self.assertEqual(self._aberto(t_boss).status_code, 404)
        self.assertEqual(self._aberto(t_hunt).status_code, 200)

    def test_apagar_so_leva_o_link_do_proprio_tipo(self):
        hilay, hunt, boss = self._mesmo_numero()
        t_boss = self._token(f"/api/bosses/hunt/{boss['id']}", hilay)
        t_hunt = self._token(f"/api/hunt/{hunt['id']}", hilay)
        self.assertEqual(self.client.delete(f"/api/bosses/hunt/{boss['id']}", headers=hilay).status_code, 200)
        self.assertEqual(self._aberto(t_boss).status_code, 404)
        self.assertEqual(self._aberto(t_hunt).status_code, 200)

    def test_banco_antigo_ganha_o_tipo_e_o_link_continua_de_hunt(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "antigo.db"
            antigo = Store(caminho)
            antigo._conn.executescript("""
                DROP TABLE split_links;
                CREATE TABLE split_links (token TEXT PRIMARY KEY, hunt_id INTEGER NOT NULL, created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
                INSERT INTO split_links VALUES ('tokenantigo1', 7, 'k', '2026-01-01', '2999-01-01T00:00:00+00:00');""")
            antigo._conn.commit()
            antigo._conn.close()
            novo = Store(caminho)
            try:
                self.assertEqual(novo.split_link_target("tokenantigo1"), ("hunt", 7))
            finally:
                novo._conn.close()

    def test_botao_usa_o_endereco_do_tipo(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-link-create="${huntBase(h)}"', js)
        self.assertNotIn("/api/hunt/${id}/link", js)


if __name__ == "__main__":
    unittest.main()
