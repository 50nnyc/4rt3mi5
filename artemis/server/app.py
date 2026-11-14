"""Servidor do 4rt3mi5: API + site (o mesmo site roda dentro do app desktop).

Acesso:
1. O criador gera um código de acesso (máx. 30 dias) - `admin.bat create "Nome"`.
2. No primeiro uso o app pede o main character; o servidor gera um CÓDIGO DE VERIFICAÇÃO,
   a pessoa coloca no comentário do personagem no tibia.com e o servidor confere pelo TibiaData.
   A partir daí o código de acesso fica preso a esse personagem: quem copiar o código de
   outra pessoa não consegue passar da verificação.
3. Cada aparelho verificado recebe um token (X-Device-Token). Depois disso o comentário pode
   ser apagado. Outros personagens (alts / main novo) são vinculados do mesmo jeito.
4. Qualquer aparelho liberado VÊ as informações de qualquer personagem, mas só ENVIA
   (Lootsplit / Stacker) em nome de personagens vinculados ao seu código.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from artemis import APP_NAME, __version__
from artemis.core.parser import ParseError
from artemis.core.report import report_from_text
from artemis.core.session import item_key, parse_solo_session
from artemis.core.tibiadata import TibiaDataError, fetch_character

from .db import Store, name_key, normalize_key

INVALID_KEY = "Chave de acesso inválida, envie mensagem ao criador."
DEVICE_NOT_VERIFIED = "Este aparelho ainda não foi verificado. Informe o seu main character."
KEY_TAKEN = ("Este código de acesso já está vinculado a outro personagem. "
             "Informe um personagem seu que já foi verificado com este código.")
FORBIDDEN_UPLOAD = "Você não pode subir informações deste personagem."
FORBIDDEN_HINT = "Vincule este personagem ao seu código em ☰ → Meus personagens."
CHECK_COOLDOWN = 10  # segundos entre conferências do mesmo código


def _base_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()


DATA_DIR = Path(os.environ.get("ARTEMIS_DATA_DIR", _base_dir() / "data"))
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
CONFIG_PATH = DATA_DIR / "server.json"


def load_config() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {"host": "0.0.0.0", "port": 8000}
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    if not cfg.get("admin_token"):  # senha do painel de administração (só do criador)
        cfg["admin_token"] = secrets.token_urlsafe(18)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


CONFIG = load_config()
store = Store(DATA_DIR / "artemis.db")

# Tabela de itens/NPCs da TibiaWiki BR (gerada pelo importador, versionada no projeto).
WIKI_FILE = Path(__file__).resolve().parent.parent / "data" / "tibiawiki.json"
if WIKI_FILE.exists():
    _wiki = json.loads(WIKI_FILE.read_text(encoding="utf-8"))
    if _wiki.get("imported_at") != store.wiki_imported_at():
        print("Carregando itens da TibiaWiki:", store.load_wiki(_wiki))
HUNTS_FILE = WIKI_FILE.parent / "hunts.json"
if HUNTS_FILE.exists():
    _h = json.loads(HUNTS_FILE.read_text(encoding="utf-8"))
    if _h.get("imported_at") != store.meta("hunts_imported_at"):
        print("Carregando hunts da TibiaWiki:", store.load_places(_h))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async def purge_loop():
        while True:
            store.purge_expired()
            await asyncio.sleep(600)  # a cada 10 minutos apaga chaves vencidas
    task = asyncio.create_task(purge_loop())
    yield
    task.cancel()


app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,  # o app desktop carrega o site localmente e chama a API daqui
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-Access-Key", "X-Device-Token", "Content-Type", "ngrok-skip-browser-warning"],
)


# ------------------------------------------------------------------ autenticação
def require_key(x_access_key: str = Header(default="")) -> dict:
    key = store.validate_key(x_access_key)
    if key is None:
        raise HTTPException(401, {"message": INVALID_KEY, "reason": "key"})
    return key


def optional_device(access: dict = Depends(require_key), x_device_token: str = Header(default="")) -> tuple[dict, str | None]:
    return access, (x_device_token if store.device_valid(access["key"], x_device_token) else None)


def require_session(session: tuple = Depends(optional_device)) -> dict:
    access, device = session
    if device is None:
        raise HTTPException(401, {"message": DEVICE_NOT_VERIFIED, "reason": "device"})
    return access


# Cache curto das consultas ao TibiaData (só para exibição; verificação sempre consulta de novo).
_char_cache: dict[str, tuple[float, object]] = {}
_last_check: dict[str, float] = {}


def lookup_character(name: str, fresh: bool = False):
    k = name_key(name)
    hit = _char_cache.get(k)
    if hit and not fresh and time.monotonic() - hit[0] < 120:
        return hit[1]
    try:
        ch = fetch_character(name)
    except TibiaDataError as e:
        if "não encontrado" not in str(e):
            raise HTTPException(503, f"Não foi possível consultar o TibiaData agora. {e}")
        ch = None
    _char_cache[k] = (time.monotonic(), ch)
    return ch


def char_or_404(name: str, fresh: bool = False):
    ch = lookup_character(name, fresh)
    if ch is None:
        raise HTTPException(404, "Personagem não encontrado no Tibia.")
    return ch


def me_payload(access: dict) -> dict:
    current = store.validate_key(access["key"]) or access
    return {"expires_at": current["expires_at"], "main_char": current.get("main_char"),
            "chars": store.key_chars(access["key"])}


class CharIn(BaseModel):
    character: str


class CodeIn(BaseModel):
    code: str


class UploadIn(BaseModel):
    raw_text: str
    nickname: str
    place_id: int | None = None  # Stacker: em qual hunt foi a sessão


@app.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "version": __version__}


@app.post("/api/auth")
def auth(session: tuple = Depends(optional_device)):
    access, device = session
    return {"valid": True, "expires_at": access["expires_at"], "claimed": bool(access.get("main_char")),
            "device_verified": device is not None}


@app.post("/api/verify/start")
def verify_start(body: CharIn, session: tuple = Depends(optional_device)):
    access, device = session
    ch = char_or_404(body.character)
    # Contato de confiança (main forçado pelo criador): entra direto, sem código de verificação.
    if access.get("trusted") and store.is_linked(access["key"], ch.name):
        token = device or store.issue_device(access["key"], ch.name)
        return {"token": token, "character": ch.name, "me": me_payload(access), "trusted": True}
    # Código já tem dono: um aparelho novo só pode verificar com um personagem já vinculado.
    if access.get("main_char") and device is None and not store.is_linked(access["key"], ch.name):
        raise HTTPException(403, KEY_TAKEN)
    v = store.start_verification(access["key"], ch.name)
    return {"code": v["code"], "character": ch.name, "expires_at": v["expires_at"]}


@app.post("/api/verify/check")
def verify_check(body: CodeIn, session: tuple = Depends(optional_device)):
    access, device = session
    v = store.get_verification(access["key"], body.code)
    if v is None:
        raise HTTPException(410, "Código de verificação expirado. Gere outro.")
    wait = CHECK_COOLDOWN - (time.monotonic() - _last_check.get(v["code"], 0))
    if wait > 0:
        raise HTTPException(429, f"Aguarde {int(wait) + 1}s para conferir de novo.")
    _last_check[v["code"]] = time.monotonic()
    ch = char_or_404(v["name"], fresh=True)
    if v["code"] not in normalize_key(ch.comment):
        raise HTTPException(409, {
            "message": f"Ainda não encontramos o código no comentário de {ch.name}.",
            "hint": "Confira se salvou o comentário no tibia.com. O TibiaData pode levar alguns minutos para atualizar; "
                    "vamos conferir de novo sozinhos.",
        })
    token = store.complete_verification(access["key"], v["code"], ch.name, device)
    return {"token": token, "character": ch.name, "me": me_payload(access)}


@app.get("/api/me")
def me(access: dict = Depends(require_session)):
    return me_payload(access)


@app.post("/api/chars/main")
def set_main(body: CharIn, access: dict = Depends(require_session)):
    if not store.set_main(access["key"], body.character):
        raise HTTPException(404, "Esse personagem não está vinculado ao seu código.")
    return me_payload(access)


@app.delete("/api/chars/{name}")
def unlink(name: str, access: dict = Depends(require_session)):
    if not store.unlink(access["key"], name):
        raise HTTPException(400, "Não foi possível remover (o main não pode ser removido; troque o main antes).")
    return me_payload(access)


@app.get("/api/character/{name}")
def character(name: str, _: dict = Depends(require_session)):
    ch = char_or_404(name)
    return {"name": ch.name, "level": ch.level, "vocation": ch.vocation, "world": ch.world}


def require_uploader(nickname: str, access: dict) -> str:
    if not store.is_linked(access["key"], nickname):
        raise HTTPException(403, {"message": FORBIDDEN_UPLOAD, "hint": FORBIDDEN_HINT})
    return next(c["name"] for c in store.key_chars(access["key"]) if name_key(c["name"]) == name_key(nickname))


# ------------------------------------------------------------------ lootsplit
def _parse_party(raw: str) -> dict:
    try:
        return report_from_text(raw)
    except ParseError as e:
        raise HTTPException(422, str(e))


def _public(row: dict, access: dict) -> dict:
    """Esconde dados internos e diz se quem está vendo pode apagar (só quem enviou)."""
    owner = row.pop("uploader_key", None)
    for k in ("submitted_by", "fingerprint", "name_key"):
        row.pop(k, None)
    row["can_delete"] = bool(owner) and owner == access["key"]
    return row


def _delete_own(table: str, row_id: int, access: dict) -> None:
    exists, owner = store.uploader_of(table, row_id)
    if not exists:
        raise HTTPException(404, "Não encontrado (talvez já tenha sido apagado).")
    if owner != access["key"]:
        raise HTTPException(403, "Só quem enviou pode apagar.")
    (store.delete_hunt if table == "hunts" else store.delete_solo)(row_id)


@app.get("/api/hunts/{name}")
def player_hunts(name: str, access: dict = Depends(require_session)):
    return {"hunts": [_public(h, access) for h in store.hunts_for_player(name)]}


@app.delete("/api/hunt/{hunt_id}")
def delete_hunt(hunt_id: int, access: dict = Depends(require_session)):
    _delete_own("hunts", hunt_id, access)
    return {"deleted": hunt_id}


@app.post("/api/lootsplit/preview")
def lootsplit_preview(body: UploadIn, _: dict = Depends(require_session)):
    """Só calcula, sem salvar (usado quando o envio não é permitido)."""
    return _parse_party(body.raw_text)


@app.post("/api/lootsplit")
def lootsplit_upload(body: UploadIn, access: dict = Depends(require_session)):
    report = _parse_party(body.raw_text)
    uploader = require_uploader(body.nickname, access)
    hunt, created = store.add_hunt(report, body.raw_text, uploader, access["key"])
    return {"created": created, "hunt": _public(hunt, access)}


# ------------------------------------------------------------------ hunt session stacker
def _totals(sessions: list[dict]) -> dict:
    keys = ("raw_xp", "xp", "supplies", "balance", "damage", "healing", "duration_seconds")
    t = {k: sum(s[k] for s in sessions) for k in keys}
    hours = t["duration_seconds"] / 3600
    for k in ("raw_xp", "xp", "balance", "damage", "healing"):
        t[f"{k}_per_hour"] = round(t[k] / hours) if hours else 0
    t["sessions"] = len(sessions)
    return t


PERIOD_DAYS = (7, 15, 30, 90, 180, 365)  # semana, quinzena, mês, 3 meses, 6 meses, 1 ano


def _sum_counts(pairs) -> list[dict]:
    acc: dict[str, int] = {}
    for k, n in pairs:
        acc[k] = acc.get(k, 0) + n
    return [{"key": k, "count": n} for k, n in sorted(acc.items(), key=lambda kv: -kv[1])]


MIN_RECORD_SECONDS = 600  # recordes "por hora" ignoram sessões com menos de 10 minutos


def xp_to_next_level(level: int) -> int:
    """XP para ir do início do level L ao L+1 (fórmula oficial do Tibia)."""
    return 50 * level * level - 150 * level + 200


def total_xp(level: int) -> int:
    return round(50 / 3 * (level ** 3 - 6 * level ** 2 + 17 * level - 12))


def _per_hour(value: int, seconds: int) -> int:
    return round(value * 3600 / seconds) if seconds else 0


def _records(sessions: list[dict]) -> list[dict]:
    longs = [s for s in sessions if s["duration_seconds"] >= MIN_RECORD_SECONDS]
    defs = [
        ("Maior XP/h", longs, lambda s: _per_hour(s["xp"], s["duration_seconds"]), "XP/h"),
        ("Mais XP numa sessão", sessions, lambda s: s["xp"], "XP"),
        ("Maior balance/h", longs, lambda s: _per_hour(s["balance"], s["duration_seconds"]), "gp/h"),
        ("Maior lucro líquido/h", longs, lambda s: _per_hour(s["net_profit"], s["duration_seconds"]), "gp/h"),
        ("Maior loot numa sessão", sessions, lambda s: s["loot_value"], "gp"),
        ("Sessão mais longa", sessions, lambda s: s["duration_seconds"], "tempo"),
    ]
    out = []
    for label, pool, f, unit in defs:
        if pool:
            best = max(pool, key=f)
            out.append({"label": label, "value": f(best), "unit": unit, "session_id": best["id"],
                        "started_at": best["started_at"], "place": (best.get("place") or {}).get("name")})
    return out


def _forecast(name: str, sessions: list[dict]) -> dict | None:
    try:
        ch = lookup_character(name)
    except HTTPException:
        ch = None
    level = ch.level if ch else next((s["level"] for s in sessions if s.get("level")), None)
    if not level:
        return None
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    xp_week = sum(s["xp"] for s in sessions if s["started_at"] >= week_ago)
    secs = sum(s["duration_seconds"] for s in sessions)
    xp_h = _per_hour(sum(s["xp"] for s in sessions), secs)
    per_day = xp_week / 7
    one = xp_to_next_level(level)
    mark = (level // 50 + 1) * 50
    to_mark = total_xp(mark) - total_xp(level)
    return {
        "level": level, "xp_per_day": round(per_day), "xp_per_hour": xp_h,
        "next_level": level + 1, "xp_next_level": one,
        "days_next_level": round(one / per_day, 1) if per_day else None,
        "hours_next_level": round(one / xp_h, 1) if xp_h else None,
        "mark": mark, "xp_mark": to_mark,
        "days_mark": round(to_mark / per_day) if per_day else None,
    }


def _goals(name: str, sessions: list[dict]) -> list[dict]:
    now = datetime.now()
    today = now.date().isoformat()
    week_start = (now - timedelta(days=now.weekday())).date().isoformat()  # segunda-feira
    pools = {"day": [s for s in sessions if s["started_at"][:10] == today],
             "week": [s for s in sessions if s["started_at"][:10] >= week_start]}
    out = []
    for g in store.goals(name):
        done = sum(s["xp"] if g["metric"] == "xp" else s["loot_value"] for s in pools[g["period"]])
        out.append({**g, "done": done, "pct": min(100, round(done * 100 / g["target"])) if g["target"] else 0})
    order = {("day", "xp"): 0, ("day", "loot"): 1, ("week", "xp"): 2, ("week", "loot"): 3}
    return sorted(out, key=lambda g: order[(g["period"], g["metric"])])


def _sell_list(name: str, sessions: list[dict], prices: dict) -> list[dict]:
    watch = store.sell_watch(name)
    acc: dict[str, int] = {}
    for s in sessions:
        for it in s["loot"]:
            since = (watch.get(it["key"]) or {}).get("since")
            if since is None or s["started_at"] > since:
                acc[it["key"]] = acc.get(it["key"], 0) + it["count"]
    out = []
    for key, count in acc.items():
        p = prices[key]
        if p.get("source") == "moeda":
            continue  # moedas não se vendem
        target = (watch.get(key) or {}).get("target")
        out.append({"key": key, "count": count, "value": count * p["unit_price"], "target": target,
                    "reached": bool(target and count >= target),
                    "best": p["buyers"][0] if p["buyers"] else None, "since": (watch.get(key) or {}).get("since")})
    for key, w in watch.items():  # item com aviso mas zerado depois de "vendi"
        if key not in acc and w.get("target"):
            out.append({"key": key, "count": 0, "value": 0, "target": w["target"], "reached": False, "best": None,
                        "since": w.get("since")})
    return sorted(out, key=lambda it: (not it["reached"], -it["value"], -it["count"]))


@app.get("/api/stacker/{name}")
def stacker(name: str, period: int = 7, access: dict = Depends(require_session)):
    period = period if period in PERIOD_DAYS else 7
    sessions = [_public(s, access) for s in store.solo_for_player(name)]
    kills, loot = store.solo_details([s["id"] for s in sessions])
    keys = {store.resolve_item(k) for rows in loot.values() for k, _ in rows}
    keys |= set(store.sell_watch(name))
    prices = store.price_info(list(keys), access["key"])
    places = {p["id"]: p for p in (store.place(pid) for pid in {s.get("place_id") for s in sessions} if pid) if p}
    for s in sessions:
        s.pop("raw_text", None)
        pl = places.get(s.get("place_id"))
        s["place"] = {"id": pl["id"], "name": pl["name"]} if pl else None
        s["kills"] = [{"key": c, "count": n} for c, n in kills[s["id"]]]
        items = _sum_counts((store.resolve_item(k), n) for k, n in loot[s["id"]])
        for it in items:
            it["value"] = it["count"] * prices[it["key"]]["unit_price"]
        s["loot"] = sorted(items, key=lambda it: (-it["value"], -it["count"]))
        s["loot_value"] = sum(it["value"] for it in items)
        s["net_profit"] = s["loot_value"] - s["supplies"]  # lucro líquido real: loot pelos preços de NPC - supplies

    cutoff = (datetime.now() - timedelta(days=period)).isoformat()
    in_period = [s for s in sessions if s["started_at"] >= cutoff]
    p_items = _sum_counts((it["key"], it["count"]) for s in in_period for it in s["loot"])
    for it in p_items:
        it["value"] = it["count"] * prices[it["key"]]["unit_price"]
    p_items.sort(key=lambda it: (-it["value"], -it["count"]))
    totals = _totals(in_period)
    loot_value = sum(it["value"] for it in p_items)
    period_data = {
        "days": period,
        "totals": totals,
        "items": p_items,
        "kills": _sum_counts((k["key"], k["count"]) for s in in_period for k in s["kills"]),
        "loot_value": loot_value,
        "net_profit": loot_value - totals["supplies"],
        "net_profit_per_hour": _per_hour(loot_value - totals["supplies"], totals["duration_seconds"]),
        "unpriced": sum(1 for it in p_items if not prices[it["key"]]["unit_price"]),
    }
    day = sessions[0]["started_at"][:10] if sessions else None
    sell = _sell_list(name, sessions, prices)
    return {
        "is_owner": store.is_linked(access["key"], name),
        "day": day,
        "day_totals": _totals([s for s in sessions if s["started_at"][:10] == day]),
        "lifetime": _totals(sessions),
        "sessions": sessions,
        "period": period_data,
        "prices": prices,
        "goals": _goals(name, sessions),
        "forecast": _forecast(name, sessions),
        "records": _records(sessions),
        "sell": sell,
        "alerts": [it for it in sell if it["reached"]],
    }


def require_owner(name: str, access: dict) -> None:
    if not store.is_linked(access["key"], name):
        raise HTTPException(403, "Só o dono do personagem pode alterar isso.")


class GoalIn(BaseModel):
    period: str
    metric: str
    target: int | None = None


@app.post("/api/goals/{name}")
def set_goal(name: str, body: GoalIn, access: dict = Depends(require_session)):
    require_owner(name, access)
    if body.period not in ("day", "week") or body.metric not in ("xp", "loot"):
        raise HTTPException(422, "Meta inválida.")
    store.set_goal(name, body.period, body.metric, body.target if body.target and body.target > 0 else None)
    return {"goals": store.goals(name)}


class SellIn(BaseModel):
    item: str
    target: int | None = None


@app.post("/api/sell/{name}")
def set_sell_target(name: str, body: SellIn, access: dict = Depends(require_session)):
    """Avisar quando juntar `target` unidades do item."""
    require_owner(name, access)
    store.set_sell(name, store.resolve_item(item_key(body.item)), body.target if body.target and body.target > 0 else None)
    return {"ok": True}


@app.post("/api/sell/{name}/sold")
def mark_sold(name: str, body: SellIn, access: dict = Depends(require_session)):
    """'Vendi': zera a contagem do item (o histórico no banco continua)."""
    require_owner(name, access)
    store.set_sell(name, store.resolve_item(item_key(body.item)), sold_at=datetime.now().isoformat(timespec="seconds"),
                   update_target=False)
    return {"ok": True}


# ------------------------------------------------------------------ hunts (locais, ranking, comparação)
class PlaceIn(BaseModel):
    name: str
    city: str | None = None


class PlaceSet(BaseModel):
    place_id: int | None = None


@app.get("/api/places")
def list_places(_: dict = Depends(require_session)):
    return store.places()


@app.post("/api/places")
def create_place(body: PlaceIn, access: dict = Depends(require_session)):
    name = " ".join(body.name.split())
    if not 3 <= len(name) <= 60:
        raise HTTPException(422, "Nome da hunt deve ter de 3 a 60 caracteres.")
    return store.create_place(name, (body.city or "").strip() or None, access["key"])


@app.post("/api/stacker/session/{session_id}/place")
def set_place(session_id: int, body: PlaceSet, access: dict = Depends(require_session)):
    exists, owner = store.uploader_of("solo_sessions", session_id)
    if not exists:
        raise HTTPException(404, "Sessão não encontrada.")
    if owner != access["key"]:
        raise HTTPException(403, "Só quem enviou pode alterar a hunt da sessão.")
    if body.place_id is not None and store.place(body.place_id) is None:
        raise HTTPException(404, "Hunt não encontrada.")
    store.set_session_place(session_id, body.place_id)
    return {"ok": True}


@app.get("/api/places/ranking")
def places_ranking(sort: str = "xp", min_level: int | None = None, max_level: int | None = None,
                   _: dict = Depends(require_session)):
    rows = store.place_stats(min_level, max_level)
    key = "gold_per_hour" if sort == "gold" else "xp_per_hour"
    return {"sort": sort, "rows": sorted(rows, key=lambda r: -r[key])}


@app.get("/api/places/compare")
def places_compare(ids: str, nick: str = "", access: dict = Depends(require_session)):
    place_ids = [int(i) for i in ids.split(",") if i.strip().isdigit()][:3]
    general = {r["id"]: r for r in store.place_stats(place_ids=place_ids)}
    mine = {r["id"]: r for r in store.place_stats(place_ids=place_ids, name=nick)} if nick else {}
    out = []
    for pid in place_ids:
        p = store.place(pid)
        if not p:
            continue
        kills, loot = store.place_top(pid)
        loot_keys = [store.resolve_item(k) for k, _ in loot]
        prices = store.price_info(loot_keys, access["key"])
        items = _sum_counts((store.resolve_item(k), n) for k, n in loot)
        for it in items:
            it["value"] = it["count"] * prices[it["key"]]["unit_price"]
            it["name"] = prices[it["key"]]["name"]
        out.append({"place": p, "stats": general.get(pid), "mine": mine.get(pid),
                    "top_kills": [{"key": k, "count": n} for k, n in kills],
                    "top_items": sorted((it for it in items if it["value"] > 0), key=lambda it: -it["value"])[:5]})
    return out


class PriceIn(BaseModel):
    item: str
    price: int | None = None


@app.post("/api/items/price")
def set_item_price(body: PriceIn, access: dict = Depends(require_session)):
    """Preço informado pelo usuário (só para itens que nenhum NPC compra) -> entra na média de todos."""
    key = store.resolve_item(item_key(body.item))
    info = store.price_info([key], access["key"])[key]
    if info["npc_price"]:
        raise HTTPException(400, "Esse item já tem preço de NPC.")
    if body.price is not None and not 0 <= body.price <= 10_000_000_000:
        raise HTTPException(422, "Preço inválido.")
    store.set_user_price(key, access["key"], body.price)
    return store.price_info([key], access["key"])[key]


@app.post("/api/stacker")
def stacker_upload(body: UploadIn, access: dict = Depends(require_session)):
    try:
        session = parse_solo_session(body.raw_text)
    except ParseError as e:
        raise HTTPException(422, str(e))
    name = require_uploader(body.nickname, access)
    if body.place_id is not None and store.place(body.place_id) is None:
        raise HTTPException(404, "Hunt não encontrada.")
    try:  # level do personagem no momento do envio (para o level médio das hunts)
        ch = lookup_character(name)
        level = ch.level if ch else None
    except HTTPException:
        level = None
    row, created = store.add_solo(name, session.fingerprint(name), session.to_dict(), access["key"], body.raw_text,
                                  body.place_id, level)
    row.pop("raw_text", None)
    return {"created": created, "session": _public(row, access)}


@app.delete("/api/stacker/session/{session_id}")
def delete_solo(session_id: int, access: dict = Depends(require_session)):
    _delete_own("solo_sessions", session_id, access)
    return {"deleted": session_id}


# ------------------------------------------------------------------ administração (só o criador)
ADMIN_REMOTE_BLOCKED = "O painel de administração só funciona no próprio PC do servidor (http://localhost:8000/admin)."
_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded", "ngrok-trace-id")


def require_admin(request: Request, x_admin_token: str = Header(default="")) -> None:
    # Tudo que chega pelo túnel (ngrok) traz cabeçalhos de proxy: o painel não aceita acesso pela internet.
    if any(h in request.headers for h in _PROXY_HEADERS):
        raise HTTPException(403, ADMIN_REMOTE_BLOCKED)
    if not secrets.compare_digest(x_admin_token, CONFIG["admin_token"]):
        raise HTTPException(401, "Senha de administrador inválida.")


class NewKeyIn(BaseModel):
    label: str = ""
    days: int = 30


class DaysIn(BaseModel):
    days: int


def _admin_key(key: str) -> dict:
    k = store.validate_key(key)
    if k is None:
        raise HTTPException(404, "Código não encontrado (ou já vencido e apagado).")
    return k


@app.get("/api/admin/keys", dependencies=[Depends(require_admin)])
def admin_keys():
    store.purge_expired()
    return store.keys_overview()


@app.post("/api/admin/keys", dependencies=[Depends(require_admin)])
def admin_create(body: NewKeyIn):
    try:
        return store.create_key(body.days, body.label.strip())
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/admin/keys/{key}/renew", dependencies=[Depends(require_admin)])
def admin_renew(key: str, body: DaysIn):
    _admin_key(key)
    try:
        return store.renew_key(key, body.days)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/admin/keys/{key}/trust", dependencies=[Depends(require_admin)])
def admin_force_main(key: str, body: CharIn):
    _admin_key(key)
    ch = char_or_404(body.character, fresh=True)
    store.force_main(key, ch.name)
    return {"key": normalize_key(key), "main_char": ch.name, "trusted": True}


@app.post("/api/admin/keys/{key}/untrust", dependencies=[Depends(require_admin)])
def admin_untrust(key: str):
    _admin_key(key)
    store.set_trusted(key, False)
    return {"trusted": False}


@app.post("/api/admin/keys/{key}/reset", dependencies=[Depends(require_admin)])
def admin_reset(key: str):
    _admin_key(key)
    store.reset_key(key)
    return {"reset": True}


@app.delete("/api/admin/keys/{key}", dependencies=[Depends(require_admin)])
def admin_revoke(key: str):
    if not store.revoke_key(key):
        raise HTTPException(404, "Código não encontrado.")
    return {"deleted": True}


@app.get("/admin", include_in_schema=False)
def admin_page(request: Request):
    if any(h in request.headers for h in _PROXY_HEADERS):
        raise HTTPException(404)
    return FileResponse(WEB_DIR / "admin.html", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ site
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})
