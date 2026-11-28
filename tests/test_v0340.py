"""0.34.0: link principal por idioma, card de detalhes e imagens oficiais de criaturas e bosses."""
import json
import re
import unittest
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.core import tibialibrary
from artemis.server import app as server

IMG = "https://static.tibia.com/images/library/{}.gif"


def catalogo() -> dict:
    lista = [("Elves", "elf"), ("Dwarfs", "dwarf"), ("Acolytes Of The Cult", "cultacolyte"), ("Wolves", "wolf")]
    return tibialibrary.parse_catalog(
        {"creatures": {"creature_list": [{"name": n, "race": r, "image_url": IMG.format(r)} for n, r in lista]
                       + [{"name": "Ruins", "race": "../x", "image_url": IMG.format("x")},
                          {"name": "Fakes", "race": "fake", "image_url": "https://exemplo.com/a.gif"}]}},
        {"boostable_bosses": {"boostable_boss_list": [{"name": "Abyssador", "image_url": IMG.format("abyssador")}]}})


DETALHE = {"creature": {"name": "Elves", "hitpoints": 100, "experience_points": 42, "weakness": ["death"],
                        "strong": None, "loot_list": ["gold coins"], "be_paralysed": True, "description": "Pointy ears."}}


class BibliotecaTests(unittest.TestCase):
    def test_catalogo_descarta_raca_e_imagem_fora_do_padrao(self):
        self.assertEqual(sorted(catalogo()["races"]), ["cultacolyte", "dwarf", "elf", "wolf"])

    def test_nome_no_singular_acha_o_plural_do_site(self):
        c = catalogo()
        for nome, raca in (("elf", "elf"), ("Wolf", "wolf"), ("dwarf", "dwarf"), ("acolyte of the cult", "cultacolyte")):
            self.assertEqual(tibialibrary.find_race(c, nome), raca, nome)
        self.assertIsNone(tibialibrary.find_race(c, "dragon"))
        self.assertEqual(tibialibrary.find_boss(c, "The Abyssador"), IMG.format("abyssador"))

    def test_detalhe_so_tem_os_campos_do_card(self):
        d = tibialibrary.parse_creature({"creature": {**DETALHE["creature"], "extra": "x"}}, "elf")
        self.assertEqual(d["url"], "https://www.tibia.com/library/?subtopic=creatures&race=elf")
        self.assertEqual((d["hp"], d["exp"], d["strong"], d["weakness"]), (100, 42, [], ["death"]))
        self.assertNotIn("extra", d)
        with self.assertRaises(tibialibrary.TibiaLibraryError):
            tibialibrary.parse_creature({}, "elf")
        with self.assertRaises(tibialibrary.TibiaLibraryError):
            tibialibrary.fetch_creature("../news")


class CardTests(unittest.TestCase):
    def setUp(self):
        server._LIBRARY_CACHE.update(at=0.0, tried=0.0, data=None)
        server._CREATURE_CACHE.clear()
        self.patches = [mock.patch.object(server.tibialibrary, "fetch_catalog", return_value=catalogo()),
                        mock.patch.object(server.tibialibrary, "fetch_creature",
                                          return_value=tibialibrary.parse_creature(DETALHE, "elf"))]
        self.catalog, self.creature = [p.start() for p in self.patches]
        self.addCleanup(mock.patch.stopall)

    def card(self, kind, name):
        return server.detail_card(kind=kind, name=name, access={"key": "chave-teste"})

    def test_criatura_separa_os_dados_por_fonte(self):
        d = self.card("creature", "elf")
        self.assertEqual([b["source"] for b in d["blocks"]], ["tibiacom", "fandom"])
        self.assertEqual(d["image"], IMG.format("elf"))
        self.assertEqual(d["texts"]["source"], "tibiacom")
        self.card("creature", "elf")
        self.assertEqual((self.catalog.call_count, self.creature.call_count), (1, 1))  # veio do cache

    def test_boss_usa_fandom_e_a_lista_do_tibia_com(self):
        d = self.card("creature", "Abyssador")
        self.assertEqual(d["kind"], "boss")
        self.assertEqual([b["source"] for b in d["blocks"]], ["fandom"])
        self.assertTrue(d["tibiacom"]["list"])
        self.creature.assert_not_called()

    def test_tibiadata_fora_nao_derruba_o_card(self):
        self.catalog.side_effect = tibialibrary.TibiaLibraryError("fora")
        d = self.card("creature", "elf")
        self.assertEqual([b["source"] for b in d["blocks"]], ["fandom"])
        self.assertIsNone(d["tibiacom"])
        self.assertEqual(server.tibia_images({}), {"images": {}, "pages": {}})
        self.assertEqual(self.catalog.call_count, 1)  # espera antes de tentar de novo

    def test_item_npc_e_hunt_vem_da_wiki_em_portugues(self):
        server.store.load_wiki(server._wiki)  # outros testes esvaziam o banco
        server.store.load_places(server._h)
        item = self.card("item", "Magic Sword")
        self.assertEqual(item["price"]["name"], "Magic Sword")
        npc = self.card("npc", "Rashid")
        self.assertEqual(npc["blocks"][0]["source"], "wikibr")
        hunt = self.card("hunt", "Ab'Dendriel Elf Cave")
        self.assertIn(["level", 25], hunt["blocks"][0]["rows"])
        self.assertEqual(len(hunt["coords"]), 3)

    def test_nome_desconhecido_responde_404(self):
        for kind in ("item", "creature", "npc", "hunt"):
            with self.assertRaises(HTTPException) as erro:
                self.card(kind, "Nada Disso Existe")
            self.assertEqual(erro.exception.status_code, 404, kind)

    def test_imagens_so_de_nomes_conhecidos(self):
        d = server.tibia_images({})
        self.assertEqual(d["images"]["elf"], IMG.format("elf"))
        self.assertEqual(d["pages"]["elf"], "elf")
        self.assertIn("abyssador", d["images"])
        self.assertNotIn("abyssador", d["pages"])  # boss não tem página própria

    def test_rotas_pedem_sessao(self):
        client = TestClient(server.app)
        server._hits.clear()
        self.assertIn(client.get("/api/card?kind=npc&name=Rashid").status_code, (401, 403))
        self.assertIn(client.get("/api/tibia/images").status_code, (401, 403))


class LinksPorIdiomaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.app_js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")

    def test_lista_do_fandom_e_servida_antes_do_app(self):
        r = self.client.get("/fandom-pages.js")
        self.assertEqual(r.status_code, 200)
        titulos = json.loads("[" + re.search(r"const FANDOM_TITLES = \[(.*?)\n\];", r.text, re.S).group(1) + "]")
        self.assertEqual(len({t.lower() for t in titulos}), len(titulos))
        for nome in ("Eyeless Devourer", "Gnomevil", "Magic Sword", "Rashid"):
            self.assertIn(nome, titulos)
        html = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('<script src="fandom-pages.js">'), html.index('<script src="app.js">'))
        self.assertIn("/fandom-pages.js", (server.WEB_DIR / "sw.js").read_text(encoding="utf-8"))

    def test_ordem_dos_sites_por_idioma(self):
        self.assertIn('I18N.lang === "pt-BR" ? ["wikibr", "fandom", "tibiacom"]', self.app_js)
        self.assertIn('I18N.lang === "en" ? ["fandom", "tibiacom", "wikibr"] : ["tibiacom", "fandom", "wikibr"]', self.app_js)

    def test_resultado_do_lootsplit_de_boss_e_redesenhado_depois_de_marcar(self):
        # o card recém-enviado fica em #bossAsk, fora da lista que o loadBoss redesenha: o botão parecia não funcionar
        self.assertIn('if (S.page === "boss") { paintBossSplit(h); return loadBoss({ quiet: true }); }', self.app_js)
        self.assertIn('box.querySelector(`[data-k="card:boss:${h.id}"]`)', self.app_js)

    def test_textos_do_card_estao_traduzidos(self):
        d = json.loads((server.WEB_DIR / "i18n-en.json").read_text(encoding="utf-8"))
        for bloco in ("CARD_ROWS", "CARD_LISTS", "CARD_SOURCES"):
            corpo = re.search(rf"const {bloco} = \{{(.*?)\}};", self.app_js, re.S).group(1)
            for texto in re.findall(r':\s*"([^"]+)"', corpo):
                self.assertIn(texto, d, texto)


if __name__ == "__main__":
    unittest.main()
