import unittest

from artemis.core.levels import LEVEL_XP, level_for_xp, xp_at, xp_to_next_level


class LevelTableTests(unittest.TestCase):
    def test_tabela_oficial(self):
        # valores da tabela do tibia.com (library/?subtopic=experiencetable)
        self.assertEqual(xp_at(1), 0)
        self.assertEqual(xp_at(2), 100)
        self.assertEqual(xp_at(8), 4200)
        self.assertEqual(xp_at(100), 15694800)
        self.assertEqual(LEVEL_XP[999], xp_at(999))
        for lv in range(1, 1000):
            self.assertEqual(xp_at(lv + 1) - xp_at(lv), xp_to_next_level(lv))

    def test_level_for_xp(self):
        self.assertEqual(level_for_xp(0), 1)
        self.assertEqual(level_for_xp(99), 1)
        self.assertEqual(level_for_xp(100), 2)
        self.assertEqual(level_for_xp(xp_at(1225)), 1225)
        self.assertEqual(level_for_xp(xp_at(1226) - 1), 1225)


if __name__ == "__main__":
    unittest.main()
