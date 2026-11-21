"""Validação de personagens na API pública do TibiaData (v5, com a v4 de reserva). Só usa a stdlib."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# 0.24.2: a v5 (lançada em 23/10/2026) usa a API de fansite do Tibia.com e seguiu respondendo
# quando o /v4/character caiu. A v4 sai do ar em 31/12/2026 e fica só de reserva até lá.
API_URL = "https://api.tibiadata.com/v5/character/{name}"
API_URL_FALLBACK = "https://api.tibiadata.com/v4/character/{name}"


class TibiaDataError(RuntimeError):
    """Falha de rede/API (diferente de 'personagem não existe')."""


@dataclass
class CharacterInfo:
    name: str
    level: int
    vocation: str
    world: str
    comment: str = ""


HIGHSCORE_URL = "https://api.tibiadata.com/v5/highscores/{world}/experience/all/{page}"


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "4rt3mi5", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def fetch_experience(name: str, world: str, level: int, timeout: float = 10) -> tuple[int, int] | None:
    """XP exata do personagem, pelo highscore de experiência do mundo (top 1000).

    O highscore é ordenado por XP, então faz busca binária nas páginas pelo level
    (umas 5 consultas). Retorna (xp, minutos desde a atualização do highscore),
    ou None se o personagem não estiver no top 1000
    ou se a API falhar.
    """
    target = name.lower()
    cache: dict[int, list[dict]] = {}
    age = [0]

    def page(n: int) -> list[dict]:
        if n not in cache:
            url = HIGHSCORE_URL.format(world=urllib.parse.quote(world), page=n)
            hs = _get_json(url, timeout).get("highscores") or {}
            age[0] = int(hs.get("highscore_age") or 0)
            cache[n] = hs.get("highscore_list") or []
        return cache[n]

    def find(n: int) -> tuple[int, int] | None:
        for row in page(n):
            if str(row.get("name", "")).lower() == target and row.get("value"):
                return int(row["value"]), age[0]
        return None

    try:
        first = page(1)
        if not first:
            return None
        lo, hi = 1, 20
        while lo <= hi:
            mid = (lo + hi) // 2
            rows = page(mid)
            if not rows:
                hi = mid - 1
                continue
            top, bottom = int(rows[0].get("level") or 0), int(rows[-1].get("level") or 0)
            if level > top:
                hi = mid - 1
            elif level < bottom:
                lo = mid + 1
            else:
                # level dentro da página (pode transbordar para as vizinhas)
                for n in (mid, mid - 1, mid + 1):
                    if 1 <= n <= 20:
                        xp = find(n)
                        if xp:
                            return xp
                return None
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _fetch_character_from(url: str, timeout: float) -> CharacterInfo | None:
    req = urllib.request.Request(url, headers={"User-Agent": "4rt3mi5", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404, 422):
            # 404 (v5) / 400 e 422 (v4) são as respostas do TibiaData para nome que não existe.
            return None
        if e.code == 502:
            # 502 é falha do TibiaData (instabilidade ou erro ao carregar esse nome),
            # não prova que o personagem não existe. Não usar "não encontrado" aqui,
            # senão o site acusa um personagem real de não existir.
            raise TibiaDataError("O TibiaData não conseguiu responder por esse nome agora (HTTP 502). Tente de novo em instantes.") from e
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


def fetch_character(name: str, timeout: float = 10) -> CharacterInfo | None:
    """Retorna os dados do personagem, ou None se ele não existir.

    Tenta a v5 primeiro; se ela falhar (rede ou erro do servidor), tenta a v4.
    "Não existe" da v5 é resposta final: não insiste na v4.
    """
    name = " ".join(name.split())
    if not name:
        return None
    quoted = urllib.parse.quote(name)
    try:
        return _fetch_character_from(API_URL.format(name=quoted), timeout)
    except TibiaDataError as first:
        try:
            return _fetch_character_from(API_URL_FALLBACK.format(name=quoted), timeout)
        except TibiaDataError:
            raise first from None
