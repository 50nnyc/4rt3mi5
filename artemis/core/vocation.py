"""0.26.1: HP, mana e capacidade calculados pela regra do jogo (só a partir do level 8).

valor(L) = valor no level 8 + ganho por level da vocação * (L - 8)
Os valores vêm de artemis/data/vocacoes.json. Abaixo do level 8 nada é calculado.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "vocacoes.json"
_dados = json.loads(DATA.read_text(encoding="utf-8"))
LEVEL_BASE = 8
BASE = _dados["valores_no_level_8"]          # hp, mana, cap
GANHO = _dados["ganho_por_level_apos_8"]     # por vocação: hp, mana, cap

# nome da vocação como aparece no highscore (Royal Paladin, Elder Druid...) -> vocação base
_PROMOVIDAS = {
    "Elite Knight": "Knight", "Royal Paladin": "Paladin", "Elder Druid": "Druid",
    "Master Sorcerer": "Sorcerer", "Exalted Monk": "Monk",
}


def vocacao_base(nome: str | None) -> str | None:
    """'Royal Paladin' -> 'Paladin'. Devolve None se não for uma das cinco vocações."""
    if not nome:
        return None
    nome = nome.strip()
    if nome in _PROMOVIDAS:
        return _PROMOVIDAS[nome]
    if nome in GANHO:
        return nome
    return None


def calcular(level: int | None, vocacao: str | None) -> dict | None:
    """HP, mana e cap calculados. None se o level for menor que 8 ou a vocação não for conhecida."""
    base = vocacao_base(vocacao)
    if base is None or level is None or level < LEVEL_BASE:
        return None
    passos = level - LEVEL_BASE
    g = GANHO[base]
    return {
        "vocacao": base,
        "hp": BASE["hp"] + g["hp"] * passos,
        "mana": BASE["mana"] + g["mana"] * passos,
        "cap": BASE["cap"] + g["cap"] * passos,
    }
