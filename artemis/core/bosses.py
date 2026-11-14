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
    bosses = {item_key(b["name"]): {**b, "loot": set(b.get("loot", [])), "rare": dict(b.get("rare", {}))}
              for b in raw.get("bosses", {}).values()}
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


RARE_RARITIES = {"very rare", "extremely rare"}  # raridade da TibiaWiki que já conta como drop raro
RARE_VALUE = 500_000  # sem raridade na wiki: item do boss que vale isso ou mais (unidade) também conta


def drop_rarity(boss_key: str, item: str) -> str | None:
    """Raridade do item na tabela do boss segundo a TibiaWiki ("very rare"...), ou None."""
    b = _data()[0].get(boss_key)
    if not b:
        return None
    return next((b["rare"][n] for n in _resolve_variants(item) if n in b["rare"]), None)


def rare_drops(kills: list[tuple[str, int]], loot: list[tuple[str, int]], whole_session: bool,
               unit_price) -> list[dict]:
    """Drops raros de boss na sessão: [{boss_key, boss, item, count, rarity, unit}].

    Raro = "very rare"/"extremely rare" na TibiaWiki ou valor unitário >= RARE_VALUE.
    `unit_price(item) -> int` dá o preço usado no app. Sessão de boss com um boss só: itens fora da
    tabela dele também contam (pelo valor).
    """
    found = bosses_in(kills)
    if not found:
        return []
    split = attribute_loot(kills, loot, whole_session)
    others = split.pop("_outros", [])
    if len(found) == 1:
        split[found[0]["key"]] = split.get(found[0]["key"], []) + others
    names = {b["key"]: b["name"] for b in found}
    out = []
    for bk, pairs in split.items():
        for item, n in pairs:
            if item in COINS:
                continue
            rarity, unit = drop_rarity(bk, item), unit_price(item)
            if (rarity in RARE_RARITIES) or unit >= RARE_VALUE:
                out.append({"boss_key": bk, "boss": names.get(bk, bk), "item": item, "count": n,
                            "rarity": rarity, "unit": unit})
    return sorted(out, key=lambda d: -d["unit"] * d["count"])


def overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Os dois períodos são a mesma sessão (com folga para o relógio de cada analyser)?"""
    a0, a1 = datetime.fromisoformat(a_start), datetime.fromisoformat(a_end)
    b0, b1 = datetime.fromisoformat(b_start), datetime.fromisoformat(b_end)
    return a0 - LINK_TOLERANCE <= b1 and b0 - LINK_TOLERANCE <= a1
