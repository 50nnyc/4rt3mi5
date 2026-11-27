"""0.33.4: a tela não fecha nem sobe depois de uma ação; crédito da TibiaWiki BR em todas as telas."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"


class TelaNoLugarTests(unittest.TestCase):
    def setUp(self):
        self.js = (WEB / "app.js").read_text(encoding="utf-8")

    def test_um_so_lugar_cuida_de_todas_as_telas(self):
        self.assertIn("const Keep = (() => {", self.js)
        self.assertIn("Keep.watch();", self.js)
        go = self.js[self.js.index("function go(page"):][:200]
        self.assertIn("Keep.drop();", go)  # trocar de tela começa do topo

    def test_cartoes_tem_chave_estavel(self):
        for chave in ('data-k="hunt:${h.id}"', 'data-k="solo:${s.id}"', 'data-k="bsess:${s.id}"', 'data-k="bhunt:${h.id}"',
                      'data-k="card:'):
            self.assertIn(chave, self.js, chave)

    def test_nenhum_carregando_apaga_a_tela_no_meio_de_uma_acao(self):
        """Quem troca a tela inteira pelo esqueleto precisa conferir o Keep (senão a página encolhe e sobe)."""
        for func in ("loadHome", "loadStack", "loadBoss", "loadHistory", "loadGear", "loadReportData"):
            inicio = self.js.index(f"async function {func}(")
            trecho = self.js[inicio:inicio + 900]
            for linha in re.findall(r".*innerHTML = skeleton\(.*", trecho):
                self.assertIn("Keep.active()", linha, f"{func}: {linha.strip()}")


class CreditoDaWikiTests(unittest.TestCase):
    def test_rodape_credita_a_tibiawiki_br_com_link(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        rodape = html[html.index('<footer class="sitefoot"'):html.index("</footer>", html.index('<footer class="sitefoot"'))]
        self.assertIn('href="https://www.tibiawiki.com.br/"', rodape)
        self.assertIn("TibiaWiki BR", rodape)


if __name__ == "__main__":
    unittest.main()
