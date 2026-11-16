import sys
import unittest

from fastapi.testclient import TestClient

from artemis.server import app as server
from artemis.server.db import hash_token
from tools import check_secrets as cs


# exemplos montados em tempo de execução: o próprio arquivo não pode conter "segredos"
FAKE_KEY = "ART-" + "7" + "9JM-JU6X"


def hits(text: str) -> list[str]:
    return [label for label, rx in cs.PATTERNS for m in rx.finditer(text) if m.group(0) not in cs.ALLOWED_TEXT]


class SecretScannerTests(unittest.TestCase):
    def test_detecta_segredos(self):
        self.assertIn("código de acesso", hits("chave: " + FAKE_KEY))
        self.assertEqual(hits("exemplo ART-XXXX-XXXX"), [])
        self.assertIn("token do GitHub", hits("ghp_" + "a" * 36))
        self.assertIn("e-mail", hits("fulano.de.tal" + "@" + "gmail.com"))
        self.assertEqual(hits("123+50nnyc@users.noreply.github.com"), [])
        self.assertIn("senha/token no código", hits('"admin' + '_token": "' + "abcdEFGH1234ijklMNOP" + '"'))
        self.assertEqual(hits("NGROK_AUTHTOKEN: ${NGROK_AUTHTOKEN:?Preencha}"), [])
        self.assertIn("token do ngrok", hits("2abcDEF123ghiJKL456mnoPQ" + "_" + "7rstUVW890xyzABC12"))
        self.assertIn("chave privada", hits("-----BEGIN RSA " + "PRIVATE KEY-----"))

    def test_arquivos_proibidos(self):
        for p in [".env", "data/artemis.db", "data/server.json", "x/cert.pem", "artemis.db-wal"]:
            self.assertTrue(cs.forbidden(p), p)
        for p in [".env.example", "artemis/data/hunts.json", "artemis/server/db.py"]:
            self.assertFalse(cs.forbidden(p), p)


class ServerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server._fails.clear()

    def tearDown(self):
        server._fails.clear()

    def test_bloqueia_forca_bruta(self):
        h = {"X-Access-Key": "ART-" + "AAAA-AAAA", "X-Forwarded-For": "203.0.113.9"}
        for _ in range(server.FAIL_LIMIT):
            self.assertEqual(self.client.post("/api/auth", headers=h).status_code, 401)
        r = self.client.post("/api/auth", headers=h)
        self.assertEqual(r.status_code, 429)
        # até um código válido fica bloqueado para esse IP; outro IP continua normal
        key = server.store.create_key(1, "rate")["key"]
        self.assertEqual(self.client.post("/api/auth", headers={**h, "X-Access-Key": key}).status_code, 429)
        self.assertEqual(self.client.post("/api/auth", headers={"X-Access-Key": key, "X-Forwarded-For": "203.0.113.10"}).status_code, 200)

    def test_limite_de_requisicoes(self):
        server._hits.clear()
        h = {"X-Forwarded-For": "198.51.100.7"}
        limit = server.RATE_RULES["read"][0]
        codes = [self.client.get("/api/changelog", headers=h).status_code for _ in range(limit + 1)]
        self.assertEqual(codes[:limit], [200] * limit)
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.client.get("/api/changelog", headers={"X-Forwarded-For": "198.51.100.8"}).status_code, 200)
        self.assertEqual(self.client.get("/api/health", headers=h).status_code, 200)  # health nunca bloqueia
        server._hits.clear()

    def test_health_aceita_head(self):  # 0.18.1: monitor externo (UptimeRobot) testa com HEAD
        r = self.client.head("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"")
        self.assertEqual(self.client.head("/api/changelog").status_code, 405)  # só o health ganhou HEAD

    def test_cors_so_app_local(self):
        ok = self.client.get("/api/health", headers={"Origin": "http://127.0.0.1:51234"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "http://127.0.0.1:51234")
        bad = self.client.get("/api/health", headers={"Origin": "https://site-malicioso.example"})
        self.assertIsNone(bad.headers.get("access-control-allow-origin"))

    def test_novidades_da_versao_atual(self):
        d = self.client.get("/api/changelog").json()
        self.assertEqual(d["version"], server.__version__)
        self.assertEqual(d["releases"][0]["version"], server.__version__, "adicione a versão nova em artemis/data/changelog.json")
        self.assertTrue(all(r["changes"] for r in d["releases"]))

    def test_cabecalhos_e_sem_docs(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get("/docs").status_code, 404)
        self.assertEqual(self.client.get("/openapi.json").status_code, 404)

    def test_token_de_aparelho_so_como_hash(self):
        key = server.store.create_key(1, "hash")["key"]
        tok = server.store.issue_device(key, "Fulano")
        rows = [r[0] for r in server.store._conn.execute("SELECT token FROM devices WHERE key = ?", (key,))]
        self.assertEqual(rows, [hash_token(tok)])
        self.assertNotIn(tok, rows)
        self.assertTrue(server.store.device_valid(key, tok))
        self.assertFalse(server.store.device_valid(key, hash_token(tok)))  # o hash do banco não serve como token


class UpdaterTests(unittest.TestCase):
    def test_so_aceita_releases_oficiais(self):
        from artemis.desktop import updater
        self.assertTrue(updater._trusted("https://github.com/50nnyc/4rt3mi5/releases/download/v1.0.0/x.exe"))
        for bad in ["https://evil.example/4rt3mi5-Setup.exe", "http://github.com/50nnyc/4rt3mi5/releases/x.exe",
                    "https://github.com/outro/4rt3mi5/releases/x.exe",
                    "https://github.com/50nnyc/4rt3mi5/releases/../../outro/x.exe"]:
            self.assertFalse(updater._trusted(bad), bad)
        self.assertIsNone(updater.check("https://evil.example/latest.json"))


@unittest.skipUnless(sys.platform == "win32", "DPAPI só existe no Windows")
class DesktopSecretTests(unittest.TestCase):
    def test_dpapi_ida_e_volta(self):
        from artemis.desktop import secure
        enc = secure.protect(FAKE_KEY)
        self.assertTrue(enc.startswith(secure.PREFIX))
        self.assertNotIn("9JM", enc)
        self.assertEqual(secure.unprotect(enc), FAKE_KEY)
        self.assertEqual(secure.unprotect("valor-antigo"), "valor-antigo")
        self.assertIsNone(secure.unprotect(secure.PREFIX + "bGl4bw=="))


if __name__ == "__main__":
    unittest.main()
