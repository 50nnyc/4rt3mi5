"""Gera o relatório (dict JSON) de uma hunt. Mesmo formato no app, no servidor e no site."""
from __future__ import annotations

import hashlib

from .parser import HuntSession, parse_session
from .split import split_session


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
