"""0.28.0: filtro por vocação no ranking de hunts e criatura/boss do dia (boosted) no Início."""
import unittest
from unittest import mock

from artemis.core import tibiaboosted
from artemis.server import app as server
from tests import limpar_banco


def sessao(xp: int = 100000) -> dict:
    return {"started_at": "2026-11-22T10:00:00", "ended_at": "2026-11-22T11:00:00", "duration_seconds": 3600,
            "session_label": "01:00h", "raw_xp": xp, "xp": xp, "supplies": 0, "balance": 0, "damage": 0,
            "damage_h": 0, "healing": 0, "healing_h": 0, "kills": [], "loot": []}


class FiltroVocacaoTests(unittest.TestCase):
    def setUp(self):
        limpar_banco(server.store._conn)
        self.lugar = server.store.create_place("Lugar Teste Vocacao", "Cidade", "chave-teste")["id"]
        for nome, voc, fp in (("Cavaleiro Teste", "Elite Knight", "fp-k"), ("Mago Teste", "Master Sorcerer", "fp-s")):
            server.store.save_char_info(nome, voc, 300)
            server.store.add_solo(nome, fp, sessao(), place_id=self.lugar, level=300)

    def test_sem_filtro_conta_todos(self):
        linhas = server.store.place_stats()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["players"], 2)

    def test_filtra_por_vocacao(self):
        linhas = server.store.place_stats(vocation="knight")
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["players"], 1)
        self.assertEqual(server.store.place_stats(vocation="druid"), [])

    def test_rota_ignora_vocacao_invalida(self):
        r = server.places_ranking(sort="xp", min_level=None, max_level=None, mode="solo", vocation="qualquer coisa", _={})
        self.assertEqual(r["rows"][0]["players"], 2)

    def test_rota_filtra_vocacao_valida(self):
        r = server.places_ranking(sort="xp", min_level=None, max_level=None, mode="solo", vocation="Sorcerer", _={})
        self.assertEqual(r["rows"][0]["players"], 1)


class BoostedTests(unittest.TestCase):
    def setUp(self):
        server._BOOSTED_CACHE.update(at=0.0, data=None)

    def test_parse_boosted(self):
        r = tibiaboosted.parse_boosted({"creatures": {"boosted": {"name": "Hyaena"}}},
                                       {"boostable_bosses": {"boosted": {"name": "Unaz The Mean"}}})
        self.assertEqual(r, {"creature": "Hyaena", "boss": "Unaz The Mean"})

    def test_parse_rejeita_nome_estranho(self):
        r = tibiaboosted.parse_boosted({"creatures": {"boosted": {"name": "<script>alert(1)</script>"}}}, {})
        self.assertIsNone(r["creature"])
        self.assertIsNone(r["boss"])

    def test_rota_usa_cache_e_ultimo_valor(self):
        dados = {"creature": "Hyaena", "boss": "Unaz The Mean"}
        with mock.patch.object(server.tibiaboosted, "fetch_boosted", return_value=dados) as f:
            self.assertEqual(server.tibia_boosted({}), dados)
            self.assertEqual(server.tibia_boosted({}), dados)
            self.assertEqual(f.call_count, 1)  # a segunda veio do cache
        server._BOOSTED_CACHE["at"] = 0.0  # cache velho: tenta de novo, mas a fonte caiu
        with mock.patch.object(server.tibiaboosted, "fetch_boosted", side_effect=tibiaboosted.TibiaBoostedError("fora")):
            self.assertEqual(server.tibia_boosted({}), dados)  # devolve o último valor conhecido

    def test_rota_sem_dado_devolve_none(self):
        with mock.patch.object(server.tibiaboosted, "fetch_boosted", side_effect=tibiaboosted.TibiaBoostedError("fora")):
            self.assertIsNone(server.tibia_boosted({}))


if __name__ == "__main__":
    unittest.main()
