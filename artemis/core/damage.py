"""Leitura do Input Analyser do Tibia (dano recebido) — 0.20.0.

Exemplo do texto copiado do cliente:

    Received Damage
    Total: 220,388
    Max-DPS: 6,143
    Damage Types
      Physical 81,976 (37.2%)
      Ice 56,033 (25.4%)
    Damage Sources
      The Moonsnow Magnolia 67,009 (30.4%)
      rogue naga 31,001 (14.1%)
      (other) 48 (5.5%)

"(other)" não é criatura: entra só no total e aparece como "(other)", sem inventar de onde veio.
"""
from __future__ import annotations

import re

from .parser import ParseError, _num

OTHER = "(other)"
_TOTAL = re.compile(r"^Total:\s*([\d.,]+)\s*$", re.IGNORECASE)
_MAX_DPS = re.compile(r"^Max-?DPS:\s*([\d.,]+)\s*$", re.IGNORECASE)
_ROW = re.compile(r"^(.+?)\s+([\d][\d.,]*)\s*\(\s*([\d.,]+)\s*%\s*\)\s*$")
_SECTIONS = {"damage types": "types", "damage sources": "sources"}
MAX_ROWS = 40  # o cliente mostra poucas linhas; mais que isso não é um Input Analyser


def _pct(s: str) -> float:
    return round(float(s.replace(",", ".")), 1)


def parse_input(text: str) -> dict:
    """Texto do Input Analyser -> {total, max_dps, types: [{name, value, pct}], sources: [{name, value, pct, other}]}."""
    lines = [ln.strip() for ln in (text or "").replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise ParseError("Nenhum texto colado.")
    if any(ln.lower().startswith(("session data:", "loot type:")) for ln in lines):
        raise ParseError("Esse texto é de um Hunt Analyser. Aqui vai o Input Analyser (Received Damage).")
    if not any(ln.lower() == "received damage" for ln in lines):
        raise ParseError("Esse texto não parece o Input Analyser: falta a linha 'Received Damage'.")
    total = max_dps = None
    out: dict[str, list] = {"types": [], "sources": []}
    section = None
    for line in lines:
        low = line.lower()
        if low in _SECTIONS:
            section = _SECTIONS[low]
            continue
        if m := _TOTAL.match(line):
            total, section = _num(m.group(1)), None
            continue
        if m := _MAX_DPS.match(line):
            max_dps, section = _num(m.group(1)), None
            continue
        if section and (m := _ROW.match(line)):
            name = " ".join(m.group(1).split())
            if len(name) > 60:
                raise ParseError("Nome grande demais numa linha do Input Analyser.")
            row = {"name": name, "value": _num(m.group(2)), "pct": _pct(m.group(3))}
            if section == "sources":
                row["other"] = name.lower() == OTHER
            out[section].append(row)
    if total is None:
        raise ParseError("Linha 'Total:' não encontrada no Input Analyser.")
    if not out["types"] and not out["sources"]:
        raise ParseError("O Input Analyser não tem 'Damage Types' nem 'Damage Sources'.")
    if len(out["types"]) > MAX_ROWS or len(out["sources"]) > MAX_ROWS:
        raise ParseError("Esse texto tem linhas demais para um Input Analyser.")
    for key in ("types", "sources"):
        out[key].sort(key=lambda r: -r["value"])
    return {"total": total, "max_dps": max_dps or 0, **out}


LOW_DPS = 25        # média de dano recebido por segundo abaixo disso, numa hunt longa, é suspeita
LOW_MIN_SECONDS = 600
LOW_PEER_SHARE = 0.10  # ou menos de 10% do que os outros da PT receberam


def looks_low(data: dict, duration_seconds: int | None, peer_totals: list[int] | None = None) -> bool:
    """0.31.2: o total do Input Analyser parece pequeno demais para a hunt (ex.: o painel estava em
    "Recent values" em vez de "Session values")? Só um aviso: quem tem certeza salva do mesmo jeito."""
    total = data.get("total") or 0
    if duration_seconds and duration_seconds >= LOW_MIN_SECONDS and total / duration_seconds < LOW_DPS:
        return True
    peers = sorted(p for p in (peer_totals or []) if p > 0)
    if peers:
        median = peers[len(peers) // 2]
        return total < median * LOW_PEER_SHARE
    return False


def summary(data: dict) -> dict:
    """O que a tela mostra: quanto apanhou, o elemento que mais bateu e a criatura que mais bateu."""
    mobs = [s for s in data.get("sources", []) if not s.get("other")]
    return {"total": data["total"], "max_dps": data.get("max_dps", 0),
            "top_type": data["types"][0] if data.get("types") else None,
            "top_mob": mobs[0] if mobs else None}


def combine(inputs: list[dict], limit: int = 5) -> dict:
    """Junta vários Input Analysers do mesmo local: % de cada elemento e das criaturas que mais bateram.
    "(other)" só entra no total, nunca na lista de criaturas."""
    total = sum(i["total"] for i in inputs)
    types: dict[str, int] = {}
    mobs: dict[str, int] = {}
    other = 0
    for i in inputs:
        for t in i.get("types", []):
            types[t["name"]] = types.get(t["name"], 0) + t["value"]
        for s in i.get("sources", []):
            if s.get("other"):
                other += s["value"]
            else:
                k = s["name"].lower()
                mobs[k] = mobs.get(k, 0) + s["value"]

    def rows(d: dict) -> list[dict]:
        return [{"name": n, "pct": round(v * 100 / total, 1) if total else 0}
                for n, v in sorted(d.items(), key=lambda kv: -kv[1])[:limit]]
    return {"inputs": len(inputs), "total": total, "types": rows(types), "mobs": rows(mobs),
            "other_pct": round(other * 100 / total, 1) if total else 0}
