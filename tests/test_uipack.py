"""0.18.0: a tela nova entra sem fechar o app; o instalador roda quando a pessoa fecha."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from artemis import __version__
from artemis.desktop import main as desktop
from artemis.desktop import uipack, updater

ROOT = Path(__file__).resolve().parent.parent
SHA = "a" * 64
REL = "https://github.com/50nnyc/4rt3mi5/releases/download/v9.0.0/"


def _zip(path: Path, files: dict) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_build_and_extract_roundtrip(self):
        z = self.tmp / "web.zip"
        sha = uipack.build(ROOT / "artemis" / "web", z)
        self.assertRegex(sha, r"^[0-9a-f]{64}$")
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
        self.assertIn("index.html", names)
        self.assertIn("app.js", names)
        self.assertFalse(any("\\" in n for n in names))
        pack = self.tmp / "pack"
        uipack.extract(z, pack, "9.0.0", 1, sha)
        self.assertEqual(uipack.read_meta(pack)["version"], "9.0.0")
        self.assertTrue((pack / "app.js").is_file())

    def test_rejects_dangerous_packs(self):
        bad = [
            {"index.html": "x", "../fora.js": "x"},
            {"index.html": "x", "/abs.js": "x"},
            {"index.html": "x", "C:/win.js": "x"},
            {"index.html": "x", "virus.exe": "x"},
            {"index.html": "x", "pack.json": "{}"},
            {"app.js": "x"},  # sem index.html
        ]
        for i, files in enumerate(bad):
            z = _zip(self.tmp / f"bad{i}.zip", files)
            target = self.tmp / f"t{i}"
            with self.assertRaises(uipack.BadPack, msg=str(files)):
                uipack.extract(z, target, "9.0.0", 1, SHA)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".novo").exists())
        self.assertFalse((self.tmp / "fora.js").exists())

    def test_usable_only_when_newer_and_compatible(self):
        z = _zip(self.tmp / "ok.zip", {"index.html": "novo"})
        pack = self.tmp / "pack"
        uipack.extract(z, pack, "9.0.0", uipack.BRIDGE, SHA)
        self.assertIsNotNone(uipack.usable(pack, "8.9.9"))
        self.assertIsNone(uipack.usable(pack, "9.0.0"))  # o instalador já trouxe essa
        uipack.extract(z, pack, "9.0.0", uipack.BRIDGE + 1, SHA)
        self.assertIsNone(uipack.usable(pack, "8.9.9"))  # exige app mais novo

    def test_prepare_live_picks_pack_or_bundled(self):
        bundled = self.tmp / "bundled"
        bundled.mkdir()
        (bundled / "index.html").write_text("velho", encoding="utf-8")
        pack, live = self.tmp / "pack", self.tmp / "live"
        uipack.extract(_zip(self.tmp / "p.zip", {"index.html": "novo", "img/a.png": "x"}), pack, "9.0.0", 1, SHA)
        self.assertEqual(uipack.prepare_live(bundled, pack, live, "8.0.0"), "9.0.0")
        self.assertEqual((live / "index.html").read_text(encoding="utf-8"), "novo")
        self.assertFalse((live / "pack.json").exists())
        # depois que o instalador da 9.0.0 entrou: volta para a interface do instalador e apaga o pacote
        self.assertEqual(uipack.prepare_live(bundled, pack, live, "9.0.0"), "9.0.0")
        self.assertEqual((live / "index.html").read_text(encoding="utf-8"), "velho")
        self.assertFalse((live / "img").exists())
        self.assertFalse(pack.exists())


class ManifestTests(unittest.TestCase):
    def _check(self, data, current="0.1.0"):
        resp = mock.MagicMock()
        resp.__enter__.return_value = io.BytesIO(json.dumps(data).encode())
        with mock.patch.object(updater._opener, "open", return_value=resp):
            return updater.check(REL + "latest.json", current=current)

    def test_reads_web_pack(self):
        info = self._check({"version": "9.0.0", "url": REL + "s.exe", "sha256": SHA,
                            "web": {"url": REL + "w.zip", "sha256": "B" * 64, "bridge": 1}})
        self.assertEqual(info.web, updater.WebPack(REL + "w.zip", "b" * 64, 1))

    def test_ignores_untrusted_or_broken_web(self):
        for web in ({"url": "https://evil.example/w.zip", "sha256": SHA, "bridge": 1},
                    {"url": REL + "w.zip", "sha256": "xyz", "bridge": 1},
                    {"url": REL + "w.zip", "sha256": SHA, "bridge": "1"},
                    {"url": REL + "w.zip", "sha256": SHA, "bridge": True},
                    "lixo"):
            info = self._check({"version": "9.0.0", "url": REL + "s.exe", "sha256": SHA, "web": web})
            self.assertIsNotNone(info)  # o instalador continua valendo
            self.assertIsNone(info.web, web)

    def test_old_manifest_without_web(self):
        self.assertIsNone(self._check({"version": "9.0.0", "url": REL + "s.exe", "sha256": SHA}).web)

    def test_download_refuses_untrusted_and_wrong_hash(self):
        tmp = Path(tempfile.mkdtemp()) / "x.zip"
        with self.assertRaises(updater.UntrustedUpdate):
            updater.download("https://evil.example/x.zip", SHA, tmp)
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {}
        resp.read.side_effect = [b"conteudo", b""]
        with mock.patch.object(updater._opener, "open", return_value=resp), self.assertRaises(RuntimeError):
            updater.download(REL + "x.zip", SHA, tmp)
        self.assertFalse(tmp.exists())

    def test_installer_on_close_is_quiet_and_does_not_reopen(self):
        with mock.patch.object(updater.subprocess, "Popen") as popen:
            updater.run_installer(Path("s.exe"), reopen=False)
            args = popen.call_args[0][0]
        self.assertIn("/VERYSILENT", args)
        self.assertIn("/reabrir=nao", args)
        with mock.patch.object(updater.subprocess, "Popen") as popen:
            updater.run_installer(Path("s.exe"), reopen=True)
            args = popen.call_args[0][0]
        self.assertIn("/SILENT", args)
        self.assertNotIn("/reabrir=nao", args)

    def test_installer_honors_reabrir(self):
        iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("Check: ReabrirDepois", iss)
        self.assertIn("{param:reabrir|sim}", iss)
        build = (ROOT / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("artemis.desktop.uipack", build)
        # o launcher congelado lê o primeiro "url"/"sha256" do latest.json: os do instalador vêm antes do "web"
        self.assertLess(build.index("    sha256          = $sha"), build.index("    web             ="))
        self.assertIn("4rt3mi5-web-*.zip", (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))


class BridgeFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patches = [
            mock.patch.object(desktop, "PACK_DIR", self.tmp / "pack"),
            mock.patch.object(desktop, "UI_DIR", self.tmp / "ui"),
            mock.patch.object(desktop.Config, "load", return_value=desktop.Config()),
            mock.patch.object(updater, "is_frozen", return_value=True),
            mock.patch.object(desktop.Bridge, "_fetch_installer"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.bridge = desktop.Bridge()
        self.zip = _zip(self.tmp / "w.zip", {"index.html": "nova"})

    def _info(self, bridge=uipack.BRIDGE, web=True):
        return updater.UpdateInfo("99.0.0", REL + "s.exe", SHA, "", updater.WebPack(REL + "w.zip", SHA, bridge) if web else None)

    def test_new_screen_without_closing(self):
        with mock.patch.object(updater, "check", return_value=self._info()), \
             mock.patch.object(updater, "download", side_effect=lambda u, s, t, timeout=60: t.write_bytes(self.zip.read_bytes()) and t):
            r = self.bridge.check_update()
        self.assertEqual(r["ui"], "ready")
        self.bridge._fetch_installer.assert_called_once()
        self.assertIsNone(self.bridge.reload_ui())
        self.assertEqual((self.tmp / "ui" / "index.html").read_text(encoding="utf-8"), "nova")
        self.assertEqual(self.bridge.get_config()["version"], "99.0.0")
        self.assertEqual(self.bridge.get_config()["app_version"], __version__)
        with mock.patch.object(updater, "check", return_value=self._info()):
            self.assertEqual(self.bridge.check_update()["ui"], "current")

    def test_incompatible_screen_waits_for_installer(self):
        with mock.patch.object(updater, "check", return_value=self._info(bridge=uipack.BRIDGE + 1)), \
             mock.patch.object(updater, "download") as dl:
            self.assertEqual(self.bridge.check_update()["ui"], "none")
        dl.assert_not_called()
        self.assertIsNotNone(self.bridge.reload_ui())  # nada para trocar

    def test_install_on_close_runs_once(self):
        self.bridge._installer = ("99.0.0", Path("s.exe"))
        with mock.patch.object(updater, "run_installer") as run:
            self.assertTrue(self.bridge._install_on_close())
            self.assertFalse(self.bridge._install_on_close())
        run.assert_called_once_with(Path("s.exe"), reopen=False)


if __name__ == "__main__":
    unittest.main()
