"""0.17.0: CSP sem 'unsafe-inline' nos scripts — nenhum script ou evento embutido no HTML, e os .js são servidos."""
import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.server import app as server

WEB = Path(server.WEB_DIR)


class CspTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server._hits.clear()

    def csp(self, html: str) -> str:
        return re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)

    def test_no_inline_script_allowed(self):
        for page in ("index.html", "admin.html", "envio.html"):  # 0.23.0: + página do link de envio
            html = (WEB / page).read_text(encoding="utf-8")
            script_src = re.search(r"script-src ([^;]+);", self.csp(html)).group(1)
            self.assertNotIn("unsafe-inline", script_src, page)
            self.assertNotIn("unsafe-eval", script_src, page)
            # nenhum <script> com código dentro, nem atributo de evento (onclick=, onerror=...)
            self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html), [], page)
            self.assertEqual(re.findall(r"\son[a-z]+\s*=", html), [], page)

    def test_scripts_have_no_inline_handlers(self):
        for js in ("app.js", "admin.js", "envio.js"):
            self.assertEqual(re.findall(r"\son(error|load|click|mouseover)\s*=\s*[\"']", (WEB / js).read_text(encoding="utf-8")), [], js)

    def test_connect_src_is_limited(self):
        connect = re.search(r"connect-src ([^;]+);", self.csp((WEB / "index.html").read_text(encoding="utf-8"))).group(1)
        self.assertNotIn(" https: ", f" {connect} ")  # nada de "qualquer site https"
        self.assertNotIn("*.duckdns.org", connect)    # só o domínio exato, nunca qualquer subdomínio do DuckDNS

    def test_desktop_default_server_is_allowed_by_csp(self):
        from artemis.desktop.config import DEFAULT_SERVER_URL
        connect = re.search(r"connect-src ([^;]+);", self.csp((WEB / "index.html").read_text(encoding="utf-8"))).group(1)
        self.assertIn(DEFAULT_SERVER_URL, connect.split())  # senão o app desktop novo não conversa com o servidor

    def test_scripts_served(self):
        r = self.client.get("/app.js")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/javascript"))
        self.assertEqual(self.client.get("/admin.js").status_code, 200)
        # pelo túnel (cabeçalho de proxy) o script do painel não sai, como o próprio painel
        self.assertEqual(self.client.get("/admin.js", headers={"X-Forwarded-For": "1.2.3.4"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
