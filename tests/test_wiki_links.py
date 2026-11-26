"""0.33.1: o site só cria link para a TibiaWiki BR quando o nome está na lista de páginas conferidas."""
import json
import re
import unittest

from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.server import app as server


def _objeto(texto: str, regra: str, abre: str, fecha: str):
    return json.loads(abre + re.search(regra, texto, re.S).group(1) + fecha)


class WikiLinksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.app_js = (server.WEB_DIR / "app.js").read_text(encoding="utf-8")
        cls.lista_js = cls.client.get("/wiki-pages.js")

    def titulos(self):
        return _objeto(self.lista_js.text, r"const WIKI_TITLES = \[(.*?)\n\];", "[", "]")

    def test_lista_e_servida_e_carrega_antes_do_app(self):
        self.assertEqual(self.lista_js.status_code, 200)
        self.assertIn("javascript", self.lista_js.headers["content-type"])
        html = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('<script src="wiki-pages.js">'), html.index('<script src="app.js">'))
        self.assertIn("/wiki-pages.js", (server.WEB_DIR / "sw.js").read_text(encoding="utf-8"))

    def test_toda_grafia_alternativa_aponta_para_titulo_conferido(self):
        alias = _objeto(self.app_js, r"const WIKI_ALIAS = \{(.*?)\n\};", "{", "}")
        self.assertEqual(set(alias.values()) - set(self.titulos()), set())

    def test_titulos_nao_se_repetem_mudando_so_maiusculas(self):
        titulos = self.titulos()
        self.assertEqual(len({t.lower() for t in titulos}), len(titulos))

    def test_nomes_que_so_redirecionavam_ou_nao_tinham_pagina_ficam_sem_link(self):
        titulos = {t.lower() for t in self.titulos()}
        for nome in ("human", "dragon hoard", "asura", "time guardian", "timedisplaced anomaly"):
            self.assertNotIn(nome, titulos)


if __name__ == "__main__":
    unittest.main()
