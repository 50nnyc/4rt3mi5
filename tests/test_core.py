import unittest

from artemis.core.parser import ParseError, parse_session
from artemis.core.report import player_view, report_from_text

EXAMPLE = """Session data: From 2026-11-04, 18:50:49 to 2026-11-04, 20:21:07
Session: 01:30h
Loot Type: Leader
Loot: 10,423,400
Supplies: 1,145,238
Balance: 9,278,162
Atx Buubo
\tLoot: 351,206
\tSupplies: 79,655
\tBalance: 271,551
\tDamage: 15,004,707
\tHealing: 1,145,371
Hilay
\tLoot: 7,000,949
\tSupplies: 274,074
\tBalance: 6,726,875
\tDamage: 12,618,253
\tHealing: 1,006,524
Jioe
\tLoot: 0
\tSupplies: 204,839
\tBalance: -204,839
\tDamage: 16,215,326
\tHealing: 7,952,897
Vcte (Leader)
\tLoot: 3,071,245
\tSupplies: 586,670
\tBalance: 2,484,575
\tDamage: 11,560,066
\tHealing: 2,655,684
"""


class ParserTests(unittest.TestCase):
    def test_example(self):
        s = parse_session(EXAMPLE)
        self.assertEqual(len(s.players), 4)
        self.assertEqual(s.balance, 9_278_162)
        self.assertEqual(s.session_label, "01:30h")
        self.assertEqual(s.duration_seconds, 90 * 60 + 18)
        jioe = s.players[2]
        self.assertEqual((jioe.name, jioe.balance), ("Jioe", -204_839))
        self.assertTrue(s.players[3].is_leader)
        self.assertEqual(s.players[3].name, "Vcte")
        self.assertEqual(s.warnings, [])

    def test_without_indentation(self):
        s = parse_session(EXAMPLE.replace("\t", ""))
        self.assertEqual(len(s.players), 4)

    def test_garbage(self):
        with self.assertRaises(ParseError):
            parse_session("oi tudo bem")


class SplitTests(unittest.TestCase):
    def test_example_split(self):
        r = report_from_text(EXAMPLE)
        self.assertEqual(r["profit_each"], 2_319_540)
        got = {(t["payer"], t["receiver"], t["amount"]) for t in r["transfers"]}
        self.assertEqual(got, {
            ("Hilay", "Jioe", 2_524_379),
            ("Hilay", "Atx Buubo", 1_882_956),
            ("Vcte", "Atx Buubo", 165_033),
        })
        # depois das transferências todos ficam com o profit (± resto do arredondamento)
        final = {p["name"]: p["balance"] for p in r["players"]}
        for t in r["transfers"]:
            final[t["payer"]] -= t["amount"]
            final[t["receiver"]] += t["amount"]
        for v in final.values():
            self.assertLess(abs(v - r["profit_each"]), r["players_count"])

    def test_player_view(self):
        r = report_from_text(EXAMPLE)
        v = player_view(r, "hilay")
        self.assertEqual(v["total_pay"], 2_524_379 + 1_882_956)
        self.assertEqual(v["total_receive"], 0)


if __name__ == "__main__":
    unittest.main()
