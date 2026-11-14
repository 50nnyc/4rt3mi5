"""Tabela de experiência do Tibia (https://www.tibia.com/library/?subtopic=experiencetable).

A tabela oficial vai até o level 999 e bate 100% com a fórmula
  XP total do level L = 50/3 * (L³ - 6L² + 17L - 12),
que também vale acima de 999. Por isso a tabela é gerada pela fórmula
(conferida contra a página oficial nos 999 levels).
"""
from __future__ import annotations

from bisect import bisect_right

MAX_TABLE_LEVEL = 5000


def total_xp(level: int) -> int:
    """XP total necessária para estar no início do level."""
    return round(50 / 3 * (level ** 3 - 6 * level ** 2 + 17 * level - 12))


def xp_to_next_level(level: int) -> int:
    """XP para ir do início do level L ao L+1."""
    return 50 * level * level - 150 * level + 200


# LEVEL_XP[L] = XP total no início do level L (índice 0 não é usado)
LEVEL_XP: list[int] = [0] + [total_xp(lv) for lv in range(1, MAX_TABLE_LEVEL + 1)]


def level_for_xp(xp: int) -> int:
    """Level correspondente a uma quantidade total de XP."""
    return max(1, bisect_right(LEVEL_XP, xp, lo=1) - 1)


def xp_at(level: int) -> int:
    return LEVEL_XP[level] if 0 < level <= MAX_TABLE_LEVEL else total_xp(level)
