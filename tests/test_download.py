"""Botão de download do app para Windows: /api/download e /download (instalador nas Releases do GitHub)."""
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("ARTEMIS_DATA_DIR", tempfile.mkdtemp(prefix="artemis_test_"))

from fastapi.testclient import TestClient  # noqa: E402

from artemis.server import app as server  # noqa: E402

SHA = "a" * 64
GOOD = {"version": "0.17.0", "sha256": SHA, "notes": "",
        "url": "https://github.com/50nnyc/4rt3mi5/releases/download/v0.17.0/4rt3mi5-Setup-0.17.0.exe"}


def raw(d: dict, bom: bool = True) -> bytes:
    return (b"\xef\xbb\xbf" if bom else b"") + json.dumps(d).encode()


class ManifestTests(unittest.TestCase):
    def test_aceita_manifesto_valido_com_bom(self):
        info = server._parse_manifest(raw(GOOD))
        self.assertEqual(info["version"], "0.17.0")
        self.assertEqual(info["virustotal"], f"https://www.virustotal.com/gui/file/{SHA}")

    def test_recusa_url_de_outro_lugar(self):
        for url in ("https://evil.example/4rt3mi5-Setup-0.17.0.exe",
                    "https://github.com/outro/4rt3mi5/releases/download/v0.17.0/4rt3mi5-Setup-0.17.0.exe",
                    "https://github.com/50nnyc/4rt3mi5/releases/download/v0.16.0/4rt3mi5-Setup-0.17.0.exe"):
            self.assertIsNone(server._parse_manifest(raw({**GOOD, "url": url})), url)

    def test_launcher_congelado_tem_preferencia(self):
        lsha = "b" * 64
        info = server._parse_manifest(raw({**GOOD, "launcher_sha256": lsha}))
        self.assertEqual(info["url"], "https://github.com/50nnyc/4rt3mi5/releases/download/v0.17.0/4rt3mi5-Launcher.exe")
        self.assertEqual(info["version"], "0.17.0")
        self.assertEqual(info["virustotal"], f"https://www.virustotal.com/gui/file/{lsha}")
        # SHA do launcher inválido: continua com o instalador da versão
        self.assertEqual(server._parse_manifest(raw({**GOOD, "launcher_sha256": "x"}))["url"], GOOD["url"])

    def test_launcher_do_repositorio_bate_com_o_hash_registrado(self):
        import hashlib
        from pathlib import Path
        pasta = Path(__file__).resolve().parent.parent / "launcher"
        esperado = (pasta / "SHA256.txt").read_text(encoding="utf-8").split()[0]
        self.assertEqual(hashlib.sha256((pasta / "4rt3mi5-Launcher.exe").read_bytes()).hexdigest(), esperado,
                         "o launcher congelado mudou: a reputação do SmartScreen se perde")

    def test_recusa_sha_ou_versao_invalidos(self):
        self.assertIsNone(server._parse_manifest(raw({**GOOD, "sha256": "xyz"})))
        self.assertIsNone(server._parse_manifest(raw({**GOOD, "version": "0.17"})))
        self.assertIsNone(server._parse_manifest(b"isto nao e json"))
        self.assertIsNone(server._parse_manifest(b"[]"))


class DownloadRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server._dl_cache.update(at=-1e9, ttl=0, info=None)

    def tearDown(self):
        server._dl_cache.update(at=-1e9, ttl=0, info=None)

    def test_info_e_redirecionamento(self):
        with mock.patch.object(server, "_fetch_manifest", return_value=server._parse_manifest(raw(GOOD))) as f:
            r = self.client.get("/api/download")
            self.assertEqual(r.status_code, 200)
            d = r.json()
            self.assertTrue(d["available"])
            self.assertEqual((d["version"], d["url"]), ("0.17.0", "/download"))
            r = self.client.get("/download", follow_redirects=False)
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r.headers["location"], GOOD["url"])
            self.assertEqual(f.call_count, 1)  # a segunda chamada usou o cache

    def test_github_fora_do_ar_manda_para_a_pagina(self):
        with mock.patch.object(server, "_fetch_manifest", return_value=None):
            self.assertEqual(self.client.get("/api/download").json(),
                             {"available": False, "page": server.RELEASES_PAGE})
            r = self.client.get("/download", follow_redirects=False)
            self.assertEqual((r.status_code, r.headers["location"]), (302, server.RELEASES_PAGE))


if __name__ == "__main__":
    unittest.main()
