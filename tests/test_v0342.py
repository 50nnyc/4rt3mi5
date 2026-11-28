"""0.34.2: o resumo do lootsplit e o convite por WhatsApp saem no idioma escolhido."""
import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"


class TextosCopiadosTests(unittest.TestCase):
    def test_toda_frase_do_resumo_e_do_convite_tem_traducao(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        ingles = json.loads((WEB / "i18n-en.json").read_text(encoding="utf-8"))
        for funcao, quantas in (("splitSummary", 5), ("inviteMessage", 1)):
            corpo = re.search(rf"function {funcao}\(.*?\n}}", js, re.S).group(0)
            frases = re.findall(r'\b(?:T|tf)\("([^"]+)"', corpo)
            self.assertEqual(len(frases), quantas, funcao)
            for frase in frases:
                self.assertIn(frase, ingles)
                self.assertNotEqual(ingles[frase], frase)


if __name__ == "__main__":
    unittest.main()
