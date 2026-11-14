"""Bosses do Tibia: reconhecer bosses nas criaturas mortas e separar o loot que veio deles.

Dados em artemis/data/bosses.json (gerado por tools/import_bosses.py a partir da TibiaWiki).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .session import item_key

BOSSES_FILE = Path(__file__).resolve().parent.parent / "data" / "bosses.json"
COINS = {"gold coin", "platinum coin", "crystal coin"}  # dropados por quase tudo: nunca atribuídos a um boss
LINK_TOLERANCE = timedelta(minutes=15)  # sessão individual x Party Hunt Analyser: horários quase iguais


@lru_cache(maxsize=1)
def _data() -> tuple[dict, dict]:
    try:
        raw = json.loads(BOSSES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    bosses = {item_key(b["name"]): {**b, "loot": set(b.get("loot", []))} for b in raw.get("bosses", {}).values()}
    creatures = {item_key(k): set(v) for k, v in raw.get("creature_loot", {}).items()}
    return bosses, creatures


def boss_info(creature: str) -> dict | None:
    """Dados do boss ou None se a criatura não for boss ("the time guardian" e "time guardian" valem)."""
    return _data()[0].get(item_key(creature))


def bosses_in(kills: list[tuple[str, int]]) -> list[dict]:
    """Bosses mortos numa sessão: [{key, name, class, count}]."""
    out = []
    for creature, n in kills:
        b = boss_info(creature)
        if b:
            out.append({"key": item_key(creature), "name": b["name"], "class": b.get("class"), "count": n})
    return out


def _resolve_variants(key: str) -> set[str]:
    """Plural/singular do nome do item ("small sapphires" -> "small sapphire")."""
    out = {key}
    if key.endswith("ies"):
        out.add(key[:-3] + "y")
    if key.endswith("es"):
        out.add(key[:-2])
    if key.endswith("s"):
        out.add(key[:-1])
    return out


def attribute_loot(kills: list[tuple[str, int]], loot: list[tuple[str, int]], whole_session: bool) -> dict[str, list]:
    """Separa o loot por boss: {boss_key: [(item, n)], "_outros": [(item, n)]}.

    whole_session=True (sessão enviada na 👑 Rotação de bosses): todo o loot conta como loot de boss;
    os itens da tabela de algum boss morto vão para ele e o resto fica em "_outros".
    whole_session=False (sessão comum do Stacker): só entram itens da tabela do boss que nenhuma
    criatura comum morta na sessão dropa (estimativa); moedas nunca entram.
    """
    bosses, creatures = _data()
    killed = [item_key(c) for c, _ in kills]
    boss_keys = [k for k in killed if k in bosses]
    common_loot: set[str] = set()
    if not whole_session:
        for k in killed:
            if k not in bosses:
                common_loot |= creatures.get(k, set())
    out: dict[str, list] = {k: [] for k in boss_keys}
    others: list = []
    for item, n in loot:
        names = _resolve_variants(item)
        owner = next((b for b in boss_keys if names & bosses[b]["loot"]), None)
        if not whole_session and (owner is None or names & common_loot or names & COINS):
            continue
        if owner is None:
            others.append((item, n))
        else:
            out[owner].append((item, n))
    if whole_session:
        out["_outros"] = others
    return out


def overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Os dois períodos são a mesma sessão (com folga para o relógio de cada analyser)?"""
    a0, a1 = datetime.fromisoformat(a_start), datetime.fromisoformat(a_end)
    b0, b1 = datetime.fromisoformat(b_start), datetime.fromisoformat(b_end)
    return a0 - LINK_TOLERANCE <= b1 and b0 - LINK_TOLERANCE <= a1
