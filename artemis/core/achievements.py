"""Conquistas e sequência de dias (funções puras, sem banco).

- Conquistas são por personagem e calculadas a partir das sessões solo e party hunts dele.
- A sequência é do código de acesso: dias seguidos em que o código enviou alguma hunt ou sessão.
  Cada 30 dias seguidos rendem +7 dias de validade do código (uma vez por bloco de 30 dias).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# Brasil sem horário de verão desde 2019: o "dia" do app é o dia em Brasília, mesmo com o
# servidor (Docker) em UTC.
LOCAL_TZ = timezone(timedelta(hours=-3))

STREAK_TARGET = 30      # dias seguidos...
STREAK_REWARD_DAYS = 7  # ...rendem +7 dias de validade do código de acesso
MIN_RATE_SECONDS = 600  # conquistas "por hora" ignoram sessões com menos de 10 minutos


def local_day(iso: str) -> date:
    """Data local (Brasília) de um horário salvo em ISO (com ou sem fuso; sem fuso = UTC)."""
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ).date()


def today() -> date:
    return datetime.now(LOCAL_TZ).date()


def runs(days: set[date], frozen: set[date] = frozenset()) -> list[tuple[date, int]]:
    """Sequências de dias consecutivos: [(primeiro_dia, tamanho)], em ordem.
    0.17.0: dias `frozen` (chave vencida) não contam nem quebram a sequência — ela fica congelada."""
    out: list[list] = []  # [primeiro, tamanho, último]
    for d in sorted(days):
        if out:
            last = out[-1][2]
            gap = (last + timedelta(days=i) for i in range(1, (d - last).days))
            if all(g in frozen for g in gap):
                out[-1][1] += 1
                out[-1][2] = d
                continue
        out.append([d, 1, d])
    return [(first, size) for first, size, _ in out]


def current_streak(days: set[date], ref: date | None = None, frozen: set[date] = frozenset()) -> int:
    """Dias seguidos até hoje. Se hoje ainda não teve envio, a sequência de ontem continua valendo.
    Dia sem envio quebra a sequência; dia com a chave vencida (`frozen`) só é pulado."""
    ref = ref or today()
    d = ref if ref in days else ref - timedelta(days=1)
    n = 0
    while True:
        if d in days:
            n += 1
        elif d not in frozen:
            break
        d -= timedelta(days=1)
    return n


def streak_rewards(days: set[date], frozen: set[date] = frozenset()) -> list[str]:
    """Ids das recompensas merecidas: um por bloco completo de 30 dias em cada sequência."""
    return [f"streak{STREAK_TARGET}:{first.isoformat()}:{n}"
            for first, size in runs(days, frozen) for n in range(1, size // STREAK_TARGET + 1)]


def streak_info(days: set[date], ref: date | None = None, frozen: set[date] = frozenset()) -> dict:
    ref = ref or today()
    cur = current_streak(days, ref, frozen)
    return {
        "current": cur,
        "target": STREAK_TARGET,
        "reward_days": STREAK_REWARD_DAYS,
        "progress": cur % STREAK_TARGET,
        "next_reward_in": STREAK_TARGET - cur % STREAK_TARGET,
        "active_today": ref in days,
        # últimos 30 dias, do mais antigo para hoje
        "calendar": [(ref - timedelta(days=i)) in days for i in range(STREAK_TARGET - 1, -1, -1)],
        # 0.17.0: dias congelados (chave vencida), na mesma ordem do calendário
        "calendar_frozen": [(ref - timedelta(days=i)) in frozen and (ref - timedelta(days=i)) not in days
                            for i in range(STREAK_TARGET - 1, -1, -1)],
    }


def _per_hour(value: int, seconds: int) -> int:
    return round(value * 3600 / seconds) if seconds else 0


def _top_in_party(hunts: list[dict], name_key: str, metric: str) -> int:
    """Em quantas party hunts o personagem teve o maior valor da métrica (dano ou cura)."""
    n = 0
    for h in hunts:
        players = h.get("players") or []
        if len(players) < 2:
            continue
        best = max(players, key=lambda p: p.get(metric) or 0)
        if (best.get(metric) or 0) > 0 and " ".join(best["name"].split()).lower() == name_key:
            n += 1
    return n


# (id, emoji, título, descrição, meta)
DEFINITIONS = [
    ("first_solo", "🗡️", "Primeira caçada", "Envie sua primeira sessão no Hunt Session Stacker.", 1),
    ("first_party", "🤝", "Primeira PT", "Participe de uma party hunt enviada pelo Lootsplit.", 1),
    ("solo_50", "📚", "Veterano", "Envie 50 sessões no Stacker.", 50),
    ("party_25", "🛡️", "Parceiro fiel", "Participe de 25 party hunts.", 25),
    ("marathon", "⏱️", "Maratona", "Faça uma sessão de 3 horas ou mais.", 3 * 3600),
    ("loot_kk", "💰", "Primeiro kk", "Junte 1kk de loot numa única sessão.", 1_000_000),
    ("xp_kk", "⚡", "Máquina de XP", "Passe de 1kk de XP/h numa sessão (10 min ou mais).", 1_000_000),
    ("explorer", "🗺️", "Explorador", "Cace em 10 hunts diferentes.", 10),
    ("slayer", "🐉", "Exterminador", "Mate 10.000 criaturas somando todas as sessões.", 10_000),
    ("frontline", "⚔️", "Linha de frente", "Seja quem mais causou dano da PT em 10 party hunts.", 10),
    ("guardian", "✨", "Anjo da guarda", "Seja quem mais curou na PT em 10 party hunts.", 10),
    ("week", "🔥", "Semana perfeita", "Cace 7 dias seguidos (sessões ou party hunts).", 7),
    ("merchant", "🧺", "Mercador", "Marque um item como vendido na lista de venda.", 1),
]


def evaluate(name: str, solo: list[dict], hunts: list[dict], sold_items: int = 0,
             frozen: set[date] = frozenset()) -> list[dict]:
    """Conquistas de um personagem.

    solo: sessões do Stacker com `xp`, `duration_seconds`, `loot_value`, `place_id`, `kills` e `started_at`.
    hunts: party hunts (relatórios) em que o personagem aparece, com `players` e `started_at`.
    """
    key = " ".join(name.split()).lower()
    longs = [s for s in solo if s["duration_seconds"] >= MIN_RATE_SECONDS]
    hunt_days = {date.fromisoformat(s["started_at"][:10]) for s in solo}
    hunt_days |= {date.fromisoformat(h["started_at"][:10]) for h in hunts if h.get("started_at")}
    best_run = max((size for _, size in runs(hunt_days, frozen)), default=0)
    values = {
        "first_solo": len(solo),
        "first_party": len(hunts),
        "solo_50": len(solo),
        "party_25": len(hunts),
        "marathon": max((s["duration_seconds"] for s in solo), default=0),
        "loot_kk": max((s.get("loot_value") or 0 for s in solo), default=0),
        "xp_kk": max((_per_hour(s["xp"], s["duration_seconds"]) for s in longs), default=0),
        "explorer": len({s["place_id"] for s in solo if s.get("place_id")}),
        "slayer": sum(k["count"] for s in solo for k in s.get("kills", [])),
        "frontline": _top_in_party(hunts, key, "damage"),
        "guardian": _top_in_party(hunts, key, "healing"),
        "week": best_run,
        "merchant": sold_items,
    }
    out = []
    for aid, emoji, title, desc, target in DEFINITIONS:
        v = max(0, int(values[aid]))
        out.append({"id": aid, "emoji": emoji, "title": title, "description": desc, "value": min(v, target),
                    "target": target, "unlocked": v >= target, "pct": min(100, round(v * 100 / target))})
    return out
