"""Leitura do texto do Party Hunt Analyser do Tibia.

Formato esperado (copiado do cliente):

    Session data: From 2026-11-04, 18:50:49 to 2026-11-04, 20:21:07
    Session: 01:30h
    Loot Type: Leader
    Loot: 10,423,400
    Supplies: 1,145,238
    Balance: 9,278,162
    Nome Do Char
        Loot: 351,206
        Supplies: 79,655
        Balance: 271,551
        Damage: 15,004,707
        Healing: 1,145,371
    Outro Char (Leader)
        ...

A indentação é opcional: muitas vezes ela se perde ao colar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime


class ParseError(ValueError):
    """Texto colado não está no formato do Party Hunt Analyser."""


_SESSION_DATA = re.compile(
    r"^Session data:\s*From\s+(\d{4}-\d{2}-\d{2}),?\s*(\d{2}:\d{2}:\d{2})\s+"
    r"to\s+(\d{4}-\d{2}-\d{2}),?\s*(\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)
_SESSION = re.compile(r"^Session:\s*(\d+):(\d{2})\s*h?\s*$", re.IGNORECASE)
_LOOT_TYPE = re.compile(r"^Loot Type:\s*(.+)$", re.IGNORECASE)
_FIELD = re.compile(r"^(Loot|Supplies|Balance|Damage|Healing):\s*(-?[\d.,]+)\s*$", re.IGNORECASE)
_LEADER = re.compile(r"^(.*?)\s*\(Leader\)\s*$", re.IGNORECASE)
# Nomes do Tibia: letras, espaços, apóstrofo, hífen e ponto; 2 a 29 caracteres.
_NAME = re.compile(r"^[A-Za-z][A-Za-z '\-.]{1,28}$")


@dataclass
class PlayerResult:
    name: str
    is_leader: bool = False
    loot: int = 0
    supplies: int = 0
    balance: int = 0
    damage: int = 0
    healing: int = 0


@dataclass
class HuntSession:
    started_at: datetime
    ended_at: datetime
    session_label: str          # ex.: "01:30h"
    loot_type: str
    loot: int
    supplies: int
    balance: int
    players: list[PlayerResult]
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> int:
        secs = int((self.ended_at - self.started_at).total_seconds())
        if secs > 0:
            return secs
        m = _SESSION.match(f"Session: {self.session_label}")
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 if m else 0


def _num(raw: str) -> int:
    neg = raw.strip().startswith("-")
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        raise ParseError(f"Número inválido: {raw!r}")
    value = int(digits)
    return -value if neg else value


def parse_session(text: str) -> HuntSession:
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise ParseError("Nenhum texto colado.")

    started = ended = None
    label = ""
    loot_type = ""
    header: dict[str, int] = {}
    players: list[PlayerResult] = []
    current: PlayerResult | None = None

    for line in lines:
        if m := _SESSION_DATA.match(line):
            started = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
            ended = datetime.fromisoformat(f"{m.group(3)}T{m.group(4)}")
            continue
        if m := _SESSION.match(line):
            label = f"{m.group(1)}:{m.group(2)}h"
            continue
        if m := _LOOT_TYPE.match(line):
            loot_type = m.group(1).strip()
            continue
        if m := _FIELD.match(line):
            key, value = m.group(1).lower(), _num(m.group(2))
            if current is None:
                header[key] = value
            else:
                setattr(current, key, value)
            continue

        # Qualquer outra linha é o nome de um jogador.
        is_leader = False
        name = line
        if m := _LEADER.match(line):
            name, is_leader = m.group(1).strip(), True
        if not _NAME.match(name):
            raise ParseError(f"Linha não reconhecida: {line!r}")
        current = PlayerResult(name=name, is_leader=is_leader)
        players.append(current)

    if started is None or ended is None:
        raise ParseError("Linha 'Session data: From ... to ...' não encontrada.")
    if not players:
        raise ParseError("Nenhum jogador encontrado no texto.")
    names = [p.name.lower() for p in players]
    if len(set(names)) != len(names):
        raise ParseError("Há jogadores repetidos no texto.")

    warnings: list[str] = []
    for p in players:
        if p.loot - p.supplies != p.balance:
            warnings.append(f"{p.name}: Loot - Supplies ({p.loot - p.supplies:,}) difere do Balance ({p.balance:,}).")
    sum_balance = sum(p.balance for p in players)
    if "balance" in header and header["balance"] != sum_balance:
        warnings.append(f"Balance total ({header['balance']:,}) difere da soma dos jogadores ({sum_balance:,}).")

    return HuntSession(
        started_at=started,
        ended_at=ended,
        session_label=label,
        loot_type=loot_type,
        loot=header.get("loot", sum(p.loot for p in players)),
        supplies=header.get("supplies", sum(p.supplies for p in players)),
        balance=header.get("balance", sum_balance),
        players=players,
        warnings=warnings,
    )
