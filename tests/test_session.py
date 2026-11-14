import unittest

from artemis.core.parser import ParseError
from artemis.core.session import parse_solo_session

SOLO = """Session data: From 2026-11-04, 18:50:49 to 2026-11-04, 20:20:49
Session: 01:30h
Raw XP Gain: 5,123,456
XP Gain: 7,684,000
Raw XP/h: 3,415,637
XP/h: 5,122,666
Loot: 1,234,567
Supplies: 456,789
Balance: 777,778
Damage: 12,345,678
Damage/h: 8,230,452
Healing: 2,345,678
Healing/h: 1,563,785
Killed Monsters:
  120x dragon
  3x dragon lord
Looted Items:
  3x gold coin
"""


class SoloTests(unittest.TestCase):
    def test_parse(self):
        s = parse_solo_session(SOLO)
        self.assertEqual(s.raw_xp, 5_123_456)
        self.assertEqual(s.xp, 7_684_000)
        self.assertEqual(s.supplies, 456_789)
        self.assertEqual(s.balance, 777_778)
        self.assertEqual(s.damage_h, 8_230_452)
        self.assertEqual(s.healing_h, 1_563_785)
        self.assertEqual(s.duration_seconds, 5400)
        self.assertEqual(dict(s.kills), {"dragon": 120, "dragon lord": 3})
        self.assertEqual(dict(s.loot), {"gold coin": 3})

    def test_user_example_with_articles(self):
        s = parse_solo_session("""Session data: From 2026-11-13, 22:45:33 to 2026-11-13, 22:50:12
Session: 00:04h
Raw XP Gain: 757
XP Gain: 1,133
Raw XP/h: 9,756
XP/h: 14,602
Loot: 112
Supplies: 0
Balance: 112
Damage: 1,275
Damage/h: 393,316
Healing: 0
Healing/h: 0
Killed Monsters:
  2x dwarf
  2x dwarf guard
  3x dwarf soldier
  2x minotaur
Looted Items:
  1x a dwarven shield
  6x a white mushroom
""")
        self.assertEqual(s.xp, 1133)
        self.assertEqual(dict(s.kills), {"dwarf": 2, "dwarf guard": 2, "dwarf soldier": 3, "minotaur": 2})
        self.assertEqual(s.loot, [("white mushroom", 6), ("dwarven shield", 1)])

    def test_party_text_rejected(self):
        from tests.test_core import EXAMPLE
        with self.assertRaises(ParseError):
            parse_solo_session(EXAMPLE)


if __name__ == "__main__":
    unittest.main()
