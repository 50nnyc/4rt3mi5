"""Criatura e boss do dia (boosted) pela API pública do TibiaData (v4). Só usa a stdlib."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

CREATURES_URL = "https://api.tibiadata.com/v4/creatures"
BOSSES_URL = "https://api.tibiadata.com/v4/boostablebosses"
_NAME = re.compile(r"[A-Za-z][A-Za-z '\-.,]{1,60}")  # nome de criatura/boss: só o que o Tibia usa


class TibiaBoostedError(RuntimeError):
    """Fonte fora do ar ou resposta inesperada."""


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "4rt3mi5", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        raise TibiaBoostedError(f"Não foi possível consultar a criatura do dia: {e}") from e


def _clean(name) -> str | None:
    s = " ".join(str(name or "").split())
    return s if _NAME.fullmatch(s) else None


def parse_boosted(creatures: dict, bosses: dict) -> dict:
    """Extrai {"creature": nome|None, "boss": nome|None} das duas respostas. Nome fora do padrão vira None."""
    c = ((creatures.get("creatures") or {}).get("boosted") or {}).get("name")
    b = ((bosses.get("boostable_bosses") or {}).get("boosted") or {}).get("name")
    return {"creature": _clean(c), "boss": _clean(b)}


def fetch_boosted(timeout: float = 15) -> dict:
    """Criatura e boss boosted de hoje. Falha de uma das fontes não derruba a outra."""
    out = {"creature": None, "boss": None}
    errors = 0
    try:
        out["creature"] = parse_boosted(_get_json(CREATURES_URL, timeout), {})["creature"]
    except TibiaBoostedError:
        errors += 1
    try:
        out["boss"] = parse_boosted({}, _get_json(BOSSES_URL, timeout))["boss"]
    except TibiaBoostedError:
        errors += 1
    if errors == 2:
        raise TibiaBoostedError("Criatura e boss do dia indisponíveis agora.")
    return out
