"""0.12.0: regras de divisão, "já paguei", comparação com a média, ranking entre amigos,
imagens da TibiaWiki guardadas no banco e backup automático."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from artemis.core.split import split_with_rules
from artemis.server import app as server
from tests import test_bosses as tb
from tests.test_core import EXAMPLE

PARTY = EXAMPLE.replace(EXAMPLE.strip().splitlines()[0],
                        "Session data: From 2026-10-01, 10:00:00 to 2026-10-01, 11:30:00")

SOLO = """Session data: From 2026-10-0{d}, 10:00:00 to 2026-10-0{d}, 11:00:00
Session: 01:00h
Raw XP Gain: 1,000,000
XP Gain: {xp}
Loot: 500,000
Supplies: 100,000
Balance: {bal}
Damage: 1,000,000
Damage/h: 1,000,000
Healing: 100,000
Healing/h: 100,000
Killed Monsters:
  10x dragon
Looted Items:
  5x platinum coins
"""


class SplitRulesCoreTests(unittest.TestCase):
    def test_excluded_and_fixed(self):
        balances = {"A": 6_000_000, "B": 0, "C": -200_000, "D": 2_000_000}
        share, transfers, diff, target = split_with_rules(balances, {"C"}, {"D": 1_000_000})
        self.assertEqual(target["C"], 0)
        self.assertEqual(target["D"], 1_000_000)
        self.assertEqual(share, (7_800_000 - 1_000_000) // 2)
        self.assertEqual(diff["C"], -200_000)  # recebe os supplies de volta
        self.assertEqual(sum(t.amount for t in transfers if t.receiver == "C"), 200_000)
        with self.assertRaises(ValueError):
            split_with_rules({"A": 1, "B": 2}, {"A"}, {"B": 0})


class V012ServerTests(unittest.TestCase):
    """Reaproveita setUp/login dos testes de bosses (TibiaData simulado, banco temporário)."""
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def test_rules_and_payments(self):
        hilay, jioe, outsider = self.login("Hilay"), self.login("Jioe"), self.login("Fulano Fora")
        r = self.client.post("/api/lootsplit", json={"raw_text": PARTY, "nickname": "Hilay"}, headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        hunt = r.json()["hunt"]
        hid = hunt["id"]
        self.assertTrue(all(t["paid_at"] is None for t in hunt["transfers"]))
        t = next(t for t in hunt["transfers"] if t["receiver"] == "Jioe")
        body = {"payer": t["payer"], "receiver": "Jioe", "paid": True}
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/paid", json=body, headers=outsider).status_code, 403)
        r = self.client.post(f"/api/hunt/{hid}/paid", json=body, headers=jioe)  # quem recebe também marca
        self.assertEqual(r.status_code, 200, r.text)
        marked = next(x for x in r.json()["hunt"]["transfers"] if x["receiver"] == "Jioe")
        self.assertIsNotNone(marked["paid_at"])
        self.assertEqual(r.json()["hunt"]["pending"], len(hunt["transfers"]) - 1)
        # regras: só quem enviou muda; mudar apaga as marcações
        rules = {"excluded": ["jioe"], "fixed": {"Vcte": 1_000_000}}
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/rules", json=rules, headers=jioe).status_code, 403)
        r = self.client.post(f"/api/hunt/{hid}/rules", json=rules, headers=hilay)
        self.assertEqual(r.status_code, 200, r.text)
        h = r.json()["hunt"]
        self.assertEqual(h["rules"], {"excluded": ["Jioe"], "fixed": {"Vcte": 1_000_000}})
        self.assertEqual(h["profit_each"], (9_278_162 - 1_000_000) // 2)
        profit = {p["name"]: p["profit"] for p in h["players"]}
        self.assertEqual((profit["Jioe"], profit["Vcte"]), (0, 1_000_000))
        self.assertTrue(all(x["paid_at"] is None for x in h["transfers"]))
        # quem vê a hunt depois recebe a divisão nova
        seen = self.client.get("/api/hunts/Jioe", headers=jioe).json()["hunts"]
        self.assertEqual(next(x for x in seen if x["id"] == hid)["rules"]["excluded"], ["Jioe"])
        bad = self.client.post(f"/api/hunt/{hid}/rules", json={"excluded": ["Hilay", "Jioe", "Vcte", "Bobeek"]}, headers=hilay)
        self.assertEqual(bad.status_code, 422)
        bad = self.client.post(f"/api/hunt/{hid}/rules", json={"excluded": ["Ninguem"]}, headers=hilay)
        self.assertEqual(bad.status_code, 422)
        r = self.client.post(f"/api/hunt/{hid}/rules", json={}, headers=hilay)  # volta a dividir igual
        self.assertIsNone(r.json()["hunt"]["rules"])
        self.assertEqual(r.json()["hunt"]["profit_each"], 2_319_540)

    def test_compare_with_average(self):
        kn = self.login("Kaio Compara")
        place = server.store.places()[0]["id"]
        first = self.client.post("/api/stacker", json={"raw_text": SOLO.format(d=1, xp="2,000,000", bal="400,000"),
                                                       "nickname": "Kaio Compara", "place_id": place}, headers=kn).json()
        self.assertEqual(first["compare"]["sessions"], 0)
        second = self.client.post("/api/stacker", json={"raw_text": SOLO.format(d=2, xp="3,000,000", bal="200,000"),
                                                        "nickname": "Kaio Compara", "place_id": place}, headers=kn).json()
        c = second["compare"]
        self.assertEqual((c["sessions"], c["avg_xp_h"], c["xp_h"]), (1, 2_000_000, 3_000_000))
        self.assertEqual((c["xp_pct"], c["gold_pct"]), (50, -50))

    def test_ranking_only_who_joined(self):
        a, b = self.login("Rank Um"), self.login("Rank Dois")
        place = server.store.places()[0]["id"]
        self.client.post("/api/stacker", json={"raw_text": SOLO.format(d=3, xp="5,000,000", bal="1,000,000"),
                                               "nickname": "Rank Um", "place_id": place}, headers=a)
        with mock.patch.object(server, "datetime", wraps=datetime) as dt:
            dt.now.return_value = datetime(2026, 10, 5)
            names = [r["name"] for r in self.client.get("/api/ranking?period=7", headers=a).json()["rows"]]
            self.assertNotIn("Rank Um", names)
            self.assertEqual(self.client.post("/api/ranking/Rank Um", json={"join": True}, headers=b).status_code, 403)
            self.assertTrue(self.client.post("/api/ranking/Rank Um", json={"join": True}, headers=a).json()["joined"])
            d = self.client.get("/api/ranking?period=7&metric=xp&nick=Rank Um", headers=b).json()
            row = next(r for r in d["rows"] if r["name"] == "Rank Um")
            self.assertEqual((row["xp"], row["xp_h"], row["sessions"]), (5_000_000, 5_000_000, 1))
            self.assertTrue(d["joined"])
            self.client.post("/api/ranking/Rank Um", json={"join": False}, headers=a)
            names = [r["name"] for r in self.client.get("/api/ranking", headers=a).json()["rows"]]
            self.assertNotIn("Rank Um", names)


class WikiImageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server._hits.clear()
        server.store._conn.execute("DELETE FROM wiki_images")
        server.store._conn.commit()

    def test_cached_in_db_after_first_fetch(self):
        with mock.patch.object(server, "_fetch_wiki_image", return_value=("image/gif", b"GIF89a-x")) as f:
            r1 = self.client.get("/img/wiki/Dragon_Scale_Mail.gif")
            r2 = self.client.get("/img/wiki/Dragon_Scale_Mail.gif")
        self.assertEqual((r1.status_code, r1.content), (200, b"GIF89a-x"))
        self.assertEqual(r2.content, b"GIF89a-x")
        self.assertEqual(f.call_count, 1)  # a segunda veio do banco
        self.assertIn("max-age", r2.headers["cache-control"])

    def test_missing_and_wiki_down(self):
        with mock.patch.object(server, "_fetch_wiki_image", return_value=None) as f:
            self.assertEqual(self.client.get("/img/wiki/Nao_Existe.gif").status_code, 404)
            self.assertEqual(self.client.get("/img/wiki/Nao_Existe.gif").status_code, 404)
        self.assertEqual(f.call_count, 1)
        with mock.patch.object(server, "_fetch_wiki_image", return_value=False):
            r = self.client.get("/img/wiki/Demodras.gif", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["location"].startswith("https://www.tibiawiki.com.br/"))
        self.assertEqual(self.client.get("/img/wiki/%3Cscript%3E.gif").status_code, 404)


class BackupTests(unittest.TestCase):
    def test_daily_backup_keeps_latest(self):
        tmp = Path(tempfile.mkdtemp(prefix="artemis_bkp_"))
        with mock.patch.object(server, "BACKUP_DIR", tmp), mock.patch.object(server, "BACKUP_KEEP", 3):
            for day in range(1, 6):
                self.assertIsNotNone(server.daily_backup(datetime(2026, 11, day, 3)))
            self.assertIsNone(server.daily_backup(datetime(2026, 11, 5, 9)))  # um por dia
        self.assertEqual(sorted(p.name for p in tmp.iterdir()),
                         ["artemis-20261103.db", "artemis-20261104.db", "artemis-20261105.db"])


if __name__ == "__main__":
    unittest.main()
