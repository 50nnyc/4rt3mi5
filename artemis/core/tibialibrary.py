"""Biblioteca de criaturas e bosses do tibia.com pela API pública do TibiaData (v4). Só usa a stdlib.

O catálogo diz quais criaturas e bosses têm imagem oficial; os detalhes existem só para criaturas.
"""
from __future__ import annotations

import re
import urllib.parse

from .tibiaboosted import TibiaBoostedError, _clean, _get_json, _image

CREATURES_URL = "https://api.tibiadata.com/v4/creatures"
CREATURE_URL = "https://api.tibiadata.com/v4/creature/{}"
BOSSES_URL = "https://api.tibiadata.com/v4/boostablebosses"
BOSSES_PAGE = "https://www.tibia.com/library/?subtopic=boostablebosses"
CREATURE_PAGE = "https://www.tibia.com/library/?subtopic=creatures&race={}"
_RACE = re.compile(r"[a-z0-9_\-]{1,60}")
TibiaLibraryError = TibiaBoostedError


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _plurals(word: str) -> list[str]:
    out = [word + "s", word + "es"]
    if word.endswith("y"):
        out.append(word[:-1] + "ies")
    if word.endswith("f"):
        out.append(word[:-1] + "ves")
    if word.endswith("fe"):
        out.append(word[:-2] + "ves")
    if word.endswith("man"):
        out.append(word[:-3] + "men")
    return out


def name_keys(name: str) -> list[str]:
    """Chaves para achar um nome no singular: ele mesmo e os plurais da palavra principal
    ("elf" -> "elves", "acolyte of the cult" -> "acolytes of the cult"), como a lista do tibia.com escreve."""
    words = str(name or "").lower().split()
    if not words:
        return []
    head = words.index("of") - 1 if "of" in words[1:] else len(words) - 1
    out = [slug(" ".join(words))]
    out += [slug(" ".join(words[:head] + [p] + words[head + 1:])) for p in _plurals(words[head])]
    return out


def parse_catalog(creatures: dict, bosses: dict) -> dict:
    """{"races": {race: imagem}, "plurals": {nome no plural: race}, "bosses": {nome: imagem}}, chaves sem espaços."""
    out: dict = {"races": {}, "plurals": {}, "bosses": {}}
    for c in (creatures.get("creatures") or {}).get("creature_list") or []:
        race, image = str(c.get("race") or ""), _image(c.get("image_url"))
        if _RACE.fullmatch(race) and image:
            out["races"][race] = image
            out["plurals"][slug(c.get("name"))] = race
    for b in (bosses.get("boostable_bosses") or {}).get("boostable_boss_list") or []:
        name, image = _clean(b.get("name")), _image(b.get("image_url"))
        if name and image:
            out["bosses"][slug(name)] = image
    return out


def fetch_catalog(timeout: float = 15) -> dict:
    out = parse_catalog(_get_json(CREATURES_URL, timeout), _get_json(BOSSES_URL, timeout))
    if not out["races"] or not out["bosses"]:
        raise TibiaLibraryError("Biblioteca do tibia.com indisponível agora.")
    return out


def find_race(catalog: dict, name: str) -> str | None:
    for key in name_keys(name):
        race = catalog["plurals"].get(key)
        if race:
            return race
    key = slug(name)
    return key if key in catalog["races"] else None


def find_boss(catalog: dict, name: str) -> str | None:
    """Imagem do boss ("the time guardian" e "time guardian" valem)."""
    key = slug(name)
    short = slug(re.sub(r"^the\s+", "", str(name or "").lower()))
    for k in (key, short, "the" + short):
        if k in catalog["bosses"]:
            return catalog["bosses"][k]
    return None


def _num(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _words(v) -> list[str]:
    return [s for s in (" ".join(str(x).split())[:60] for x in (v if isinstance(v, list) else [])) if s][:40]


def _text(v) -> str:
    return str(v or "").strip()[:4000]


def parse_creature(data: dict, race: str) -> dict:
    """Só os campos que o card usa, já limpos."""
    c = data.get("creature") or {}
    if not c.get("name"):
        raise TibiaLibraryError("Criatura sem detalhes no TibiaData.")
    return {"url": CREATURE_PAGE.format(race), "hp": _num(c.get("hitpoints")), "exp": _num(c.get("experience_points")),
            "immune": _words(c.get("immune")), "strong": _words(c.get("strong")), "weakness": _words(c.get("weakness")),
            "healed": _words(c.get("healed")), "loot": _words(c.get("loot_list")),
            "paralysable": bool(c.get("be_paralysed")), "sees_invisible": bool(c.get("see_invisible")),
            "summon_mana": _num(c.get("summoned_mana")) if c.get("be_summoned") else None,
            "convince_mana": _num(c.get("convinced_mana")) if c.get("be_convinced") else None,
            "description": _text(c.get("description")), "behaviour": _text(c.get("behaviour"))}


def fetch_creature(race: str, timeout: float = 15) -> dict:
    if not _RACE.fullmatch(race):
        raise TibiaLibraryError("Criatura desconhecida.")
    return parse_creature(_get_json(CREATURE_URL.format(urllib.parse.quote(race)), timeout), race)
