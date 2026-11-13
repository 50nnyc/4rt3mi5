"""Validação de personagens na API pública do TibiaData (v4). Só usa a stdlib."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API_URL = "https://api.tibiadata.com/v4/character/{name}"


class TibiaDataError(RuntimeError):
    """Falha de rede/API (diferente de 'personagem não existe')."""


@dataclass
class CharacterInfo:
    name: str
    level: int
    vocation: str
    world: str
    comment: str = ""


def fetch_character(name: str, timeout: float = 10) -> CharacterInfo | None:
    """Retorna os dados do personagem, ou None se ele não existir."""
    name = " ".join(name.split())
    if not name:
        return None
    url = API_URL.format(name=urllib.parse.quote(name))
    req = urllib.request.Request(url, headers={"User-Agent": "4rt3mi5", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        if e.code == 502:
            # Hoje o TibiaData responde 502 quando o personagem não existe
            # (mas 502 também pode ser instabilidade momentânea).
            raise TibiaDataError("Personagem não encontrado (ou o TibiaData está instável). Confira o nome.") from e
        raise TibiaDataError(f"TibiaData respondeu HTTP {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise TibiaDataError(f"Não foi possível consultar o TibiaData: {e}") from e

    ch = (data.get("character") or {}).get("character") or {}
    if not ch.get("name"):
        return None
    return CharacterInfo(
        name=ch["name"],
        level=int(ch.get("level") or 0),
        vocation=ch.get("vocation", ""),
        world=ch.get("world", ""),
        comment=ch.get("comment", "") or "",
    )
