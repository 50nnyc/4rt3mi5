"""0.21.0: rodapé CipSoft/Hilay, contato com o administrador (CAPTCHA próprio + campo ":boom:"),
download só pelo menu com o aviso da CipSoft, créditos e contagem de visitas para o relatório mensal."""
import hashlib
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.core import captcha
from artemis.server import app as server
from artemis.server import mailer

WEB = Path(server.WEB_DIR)
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}


def solve(ch: dict) -> dict:
    for n in range(ch["maxnumber"] + 1):
        if hashlib.sha256((ch["salt"] + str(n)).encode()).hexdigest() == ch["challenge"]:
            return {"salt": ch["salt"], "number": n, "challenge": ch["challenge"], "signature": ch["signature"]}
    raise AssertionError("sem solução")


class CaptchaTests(unittest.TestCase):
    SECRET = b"segredo-de-teste"

    def test_solved_challenge_passes_once(self):
        ch = captcha.issue(self.SECRET, now=1000.0, max_number=500)
        ans, used = solve(ch), {}
        captcha.verify(self.SECRET, ans, used, now=1005.0)
        with self.assertRaises(captcha.CaptchaError):  # o mesmo desafio não vale duas vezes
            captcha.verify(self.SECRET, ans, used, now=1006.0)

    def test_rejects_wrong_forged_fast_and_old(self):
        ch = captcha.issue(self.SECRET, now=1000.0, max_number=500)
        ans = solve(ch)
        with self.assertRaises(captcha.CaptchaError):
            captcha.verify(self.SECRET, {**ans, "number": ans["number"] + 1}, {}, now=1005.0)
        with self.assertRaises(captcha.CaptchaError):  # assinado com outro segredo
            captcha.verify(b"outro", ans, {}, now=1005.0)
        with self.assertRaises(captcha.CaptchaError):  # rápido demais para um navegador
            captcha.verify(self.SECRET, ans, {}, now=1000.2)
        with self.assertRaises(captcha.CaptchaError):  # vencido
            captcha.verify(self.SECRET, ans, {}, now=1000.0 + captcha.TTL + 1)
        with self.assertRaises(captcha.CaptchaError):
            captcha.verify(self.SECRET, {"salt": "x"}, {}, now=1005.0)


class ContactTests(unittest.TestCase):
    admin = property(lambda self: {"X-Admin-Token": server.CONFIG["admin_token"]})

    def setUp(self):
        self.client = TestClient(server.app)
        server._hits.clear(); server._contact_hits.clear(); server._captcha_used.clear()
        self.sent = mock.patch.object(mailer, "send", return_value=True)
        self.send = self.sent.start()
        self.clock = mock.patch.object(captcha.time, "time", side_effect=self._now)
        self.t = 2_000_000.0
        self.clock.start()

    def tearDown(self):
        self.sent.stop(); self.clock.stop()

    def _now(self):
        return self.t

    def answer(self):
        ch = self.client.get("/api/contact/challenge").json()
        self.t += 3  # a pessoa leva alguns segundos
        return solve(ch)

    def body(self, **kw):
        return {"email": "fan@exemplo.com", "subject": "Parceria", "message": "Olá! Gostaria de falar sobre o 4rt3mi5.",
                "lang": "en", "captcha": self.answer(), ":boom:": "", **kw}

    def test_info_shows_public_address(self):
        r = self.client.get("/api/contact").json()
        self.assertEqual(r["to"], server.CONTACT_EMAIL)
        self.assertEqual(r["max"], 3000)

    def test_message_is_saved_and_mailed(self):
        r = self.client.post("/api/contact", json=self.body())
        self.assertEqual(r.status_code, 200, r.text)
        msgs = self.client.get("/api/admin/contacts", headers=self.admin).json()["messages"]
        self.assertTrue(any(m["subject"] == "Parceria" and m["lang"] == "en" for m in msgs))

    def test_boom_field_marks_robot_and_sends_nothing(self):
        before = self.client.get("/api/admin/contacts", headers=self.admin).json()
        r = self.client.post("/api/contact", json={**self.body(), ":boom:": "http://spam", "subject": "ROBO"})
        self.assertEqual(r.status_code, 200)  # o robô acha que deu certo
        after = self.client.get("/api/admin/contacts", headers=self.admin).json()
        self.assertEqual(after["robots"], before["robots"] + 1)
        self.assertFalse(any(m["subject"] == "ROBO" for m in after["messages"]))

    def test_needs_captcha_valid_email_and_text(self):
        b = self.body()
        self.assertEqual(self.client.post("/api/contact", json={**b, "captcha": {}}).status_code, 400)
        self.assertEqual(self.client.post("/api/contact", json=self.body(email="sem-arroba")).status_code, 422)
        self.assertEqual(self.client.post("/api/contact", json=self.body(message="oi")).status_code, 422)
        self.assertEqual(self.client.post("/api/contact", json=self.body(message="x" * 3001)).status_code, 422)

    def test_subject_has_no_line_breaks_and_is_optional(self):
        r = self.client.post("/api/contact", json=self.body(subject="a\r\nBcc: x@y.com"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all("\n" not in m["subject"] for m in self.client.get("/api/admin/contacts", headers=self.admin).json()["messages"]))
        msg = mailer.build("eu@gmail.com", "eu@gmail.com", "fan@x.com", "", "texto", "pt-BR", "agora")
        self.assertEqual(msg["Subject"], mailer.SUBJECT_TAG)
        self.assertEqual(msg["Reply-To"], "fan@x.com")

    def test_rate_limit_per_ip(self):
        for _ in range(server.CONTACT_PER_IP[0]):
            self.assertEqual(self.client.post("/api/contact", json=self.body()).status_code, 200)
        self.assertEqual(self.client.post("/api/contact", json=self.body()).status_code, 429)

    def test_mail_off_without_smtp(self):
        with mock.patch.dict("os.environ", {"ARTEMIS_SMTP_USER": "", "ARTEMIS_SMTP_PASSWORD": ""}):
            self.assertFalse(mailer.configured())


class VisitTests(unittest.TestCase):
    admin = property(lambda self: {"X-Admin-Token": server.CONFIG["admin_token"]})

    def setUp(self):
        self.client = TestClient(server.app)
        server._hits.clear()

    def report(self):
        return self.client.get("/api/admin/report?month=" + server.ach.local_day(
            server.datetime.now(server.timezone.utc).isoformat()).strftime("%Y-%m"), headers=self.admin).json()

    def test_page_views_and_unique_visitors(self):
        before = self.report()
        for _ in range(3):
            self.client.get("/", headers=BROWSER)
        self.client.get("/", headers={"User-Agent": "Googlebot/2.1"})       # robô não conta
        self.client.get("/api/health", headers=BROWSER)                     # API não é visita
        after = self.report()
        self.assertEqual(after["page_views"], before["page_views"] + 3)
        self.assertLessEqual(after["unique_visitors"] - before["unique_visitors"], 1)
        self.assertGreaterEqual(after["unique_visitors"], 1)

    def test_no_ip_is_stored(self):
        self.client.get("/", headers={**BROWSER, "X-Forwarded-For": "203.0.113.77"})
        rows = server.store._conn.execute("SELECT period, mark FROM visit_seen").fetchall()
        self.assertTrue(rows)
        self.assertFalse(any("203.0.113.77" in r["mark"] or "203.0.113.77" in r["period"] for r in rows))

    def test_report_validates_month(self):
        self.assertEqual(self.client.get("/api/admin/report?month=2026-13", headers=self.admin).status_code, 422)
        self.assertEqual(self.client.get("/api/admin/report").status_code, 401)


class PageTests(unittest.TestCase):
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    def test_footer_links_tibia_cipsoft_and_hilay(self):
        self.assertIn('href="https://www.tibia.com/mmorpg/free-multiplayer-online-role-playing-game.php"', self.html)
        self.assertIn('href="https://www.cipsoft.com/en/"', self.html)
        self.assertIn('id="openContact"', self.html)
        self.assertIn(">Hilay<", self.html)

    def test_contact_form(self):
        self.assertIn('name=":boom:"', self.html)
        self.assertIn('maxlength="3000"', self.html)
        self.assertIn('placeholder="exemplo@exemplo.com"', self.html)
        self.assertIn('id="contactLang"', self.html)

    def test_no_download_anywhere(self):
        # 0.23.0: o app para Windows foi descontinuado: nenhum botão de download no site
        self.assertNotIn('id="dlLogin"', self.html)
        self.assertNotIn("dlHome", self.js)
        self.assertNotIn('data-page="download"', self.html)
        self.assertNotIn("paintDownload", self.js)

    def test_credits_where_content_is_used(self):
        self.assertIn("Mapa fornecido por", self.js)
        self.assertIn("TibiaWiki BR", self.js)
        self.assertIn('id="creditsScreen"', self.html)


if __name__ == "__main__":
    unittest.main()
