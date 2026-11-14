"""Gera o relatório (dict JSON) de uma hunt. Mesmo formato no app, no servidor e no site."""
from __future__ import annotations

import hashlib

from .parser import HuntSession, parse_session
from .split import split_session, split_with_rules


def fingerprint(session: HuntSession) -> str:
    key = "|".join([
        session.started_at.isoformat(),
        session.ended_at.isoformat(),
        *sorted(p.name.lower() for p in session.players),
    ])
    return hashlib.sha256(key.encode()).hexdigest()


def build_report(session: HuntSession) -> dict:
    share, transfers, diff = split_session(session)
    duration = session.duration_seconds
    per_hour = round(share * 3600 / duration) if duration > 0 else 0
    return {
        "fingerprint": fingerprint(session),
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat(),
        "duration_seconds": duration,
        "session_label": session.session_label,
        "loot_type": session.loot_type,
        "loot": session.loot,
        "supplies": session.supplies,
        "balance": sum(p.balance for p in session.players),
        "players_count": len(session.players),
        "profit_each": share,
        "profit_each_per_hour": per_hour,
        "warnings": session.warnings,
        "players": [
            {
                "name": p.name,
                "is_leader": p.is_leader,
                "loot": p.loot,
                "supplies": p.supplies,
                "balance": p.balance,
                "damage": p.damage,
                "healing": p.healing,
                "diff": diff[p.name],
            }
            for p in session.players
        ],
        "transfers": [
            {"payer": t.payer, "receiver": t.receiver, "amount": t.amount, "command": t.bank_command}
            for t in transfers
        ],
    }


def report_from_text(text: str) -> dict:
    return build_report(parse_session(text))


def apply_rules(report: dict, rules: dict | None) -> dict:
    """Refaz a divisão com as regras da PT (quem fica fora / quem tem valor fixo).

    Sem regras, cada jogador recebe `profit` = profit_each. Com regras, `profit_each` passa a ser o
    valor de quem divide igual e cada jogador ganha `profit` (o que ele termina ganhando).
    """
    out = {**report, "players": [dict(p) for p in report["players"]]}
    names = {p["name"].lower(): p["name"] for p in out["players"]}
    excluded = {names[n.lower()] for n in (rules or {}).get("excluded", []) if n.lower() in names}
    fixed = {names[n.lower()]: int(v) for n, v in (rules or {}).get("fixed", {}).items()
             if n.lower() in names and names[n.lower()] not in excluded}
    if not excluded and not fixed:
        for p in out["players"]:
            p["profit"] = out["profit_each"]
        out["rules"] = None
        return out
    share, transfers, diff, target = split_with_rules({p["name"]: p["balance"] for p in out["players"]}, excluded, fixed)
    duration = out.get("duration_seconds") or 0
    out.update(profit_each=share, profit_each_per_hour=round(share * 3600 / duration) if duration > 0 else 0,
               rules={"excluded": sorted(excluded), "fixed": fixed},
               transfers=[{"payer": t.payer, "receiver": t.receiver, "amount": t.amount, "command": t.bank_command}
                          for t in transfers])
    for p in out["players"]:
        p["diff"], p["profit"] = diff[p["name"]], target[p["name"]]
    return out


def profit_of(report: dict, name: str) -> int:
    """Quanto um jogador termina ganhando na hunt (considera as regras de divisão)."""
    p = next((p for p in report["players"] if p["name"].lower() == name.lower()), None)
    return p.get("profit", report["profit_each"]) if p else report["profit_each"]


def player_view(report: dict, name: str) -> dict:
    """O que um jogador específico tem que pagar/receber nessa hunt."""
    key = name.lower()
    me = next((p for p in report["players"] if p["name"].lower() == key), None)
    if me is None:
        return {}
    pays = [t for t in report["transfers"] if t["payer"].lower() == key]
    gets = [t for t in report["transfers"] if t["receiver"].lower() == key]
    return {
        "player": me,
        "pays": pays,
        "receives": gets,
        "total_pay": sum(t["amount"] for t in pays),
        "total_receive": sum(t["amount"] for t in gets),
    }
