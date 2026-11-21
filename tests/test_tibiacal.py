"""0.22.1: calendário de eventos do Tibia colado pelo administrador (HTML do Event Schedule → só dados)."""
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from artemis.core import tibiacal
from tests import limpar_banco
from tests.test_server import server  # mesmo banco temporário dos testes do servidor

SAMPLE = (Path(__file__).parent / "fixtures" / "tibia_calendar_sample.html").read_text(encoding="utf-8")


class ParserTests(unittest.TestCase):
    def test_reads_month_days_events_and_descriptions(self):
        c = tibiacal.parse_calendar(SAMPLE)
        self.assertEqual(c["month"], "2026-11")
        self.assertEqual(c["days"]["2026-10-31"], [{"name": "Halloween Event", "star": True, "bg": "#235c00", "fg": "#d4c0a1"}])
        self.assertEqual([e["name"] for e in c["days"]["2026-11-12"]], ["Lightbearer", "Full Moon"])
        self.assertTrue(c["days"]["2026-11-12"][1]["star"])
        self.assertEqual(c["days"]["2026-12-04"][0]["name"], "Rapid Respawn")  # dias do mês seguinte
        self.assertEqual(c["days"]["2026-11-04"], [])
        self.assertIn("Don't let even one go out", c["events"]["Lightbearer"]["description"])
        self.assertNotIn("alert", c["events"]["Full Moon"]["description"])  # nada de script do HTML colado
        self.assertEqual(c["events"]["Full Moon"]["description"], "The moon is full! Beware.")

    def test_rejects_other_text(self):
        with self.assertRaises(tibiacal.CalendarError):
            tibiacal.parse_calendar("<div>qualquer coisa</div>")
        with self.assertRaises(tibiacal.CalendarError):
            tibiacal.parse_calendar('<table id="eventscheduletable"><tr><td>1</td></tr></table>')


class CalendarApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        limpar_banco(server.store._conn)
        cls.client = TestClient(server.app)
        key = server.store.create_key(30, "cal")["key"]
        server.store.force_main(key, "Leitor Calendario")
        cls.h = {"X-Access-Key": key, "X-Device-Token": server.store.issue_device(key, "Leitor Calendario")}
        cls.admin = {"X-Admin-Token": server.CONFIG["admin_token"]}

    def test_admin_publishes_users_read_data_only(self):
        self.assertEqual(self.client.post("/api/admin/calendar", json={"raw_html": SAMPLE}).status_code, 401)
        self.assertEqual(self.client.post("/api/admin/calendar", json={"raw_html": SAMPLE},
                                          headers={**self.admin, "X-Forwarded-For": "1.2.3.4"}).status_code, 403)
        bad = self.client.post("/api/admin/calendar", json={"raw_html": "<p>não é o calendário</p>"}, headers=self.admin)
        self.assertEqual(bad.status_code, 422)
        r = self.client.post("/api/admin/calendar", json={"raw_html": SAMPLE}, headers=self.admin).json()
        self.assertEqual(r["month"], "2026-11")
        self.assertIn("Lightbearer", r["events"])
        second = SAMPLE.replace("Rapid Respawn", "Rapid Respawn Novo")
        self.client.post("/api/admin/calendar", json={"raw_html": second}, headers=self.admin)
        months = self.client.get("/api/admin/calendar", headers=self.admin).json()
        self.assertEqual(next(m for m in months if m["month"] == "2026-11")["versions"], 2)  # histórico guardado
        u = self.client.get("/api/tibia/calendar?month=2026-11", headers=self.h).json()
        self.assertIn("Rapid Respawn Novo", u["calendar"]["events"])  # o app mostra a mais nova
        self.assertNotIn("raw_html", u["calendar"])                   # o HTML colado nunca sai
        self.assertNotIn("<", str(u["calendar"]["events"]))
        # desfazer a última colagem volta a valer a anterior
        self.assertEqual(self.client.delete("/api/admin/calendar/2026-11", headers=self.admin).status_code, 200)
        u = self.client.get("/api/tibia/calendar?month=2026-11", headers=self.h).json()
        self.assertIn("Rapid Respawn", u["calendar"]["events"])
        self.assertNotIn("Rapid Respawn Novo", u["calendar"]["events"])
        self.assertEqual(self.client.get("/api/tibia/calendar").status_code, 401)

    def test_report_of_month_without_visits(self):
        # 0.22.1: mês sem nenhuma visita ainda dava erro 500 no painel
        r = self.client.get("/api/admin/report?month=1999-01", headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["unique_visitors"], 0)


if __name__ == "__main__":
    unittest.main()
