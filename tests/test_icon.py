"""0.17.3: ícone próprio do app de Windows (exe, janela, barra de tarefas e atalhos)."""
import struct
import unittest
from pathlib import Path

from artemis.desktop import main as desktop

ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "artemis" / "desktop" / "4rt3mi5.ico"


class IconTests(unittest.TestCase):
    def test_ico_has_small_and_large_sizes(self):
        data = ICO.read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, kind), (0, 1))
        sizes = set()
        for i in range(count):
            w, _h, _c, _r, _p, _b, size, off = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
            sizes.add(w or 256)
            self.assertEqual(data[off:off + 8], b"\x89PNG\r\n\x1a\n")
            self.assertLessEqual(off + size, len(data))
        for n in (16, 24, 32, 48, 256):  # barra de tarefas, área de trabalho e telas de alta resolução
            self.assertIn(n, sizes)

    def test_build_and_installer_use_icon(self):
        self.assertIn("--icon artemis/desktop/4rt3mi5.ico", (ROOT / "build.ps1").read_text(encoding="utf-8"))
        iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("SetupIconFile=", iss)
        self.assertEqual(iss.count(f'AppUserModelID: "{desktop.APP_ID}"'), 2)
        # 0.17.4: atalhos apontam para o .ico solto (caminho fora do cache antigo) e o Windows recarrega os ícones
        self.assertEqual(iss.count('IconFilename: "{app}\\4rt3mi5.ico"'), 2)
        self.assertIn('Source: "..\\artemis\\desktop\\4rt3mi5.ico"; DestDir: "{app}"', iss)
        self.assertIn("ChangesAssociations=yes", iss)

    def test_window_finds_icon(self):
        self.assertEqual(Path(desktop.icon_path()), ICO)


if __name__ == "__main__":
    unittest.main()
