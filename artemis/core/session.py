"""Leitura do Hunt Analyser individual (Hunt Session Stacker).

Exemplo do texto copiado do cliente:

    Session data: From 2026-11-04, 18:50:49 to 2026-11-04, 20:21:07
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
    Looted Items:
      3x gold coin

Só guardamos: XP bruta, XP, supplies, balance, damage, damage/h, healing, healing/h.
O resto (monstros, itens, loot) é descartado por enquanto.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .parser import _SESSION, _SESSION_DATA, ParseError, _num

_KV = re.compile(r"^([A-Za-z][A-Za-z /]*?):\s*(-?[\d.,]+)\s*$")
_SECTION = re.compile(r"^(Killed Monsters|Looted Items):\s*$", re.IGNORECASE)
_COUNT = re.compile(r"^(\d[\d.,]*)\s*x\s+(.+?)\s*$", re.IGNORECASE)
_ARTICLE = re.compile(r"^(a|an|the)\s+", re.IGNORECASE)


def item_key(name: str) -> str:
    """Nome normalizado do item/criatura: minúsculo, sem artigo ("a dwarven shield" -> "dwarven shield")."""
    return _ARTICLE.sub("", " ".join(name.split())).lower()

_FIELDS = {
    "raw xp gain": "raw_xp",
    "xp gain": "xp",
    "supplies": "supplies",
    "balance": "balance",
    "damage": "damage",
    "damage/h": "damage_h",
    "healing": "healing",
    "healing/h": "healing_h",
}


@dataclass
class SoloSession:
    started_at: str
    ended_at: str
    duration_seconds: int
    session_label: str
    raw_xp: int = 0
    xp: int = 0
    supplies: int = 0
    balance: int = 0
    damage: int = 0
    damage_h: int = 0
    healing: int = 0
    healing_h: int = 0
    kills: list = field(default_factory=list)   # [(criatura, quantidade)]
    loot: list = field(default_factory=list)    # [(item, quantidade)]

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self, character: str) -> str:
        key = f"{character.lower()}|{self.started_at}|{self.ended_at}"
        return hashlib.sha256(key.encode()).hexdigest()


def parse_solo_session(text: str) -> SoloSession:
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise ParseError("Nenhum texto colado.")
    if any(ln.lower().startswith("loot type:") for ln in lines):
        raise ParseError("Esse texto é do Party Hunt Analyser. Use a opção Lootsplit para ele.")

    started = ended = None
    label = ""
    values: dict[str, int] = {}
    sections: dict[str, dict[str, int]] = {"killed monsters": {}, "looted items": {}}
    section = None
    for line in lines:
        if m := _SECTION.match(line):
            section = m.group(1).lower()
            continue
        if section:
            if m := _COUNT.match(line):
                name = item_key(m.group(2))
                bucket = sections[section]
                bucket[name] = bucket.get(name, 0) + _num(m.group(1))
                continue
            section = None  # fim da lista
        if m := _SESSION_DATA.match(line):
            started = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
            ended = datetime.fromisoformat(f"{m.group(3)}T{m.group(4)}")
            continue
        if m := _SESSION.match(line):
            label = f"{m.group(1)}:{m.group(2)}h"
            continue
        if m := _KV.match(line):
            field = _FIELDS.get(m.group(1).strip().lower())
            if field:
                values[field] = _num(m.group(2))
            # campos que não guardamos (Loot, Raw XP/h, XP/h...) são ignorados

    if started is None or ended is None:
        raise ParseError("Linha 'Session data: From ... to ...' não encontrada.")
    if "xp" not in values or "balance" not in values:
        raise ParseError("Esse texto não parece um Hunt Analyser individual (faltam XP Gain / Balance).")

    duration = int((ended - started).total_seconds())
    if duration <= 0 and (m := _SESSION.match(f"Session: {label}")):
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60
    return SoloSession(
        started_at=started.isoformat(),
        ended_at=ended.isoformat(),
        duration_seconds=max(duration, 0),
        session_label=label,
        kills=sorted(sections["killed monsters"].items(), key=lambda kv: -kv[1]),
        loot=sorted(sections["looted items"].items(), key=lambda kv: -kv[1]),
        **values,
    )
