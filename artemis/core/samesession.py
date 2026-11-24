"""0.31.0: reconhece o mesmo Party Hunt Analyser enviado por pessoas diferentes.

Cada membro copia o analyser num momento: o início é o mesmo, mas o fim (e por isso o loot) pode sair diferente
se a sessão ainda estava rodando. A impressão digital exata (início + fim + nomes) não pega esse caso."""
from __future__ import annotations

from datetime import datetime

START_TOLERANCE = 5 * 60        # início "igual": até 5 minutos de diferença
OVERLAP_SHARE = 0.6             # ou os períodos se cobrem em pelo menos 60% do mais curto
PLAYERS_SHARE = 0.6             # e a PT é praticamente a mesma (entrou/saiu alguém)
UPDATE_MARGIN = 60              # a versão nova só vence se for mais de 1 minuto mais longa


def _t(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _names(report: dict) -> set[str]:
    return {str(p.get("name", "")).strip().lower() for p in report.get("players", []) if p.get("name")}


def same_session(a: dict, b: dict) -> bool:
    """Os dois relatórios são a mesma sessão da PT? Duas hunts seguidas da mesma PT não contam (períodos separados)."""
    na, nb = _names(a), _names(b)
    if not na or not nb or len(na & nb) / len(na | nb) < PLAYERS_SHARE:
        return False
    a0, a1, b0, b1 = _t(a.get("started_at")), _t(a.get("ended_at")), _t(b.get("started_at")), _t(b.get("ended_at"))
    if not (a0 and b0):
        return False
    if abs((a0 - b0).total_seconds()) <= START_TOLERANCE:
        return True
    if not (a1 and b1):
        return False
    inter = (min(a1, b1) - max(a0, b0)).total_seconds()
    shortest = min((a1 - a0).total_seconds(), (b1 - b0).total_seconds())
    return shortest > 0 and inter / shortest >= OVERLAP_SHARE


def completeness(report: dict) -> tuple:
    """Quanto mais longa e com mais jogadores, mais completa (empate: mais loot)."""
    return (int(report.get("duration_seconds") or 0), len(report.get("players", [])), int(report.get("loot") or 0))


def is_more_complete(new: dict, old: dict) -> bool:
    """A versão nova é mesmo mais completa (mais de 1 minuto a mais, ou mais jogadores na mesma duração)?"""
    n, o = completeness(new), completeness(old)
    if n[0] > o[0] + UPDATE_MARGIN:
        return True
    return abs(n[0] - o[0]) <= UPDATE_MARGIN and (n[1], n[2]) > (o[1], o[2])
