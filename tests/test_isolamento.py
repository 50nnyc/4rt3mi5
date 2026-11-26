"""Garante que a suíte nunca usa o banco do projeto, com ou sem `-t .` no comando."""
import re
import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.server import app as server


class IsolamentoTests(unittest.TestCase):
    def test_banco_fica_na_pasta_temporaria(self):
        self.assertIn(Path(tempfile.gettempdir()).resolve(), Path(server.DATA_DIR).resolve().parents)

    def test_todo_modulo_isola_o_banco_antes_de_importar_o_servidor(self):
        """Sem `-t .`, o primeiro módulo que importar o servidor decide qual banco a suíte inteira usa."""
        for arquivo in sorted(Path(__file__).parent.glob("test_*.py")):
            linhas = arquivo.read_text(encoding="utf-8").splitlines()

            def primeira(regra):
                return next((i for i, linha in enumerate(linhas) if re.search(regra, linha)), None)

            servidor = primeira(r"^(from|import) artemis.*\bserver\b")
            if servidor is None:
                continue
            isola = primeira(r"^(import tests\b|from tests\b|os\.environ.*ARTEMIS_DATA_DIR)")
            with self.subTest(arquivo=arquivo.name):
                self.assertTrue(isola is not None and isola < servidor,
                                "coloque `import tests` antes de importar o servidor")


if __name__ == "__main__":
    unittest.main()
