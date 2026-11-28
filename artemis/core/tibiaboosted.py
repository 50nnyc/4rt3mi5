"""Criatura e boss do dia (boosted) pela API pública do TibiaData (v4). Só usa a stdlib."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

CREATURES_URL = "https://api.tibiadata.com/v4/creatures"
BOSSES_URL = "https://api.tibiadata.com/v4/boostablebosses"
_NAME = re.compile(r"[A-Za-z][A-Za-z '\-.,]{1,60}")  # nome de criatura/boss: só o que o Tibia usa
_IMAGE = re.compile(r"https://static\.tibia\.com/images/(?:[A-Za-z0-9_\-]+/)*[A-Za-z0-9_\-]+\.(?:gif|png)")


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


def _image(url) -> str | None:
    s = str(url or "")
    return s if _IMAGE.fullmatch(s) else None


def parse_boosted(creatures: dict, bosses: dict) -> dict:
    """Extrai nome e imagem oficial da criatura e do boss das duas respostas. Valor fora do padrão vira None."""
    c = (creatures.get("creatures") or {}).get("boosted") or {}
    b = (bosses.get("boostable_bosses") or {}).get("boosted") or {}
    return {"creature": _clean(c.get("name")), "creature_image": _image(c.get("image_url")),
            "boss": _clean(b.get("name")), "boss_image": _image(b.get("image_url"))}


def fetch_boosted(timeout: float = 15) -> dict:
    """Criatura e boss boosted de hoje. Falha de uma das fontes não derruba a outra."""
    out = parse_boosted({}, {})
    errors = 0
    try:
        found = parse_boosted(_get_json(CREATURES_URL, timeout), {})
        out.update(creature=found["creature"], creature_image=found["creature_image"])
    except TibiaBoostedError:
        errors += 1
    try:
        found = parse_boosted({}, _get_json(BOSSES_URL, timeout))
        out.update(boss=found["boss"], boss_image=found["boss_image"])
    except TibiaBoostedError:
        errors += 1
    if errors == 2:
        raise TibiaBoostedError("Criatura e boss do dia indisponíveis agora.")
    return out
