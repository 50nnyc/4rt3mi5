"""0.30.0: filtro por mundo no ranking Geral e sessão ao vivo (leitura do analyzer sem salvar)."""
import unittest
from pathlib import Path
from unittest import mock

from artemis.core import rankscan
from artemis.server import app as server
from artemis.server.db import name_key
from tests import test_bosses as tb
from tests.test_v012 import SOLO
from tests.test_v026_1 import RankingTests

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"


def fetch_page(w, c, p, **_k):
    """Dois mundos; Antica tem 3 jogadores na 1ª página, Bona 2. Só 'experience' (vira level)."""
    if p != 1 or c != "experience":
        return []
    if w == "Antica":
        return [{"name": "A Um", "level": 900, "vocation": "Knight", "value": 1},
                {"name": "A Dois", "level": 800, "vocation": "Druid", "value": 1},
                {"name": "A Tres", "level": 700, "vocation": "Paladin", "value": 1}]
    return [{"name": "B Um", "level": 850, "vocation": "Sorcerer", "value": 1},
            {"name": "B Dois", "level": 600, "vocation": "Monk", "value": 1}]


class MundoTests(RankingTests):
    def _scan(self, per_world=200):
        with mock.patch.object(rankscan, "PER_WORLD", per_world):
            rankscan.run_scan(server.store, day="2026-11-21", tracked={}, fetch_page=fetch_page,
                              fetch_worlds=lambda: ["Antica", "Bona"], key_fn=name_key,
                              categories=("experience",), workers=2, pages=2)

    def _get(self, qs):
        token = self.login("Fora Mundo")
        hdr = {"X-Access-Key": self.key, "X-Device-Token": token}
        r = self.client.get("/api/rank/geral?" + qs, headers=hdr)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_filtra_pelo_top_guardado_do_mundo(self):
        self._scan()
        d = self._get("metric=level&world=bona")  # sem diferenciar maiúsculas
        self.assertEqual(d["world"], "Bona")
        self.assertEqual(d["source"], "mundo")
        self.assertEqual([r["name"] for r in d["rows"]], ["B Um", "B Dois"])
        self.assertEqual([r["pos"] for r in d["rows"]], [1, 2])  # posição dentro do mundo
        self.assertEqual(d["worlds"], ["Antica", "Bona"])

    def test_sem_filtro_continua_o_top_geral(self):
        self._scan()
        d = self._get("metric=level")
        self.assertEqual([r["name"] for r in d["rows"]], ["A Um", "B Um", "A Dois", "A Tres", "B Dois"])
        self.assertEqual(d["world"], "")

    def test_mundo_inexistente_vira_geral(self):
        self._scan()
        d = self._get("metric=level&world=Nunca")
        self.assertEqual(d["world"], "")
        self.assertEqual(len(d["rows"]), 5)

    def test_limite_por_mundo(self):
        self._scan(per_world=2)
        d = self._get("metric=level&world=Antica")
        self.assertEqual([r["name"] for r in d["rows"]], ["A Um", "A Dois"])

    def test_reserva_quando_ainda_nao_ha_top_por_mundo(self):
        self._scan()
        with server.store._lock:  # simula o banco de antes da 0.30.0: só o top 1000 geral
            server.store._conn.execute("DELETE FROM rank_world_top")
            server.store._conn.commit()
        d = self._get("metric=level&world=Antica")
        self.assertEqual(d["source"], "geral")
        self.assertEqual([r["name"] for r in d["rows"]], ["A Um", "A Dois", "A Tres"])
        self.assertEqual([r["pos"] for r in d["rows"]], [1, 2, 3])


class FiltroMundoOutrasAbasTests(RankingTests):
    """O filtro de mundo também vale em Usuários do 4rt3mi5 e Amigos; o padrão é todos os mundos."""

    def test_filtro_generico(self):
        rows = [{"name": "A", "world": "Antica"}, {"name": "B", "world": "Bona"}, {"name": "C", "world": None}]
        r, worlds, w = server._filter_world(rows, "")
        self.assertEqual((len(r), worlds, w), (3, ["Antica", "Bona"], ""))
        r, _, w = server._filter_world(rows, "bona")
        self.assertEqual(([x["name"] for x in r], w), (["B"], "Bona"))
        r, _, w = server._filter_world(rows, "Nunca")  # mundo que não está na lista: ignora e mostra todos
        self.assertEqual((len(r), w), (3, ""))

    def test_rotas_aceitam_mundo(self):
        rankscan.run_scan(server.store, day="2026-11-21", tracked={name_key("A Um"): "A Um", name_key("B Um"): "B Um"},
                          fetch_page=fetch_page, fetch_worlds=lambda: ["Antica", "Bona"], key_fn=name_key,
                          categories=("experience",), workers=2, pages=2)
        for n in ("A Um", "B Um"):
            server.store.xp_save(n, "2026-11-21", 1000)
        token = self.login("Fora Mundo")
        hdr = {"X-Access-Key": self.key, "X-Device-Token": token}
        d = self.client.get("/api/xp-ranking?days=30&scope=mine&world=", headers=hdr).json()
        self.assertEqual(d["world"], "")
        server.store.custom_add(self.key, "A Um"); server.store.custom_add(self.key, "B Um")
        todos = self.client.get("/api/xp-ranking?days=30&scope=mine", headers=hdr).json()
        so_bona = self.client.get("/api/xp-ranking?days=30&scope=mine&world=Bona", headers=hdr).json()
        self.assertEqual(sorted(todos["worlds"]), ["Antica", "Bona"])
        self.assertEqual([r["name"] for r in so_bona["rows"]], ["B Um"])
        amigos = self.client.get("/api/rank/amigos?world=Antica", headers=hdr).json()
        self.assertIn("worlds", amigos)
        self.assertTrue(all(r["world"] in (None, "Antica") for r in amigos["rows"]))


class SessaoAoVivoTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def test_preview_le_sem_salvar(self):
        hdr = self.login("Hilay")
        r = self.client.post("/api/stacker/preview", json={"raw_text": SOLO.format(d=1, xp=900_000, bal=400_000)}, headers=hdr)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual((d["duration_seconds"], d["xp"], d["balance"]), (3600, 900_000, 400_000))
        self.assertEqual(server.store.solo_for_player("Hilay"), [])  # nada foi salvo

    def test_preview_recusa_texto_invalido(self):
        hdr = self.login("Hilay")
        self.assertEqual(self.client.post("/api/stacker/preview", json={"raw_text": "qualquer coisa"}, headers=hdr).status_code, 422)

    def test_tela_tem_a_sessao_ao_vivo(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/stacker/preview", js)
        self.assertIn('id="liveBox"', (WEB / "index.html").read_text(encoding="utf-8"))
        self.assertIn('id="geralWorld"', (WEB / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
