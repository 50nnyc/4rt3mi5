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
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import re
from collections import deque
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from artemis import APP_NAME, __version__
from artemis.core import achievements as ach
from artemis.core import bosses as boss_core
from artemis.core import captcha
from artemis.core import rotations as rot
from artemis.core import damage as damage_core
from artemis.core import party as party_core
from artemis.core.parser import ParseError
from artemis.core.report import profit_of, report_from_text
from artemis.core.session import item_key, parse_solo_session
from artemis.core.levels import level_for_xp, xp_at, xp_to_next_level
from artemis.core import tibiacal, tibianews
from artemis.core import translate as translate_core
from artemis.core import rankscan
from artemis.core import vocation as vocation_core
from artemis.core.tibiadata import (HIGHSCORE_CATEGORIES, TibiaDataError, fetch_character, fetch_experience,
                                    fetch_highscore_page, fetch_worlds_list)

from . import mailer
from .db import BASE_PLAYER_TYPES, Store, extra_player_types, name_key, normalize_key, session_content_hash

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
    changed = False
    if not cfg.get("admin_token"):  # senha do painel de administração (só do criador)
        cfg["admin_token"] = secrets.token_urlsafe(18)
        changed = True
    # 0.17.0: "pepper" das senhas das contas. Fica FORA do banco: quem copiar só o banco (ou um backup dele) não
    # consegue testar senha nenhuma. Se ARTEMIS_PW_PEPPER estiver definido no ambiente (.env), ele vale.
    if not cfg.get("pw_pepper"):
        cfg["pw_pepper"] = secrets.token_hex(32)
        changed = True
    if changed:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


CONFIG = load_config()
store = Store(DATA_DIR / "artemis.db")
store.pepper = os.environ.get("ARTEMIS_PW_PEPPER") or CONFIG["pw_pepper"]

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


BACKUP_DIR = DATA_DIR / "backups"
BACKUP_KEEP = int(os.environ.get("ARTEMIS_BACKUP_KEEP", "14"))  # backups diários guardados (os mais velhos saem)


def daily_backup(now: datetime | None = None) -> Path | None:
    """Um backup por dia em data/backups/artemis-AAAAMMDD.db; mantém só os BACKUP_KEEP mais novos."""
    now = now or datetime.now()
    path = BACKUP_DIR / f"artemis-{now:%Y%m%d}.db"
    if path.exists():
        return None
    store.backup_to(path)
    store.set_meta("last_backup", now.isoformat(timespec="seconds"))
    for old in sorted(BACKUP_DIR.glob("artemis-*.db"), reverse=True)[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)
    return path


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async def purge_loop():
        while True:
            store.purge_expired()
            await asyncio.sleep(600)  # a cada 10 minutos apaga chaves vencidas

    async def backup_loop():
        while True:
            try:
                await asyncio.to_thread(daily_backup)
            except Exception as e:  # backup nunca derruba o servidor
                print("Falha no backup automático:", e)
            await asyncio.sleep(3600)  # confere a cada hora se o backup do dia já foi feito
    async def news_loop():
        await asyncio.sleep(5)
        while True:
            try:
                await asyncio.to_thread(sync_tibia_news)
            except Exception as e:  # notícia nunca derruba o servidor
                print("Falha ao atualizar as notícias do Tibia:", e)
            await asyncio.sleep(NEWS_SYNC_EVERY)
    async def xp_loop():
        # 0.25.1: snapshot de XP de todos os cadastrados, todo dia às 09h (Brasília)
        while True:
            await asyncio.sleep(_seconds_until_next_update())
            try:
                n = await asyncio.to_thread(_xp_snapshot_all)
                print(f"XP do TibiaData: {n} personagens guardados")
            except Exception as e:  # ranking nunca derruba o servidor
                print("Falha no snapshot de XP:", e)
    tasks = [asyncio.create_task(purge_loop()), asyncio.create_task(backup_loop()),
             asyncio.create_task(xp_loop())]
    if NEWS_SYNC_EVERY > 0:
        tasks.append(asyncio.create_task(news_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)  # sem documentação pública da API


@app.exception_handler(RequestValidationError)
async def invalid_input(_request: Request, exc: RequestValidationError):
    """Dados fora do formato/tamanho permitido: mensagem curta, sem ecoar o que foi enviado."""
    fields = sorted({str(e.get("loc", ["", "?"])[-1]) for e in exc.errors()})
    return JSONResponse(status_code=422, content={"detail": {"message": "Dados inválidos ou grandes demais: " + ", ".join(fields),
                                                             "reason": "invalid"}})


# ------------------------------------------------------------------ limite de requisições (anti-abuso)
MAX_BODY = 512 * 1024                          # nenhum envio legítimo passa disso
RATE_RULES = {"read": (240, 60), "write": (40, 60), "upload": (30, 600),   # (máx., janela em s) por IP
              "img": (600, 60), "track": (120, 60)}                         # imagens (/img/wiki/...) e uso das telas
UPLOAD_PATHS = {"/api/lootsplit", "/api/stacker", "/api/places", "/api/lootsplit/preview", "/api/public/lootsplit",
                "/api/bosses/session", "/api/bosses/lootsplit", "/api/store/free",
                "/api/account/register", "/api/recovery", "/api/recovery/login", "/api/contact",
                "/api/link/info", "/api/link/send", "/api/links"}  # 0.23.0: link de envio
SLOW_DOWN = "Muitas requisições em pouco tempo. Aguarde um pouco e tente de novo."
_hits: dict[tuple[str, str], deque] = {}


def _rate_bucket(request: Request) -> str | None:
    path = request.url.path
    if not path.startswith("/api/") or path == "/api/health":
        return None
    if request.method == "POST" and path in UPLOAD_PATHS:
        return "upload"
    if path == "/api/track":
        return "track"
    return "write" if request.method in ("POST", "DELETE", "PUT", "PATCH") else "read"


def _rate_limited(ip: str, bucket: str) -> bool:
    limit, window = RATE_RULES[bucket]
    now = time.monotonic()
    q = _hits.setdefault((ip, bucket), deque())
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    if len(_hits) > 20000:  # memória limitada: descarta os mais antigos
        for k in list(_hits)[:5000]:
            _hits.pop(k, None)
    return False


@app.middleware("http")
async def abuse_guard(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > MAX_BODY):
        return JSONResponse(status_code=413, content={"detail": {"message": "Envio grande demais.", "reason": "size"}})
    if request.method in ("POST", "PUT", "PATCH") and not length and request.url.path.startswith("/api/"):
        body = await request.body()  # sem Content-Length (chunked): confere o tamanho real
        if len(body) > MAX_BODY:
            return JSONResponse(status_code=413, content={"detail": {"message": "Envio grande demais.", "reason": "size"}})
    bucket = _rate_bucket(request)
    if bucket and _rate_limited(client_ip(request), bucket):
        return JSONResponse(status_code=429, content={"detail": {"message": SLOW_DOWN, "reason": "rate"}},
                            headers={"Retry-After": "60"})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.headers.get("x-forwarded-proto") == "https":  # pelo túnel: força HTTPS por 1 ano
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"  # respostas com dados de conta não ficam em cache
    return resp


# ------------------------------------------------------------------ 0.22.3: conta de visitante (só visualização)
# A conta de visitante (ex.: a da CipSoft) abre todas as telas, mas não envia, salva nem altera nada no banco.
# O bloqueio é no servidor: qualquer POST/DELETE com a chave (ou a sessão de conta) do visitante é recusado,
# menos entrar/sair, as contas que só calculam (sem salvar) e o formulário de contato.
GUEST_READONLY = "Conta de visitante: só visualização. Nada pode ser enviado, salvo ou alterado."
GUEST_ALLOWED = {"/api/auth", "/api/account/login", "/api/account/resume", "/api/account/logout",
                 "/api/lootsplit/preview", "/api/public/lootsplit", "/api/contact"}


def _is_guest(request: Request) -> bool:
    key = request.headers.get("x-access-key", "")
    if key and store.key_readonly(key):
        return True
    return store.account_token_readonly(request.headers.get("x-account-token", ""))


@app.middleware("http")
async def guest_readonly(request: Request, call_next):
    path = request.url.path
    if (request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/") and path not in GUEST_ALLOWED
            and await asyncio.to_thread(_is_guest, request)):
        if path == "/api/track":  # nem os contadores de uso das telas
            return JSONResponse({"ok": True})
        return JSONResponse(status_code=403, content={"detail": {"message": GUEST_READONLY, "reason": "readonly"}})
    return await call_next(request)


# ------------------------------------------------------------------ 0.23.0: app para Windows descontinuado
# O app de Windows abre a tela num endereço local (127.0.0.1/localhost) e chama a API do servidor de outro endereço.
# Essas chamadas agora recebem 410 com a mensagem (o app mostra no login). O site no próprio PC (mesma origem) continua.
# Fica ANTES do CORS no arquivo: assim o CORS embrulha a resposta e o app consegue ler a mensagem.
_DESKTOP_ORIGIN = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")


def _from_desktop_app(request: Request) -> bool:
    origin = request.headers.get("origin", "")
    return bool(_DESKTOP_ORIGIN.match(origin)) and origin.split("://", 1)[1] != request.headers.get("host", "")


@app.middleware("http")
async def desktop_discontinued(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path != "/api/health" and request.method != "OPTIONS" and _from_desktop_app(request):
        return JSONResponse(status_code=410, content={"detail": {"message": DESKTOP_GONE, "reason": "desktop"}})
    return await call_next(request)


# ------------------------------------------------------------------ 0.21.0: visitas ao site (só contadores)
# Conta quem abre a página no navegador (o app de Windows abre a tela dele mesmo e não entra aqui).
# Visitante único: uma marca embaralhada (IP + navegador + segredo do servidor) que vale só no dia/mês
# e é apagada quando o período acaba. O IP nunca é guardado.
_BOT_UA = re.compile(r"bot|crawl|spider|slurp|curl|wget|python|httpx|go-http|java/|okhttp|uptime|monitor|"
                     r"headless|lighthouse|preview|facebookexternalhit|whatsapp|telegram|discord|scan", re.I)


def _visit_mark(period: str, ip: str, ua: str) -> str:
    return hmac.new(store.visit_salt().encode(), f"{period}|{ip}|{ua}".encode("utf-8", "replace"), hashlib.sha256).hexdigest()[:32]


def _count_visit(ip: str, ua: str) -> None:
    try:
        day = ach.local_day(datetime.now(timezone.utc).isoformat()).isoformat()
        store.count_visit(day, _visit_mark(day, ip, ua), _visit_mark(day[:7], ip, ua))
    except Exception as e:  # contar visita nunca atrapalha a página
        print("Falha ao contar visita:", type(e).__name__)


@app.middleware("http")
async def visit_counter(request: Request, call_next):
    resp = await call_next(request)
    if (request.method == "GET" and request.url.path == "/" and resp.status_code == 200
            and not request.headers.get("sec-purpose", "").startswith("prefetch")):
        ua = request.headers.get("user-agent", "")
        if ua and not _BOT_UA.search(ua):
            await asyncio.to_thread(_count_visit, client_ip(request), ua[:300])
    return resp


# ------------------------------------------------------------------ limite contra força bruta
FAIL_LIMIT = 10          # tentativas erradas de código/senha...
FAIL_WINDOW = 600        # ...em 10 minutos bloqueiam o IP por esse tempo
TOO_MANY = "Muitas tentativas com código inválido. Aguarde alguns minutos e tente de novo."
_fails: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    # O ngrok ACRESCENTA o IP real no fim do X-Forwarded-For; o começo pode ter sido inventado por quem chama
    # (e serviria para fugir do bloqueio contra força bruta). Por isso vale o último.
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[-1].strip() if fwd else (request.client.host if request.client else "?")


def _check_blocked(ip: str) -> None:
    now = time.monotonic()
    recent = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
    _fails[ip] = recent
    if len(recent) >= FAIL_LIMIT:
        raise HTTPException(429, {"message": TOO_MANY, "reason": "rate"})


def _record_fail(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.monotonic())
    if len(_fails) > 5000:  # não deixa a tabela crescer sem limite
        for k in list(_fails)[:1000]:
            _fails.pop(k, None)
app.add_middleware(
    CORSMiddleware,  # o app desktop carrega o site localmente (127.0.0.1) e chama a API daqui
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",  # outros sites não podem usar a API pelo navegador
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-Access-Key", "X-Device-Token", "X-Account-Token", "Content-Type", "ngrok-skip-browser-warning"],
)


# ------------------------------------------------------------------ autenticação
def require_key(request: Request, x_access_key: str = Header(default="")) -> dict:
    ip = client_ip(request)
    _check_blocked(ip)
    key = store.validate_key(x_access_key)
    if key is None:
        _record_fail(ip)
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


_VALID_NAME = re.compile(r"[A-Za-zÀ-ÿ' .-]{2,40}")


def lookup_character(name: str, fresh: bool = False):
    if not _VALID_NAME.fullmatch(name or ""):  # nome impossível no Tibia: nem consulta o TibiaData
        return None
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
    if ch is not None:  # guarda vocação/level para colorir por vocação sem consultar de novo
        store.save_char_info(ch.name, ch.vocation, ch.level)
    return ch


def char_or_404(name: str, fresh: bool = False):
    ch = lookup_character(name, fresh)
    if ch is None:
        raise HTTPException(404, "Personagem não encontrado no Tibia.")
    return ch


def user_expires(access: dict) -> str | None:
    """Vencimento mostrado para a pessoa. Código vitalício ("amigo do adm"): nenhum, e nada diz que é vitalício."""
    return None if access.get("lifetime") else access.get("expires_at")


def me_payload(access: dict) -> dict:
    current = store.validate_key(access["key"]) or access
    return {"expires_at": user_expires(current), "main_char": current.get("main_char"),
            "chars": store.key_chars(access["key"]), "player_type": store.player_type(access["key"]),
            "player_type_chosen": store.player_type_chosen(access["key"]),
            "player_types": list(_open_player_types()), "player_type_info": _extra_type_info(),
            "hardcore_types": list(_hardcore_types()), "readonly": bool(current.get("readonly")),
            # 0.23.0: o que chegou pelo link de envio nas últimas 24 h e tentativas de vincular os seus personagens
            # em outra conta (últimos 30 dias)
            "link_sends": store.sends_by_others(access["key"], datetime.now(timezone.utc) - timedelta(days=1)),
            "char_claims": store.char_claims_since([c["name"] for c in store.key_chars(access["key"])],
                                                   datetime.now(timezone.utc) - timedelta(days=30))}


NAME_MAX = 40          # nomes do Tibia têm até 29 caracteres
RAW_MAX = 200_000      # texto colado do analyser (uma sessão longa tem poucos KB)
Name = Annotated[str, Field(min_length=1, max_length=NAME_MAX)]


class CharIn(BaseModel):
    character: Name


class CodeIn(BaseModel):
    code: Annotated[str, Field(max_length=40)]


class UploadIn(BaseModel):
    raw_text: Annotated[str, Field(min_length=1, max_length=RAW_MAX)]
    nickname: Name
    place_id: int | None = Field(default=None, ge=1)  # Stacker: em qual hunt foi a sessão
    for_char: Name | None = None  # 0.23.0: jogador autorizado enviando pelo dono deste personagem


CHANGELOG_FILE = Path(__file__).resolve().parent.parent / "data" / "changelog.json"


@app.get("/api/changelog")
def changelog():
    """Novidades de cada versão (aba 📰 Novidades). Público: não tem dado de ninguém."""
    try:
        data = json.loads(CHANGELOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"releases": []}
    return {"version": __version__, "releases": data.get("releases", [])}


# ------------------------------------------------------------------ 📰 notícias do Tibia (0.22.0)
# Latest News e News Archive do tibia.com, pela TibiaData. O índice inteiro fica no banco; o texto de cada
# notícia é baixado aos poucos (e na hora, quando alguém abre). Fonte fora do ar: tudo sai do que já está guardado.
NEWS_SYNC_EVERY = int(os.environ.get("ARTEMIS_NEWS_SYNC", "1800"))   # segundos (0 desliga; os testes desligam)
NEWS_FETCH_PER_SYNC = 40          # textos novos baixados por rodada (não sobrecarrega a fonte)
NEWS_ON_DEMAND = (60, 60)         # textos baixados na hora (todas as pessoas juntas) por minuto
NEWS_LATEST_DAYS = 90             # como o Latest News do tibia.com
_news_fetches: deque = deque()
_news_lock = threading.Lock()


def _news_budget() -> bool:
    limit, window = NEWS_ON_DEMAND
    now = time.monotonic()
    while _news_fetches and now - _news_fetches[0] > window:
        _news_fetches.popleft()
    if len(_news_fetches) >= limit:
        return False
    _news_fetches.append(now)
    return True


def _news_ok(ok: bool) -> None:
    store.set_meta("tibia_news_source", "ok" if ok else "offline")
    if ok:
        store.set_meta("tibia_news_ok_at", datetime.now().astimezone().isoformat(timespec="seconds"))


def sync_tibia_news() -> dict:
    """Atualiza a lista (tudo na primeira vez; depois só os últimos 30 dias) e baixa alguns textos que faltam."""
    if not _news_lock.acquire(blocking=False):
        return {"skipped": True}
    try:
        first = store.tibia_news_count() == 0
        try:
            new = store.save_tibia_news_list(tibianews.fetch_archive(9999 if first else 30))
        except tibianews.TibiaNewsError:
            _news_ok(False)
            return {"ok": False}
        fetched = 0
        for nid in store.tibia_news_missing(NEWS_FETCH_PER_SYNC):
            try:
                item = tibianews.fetch_item(nid)
            except tibianews.TibiaNewsError:
                break
            if item:
                store.save_tibia_news_content(nid, item["title"], item["content_html"], item["content_text"])
                fetched += 1
        _news_ok(True)
        return {"ok": True, "new": new, "fetched": fetched}
    finally:
        _news_lock.release()


NEWS_PER_REQUEST = 10             # textos que faltam, baixados juntos (em paralelo) numa mesma abertura de tela


def _news_with_content(rows: list[dict]) -> list[dict]:
    """Baixa na hora o texto que ainda falta (em paralelo, dentro do limite). Sem fonte, devolve o que tiver."""
    from concurrent.futures import ThreadPoolExecutor
    missing = [r for r in rows if r.get("content_html") is None][:NEWS_PER_REQUEST]
    missing = [r for r in missing if _news_budget()]
    if not missing:
        return rows

    def get(r: dict):
        try:
            return r, tibianews.fetch_item(r["id"], timeout=8)
        except tibianews.TibiaNewsError:
            return r, False
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(get, missing))
    if any(item is False for _, item in results):
        _news_ok(False)
    for r, item in results:
        if item:
            store.save_tibia_news_content(r["id"], item["title"], item["content_html"], item["content_text"])
            r.update(title=item["title"] or r["title"], content_html=item["content_html"])
    return rows


def _news_out(r: dict) -> dict:
    return {"id": r["id"], "date": r["date"], "title": r["title"], "category": r["category"], "type": r["type"],
            "url": tibianews.TIBIA_NEWS_URL.format(id=r["id"]), "content_html": r.get("content_html"),
            "saved": r.get("content_html") is not None if "content_html" in r else bool(r.get("saved")),
            "translated": bool(r.get("translated"))}


# ------------------------------------------------------------------ 🌐 tradução automática (0.22.2)
# Notícias, News Archive e calendário vêm em inglês; o resto do app tem tradução própria (i18n-*.json).
TRANSLATE_KEY = os.environ.get("ARTEMIS_DEEPL_KEY", "").strip()
TRANSLATE_MONTHLY = int(os.environ.get("ARTEMIS_TRANSLATE_MONTHLY", "995000"))  # caracteres/mês (o grátis do DeepL é 1 milhão)
TRANSLATE_MARGIN = 5000            # folga em relação ao limite que o próprio DeepL informa
TRANSLATE_USAGE_EVERY = 3600       # segundos entre consultas do uso real no DeepL
_tr_usage: dict = {"at": -1e9, "used": 0, "limit": 0}


def _deepl_room(chars: int) -> bool:
    """Confere no DeepL (no máximo 1x por hora, somando o que foi gasto desde então) se ainda cabe."""
    now = time.monotonic()
    if now - _tr_usage["at"] > TRANSLATE_USAGE_EVERY:
        try:
            used, limit = translate_core.usage(TRANSLATE_KEY)
            _tr_usage.update(at=now, used=used, limit=limit)
        except translate_core.TranslateError as e:
            print(e)
            _tr_usage["at"] = now  # tenta de novo daqui a 1 h; enquanto isso vale o contador nosso
    if not _tr_usage["limit"]:
        return True
    return _tr_usage["used"] + chars <= _tr_usage["limit"] - TRANSLATE_MARGIN


def _lang(lang: str) -> str | None:
    """Idioma do app que tem tradução automática; None = mostrar o original (inglês)."""
    return lang if lang in translate_core.TARGETS else None


def _translate(texts: list[str], lang: str | None, html: bool = False) -> tuple[list[str], bool]:
    """Traduz usando o que já está guardado; o que falta vai ao DeepL (dentro da cota do mês).
    Retorna (textos, algum foi traduzido?). Sem chave, sem cota ou com o serviço fora: devolve o original."""
    if not lang or not texts:
        return texts, False
    hashes = [store.text_hash(t, html) for t in texts]
    known = store.translations(sorted(set(hashes)), lang)
    missing = {h: t for h, t in zip(hashes, texts) if h not in known and t.strip()}
    if missing and TRANSLATE_KEY:
        month_key = "translate_chars:" + datetime.now().strftime("%Y-%m")
        used = int(store.meta(month_key) or 0)
        chars = sum(len(t) for t in missing.values())
        if used + chars <= TRANSLATE_MONTHLY and _deepl_room(chars):
            try:
                got = translate_core.translate(TRANSLATE_KEY, list(missing.values()), lang, html=html)
            except translate_core.TranslateError as e:
                print("Tradução indisponível:", e)
            else:
                if html:  # o que volta do serviço passa de novo pela lista fechada de tags
                    got = [tibianews.sanitize(g) for g in got]
                rows = list(zip(missing.keys(), got))
                store.save_translations(rows, lang)
                store.set_meta(month_key, str(used + chars))
                _tr_usage["used"] += chars
                known.update(rows)
    out = [known.get(h, t) for h, t in zip(hashes, texts)]
    return out, any(h in known for h in hashes)


def _translate_news(rows: list[dict], lang: str | None, content: bool = True) -> list[dict]:
    if not lang or not rows:
        return rows
    titles, t_ok = _translate([r["title"] for r in rows], lang)
    for r, t in zip(rows, titles):
        r["title"] = t
    with_body = [r for r in rows if content and r.get("content_html")]
    bodies, b_ok = _translate([r["content_html"] for r in with_body], lang, html=True)
    for r, b in zip(with_body, bodies):
        r["content_html"] = b
    if t_ok or b_ok:
        for r in rows:
            r["translated"] = True
    return rows


def _news_status() -> dict:
    return {"updated_at": store.meta("tibia_news_ok_at"), "offline": store.meta("tibia_news_source") == "offline",
            "total": store.tibia_news_count()}


@app.get("/api/tibia/latest")
def tibia_latest(lang: str = "", _: dict = Depends(require_session)):
    """📰 Novidades: o que está no Latest News do tibia.com (ticker, artigo em destaque e notícias), no idioma do app."""
    since = (date.today() - timedelta(days=NEWS_LATEST_DAYS)).isoformat()
    tickers = _news_with_content(store.tibia_news_latest(("ticker",), 8))
    featured = _news_with_content(store.tibia_news_latest(("article",), 1))
    news = _news_with_content(store.tibia_news_latest(("news",), 30, since) or store.tibia_news_latest(("news",), 10))
    _translate_news(tickers + featured + news, _lang(lang))
    return {**_news_status(), "tickers": [_news_out(r) for r in tickers],
            "featured": _news_out(featured[0]) if featured else None, "news": [_news_out(r) for r in news]}


@app.get("/api/tibia/headline")
def tibia_headline(lang: str = "", _: dict = Depends(require_session)):
    """Destaque do Início: a notícia (ou artigo) mais nova do tibia.com, no idioma do app."""
    rows = _news_with_content(store.tibia_news_latest(("news", "article"), 1))
    if not rows:
        return None
    _translate_news(rows, _lang(lang))
    return _news_out(rows[0])


@app.get("/api/tibia/archive")
def tibia_archive(date_from: str = Query("", alias="from"), date_to: str = Query("", alias="to"),
                  categories: str = ",".join(tibianews.CATEGORIES), types: str = ",".join(tibianews.TYPES),
                  q: str = Query("", max_length=80), lang: str = "", _: dict = Depends(require_session)):
    """💬 O que os CMs estão falando: o filtro do News Archive (padrão: última semana, tudo marcado)."""
    today = date.today()
    try:
        d_to = date.fromisoformat(date_to) if date_to else today
        d_from = date.fromisoformat(date_from) if date_from else d_to - timedelta(days=7)
    except ValueError:
        raise HTTPException(422, "Data inválida. Use o calendário do filtro.")
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    cats = [c for c in categories.lower().split(",") if c in tibianews.CATEGORIES]
    typs = [t for t in types.lower().split(",") if t in tibianews.TYPES]
    rows, total = store.tibia_news_search(d_from.isoformat(), d_to.isoformat(), cats, typs, q.strip())
    _translate_news(rows, _lang(lang), content=False)  # na lista só os títulos; o texto traduz ao abrir
    return {**_news_status(), "from": d_from.isoformat(), "to": d_to.isoformat(), "count": total,
            "rows": [_news_out(r) for r in rows]}


@app.get("/api/tibia/calendar")
def tibia_calendar(month: str = "", lang: str = "", _: dict = Depends(require_session)):
    """📅 Calendário de eventos (o que o administrador colou do tibia.com; a colagem mais nova de cada mês).
    As descrições dos eventos vêm no idioma do app; o nome do evento fica como no jogo."""
    months = [m["month"] for m in store.calendar_months()]
    if not months:
        return {"months": [], "month": None, "calendar": None}
    current = date.today().strftime("%Y-%m")
    if month not in months:
        month = current if current in months else min((m for m in months if m >= current), default=months[0])
    cal = store.calendar(month)
    translated = False
    if cal and _lang(lang):
        names = [n for n, ev in cal["events"].items() if ev.get("description")]
        texts, translated = _translate([cal["events"][n]["description"] for n in names], _lang(lang))
        for n, t in zip(names, texts):
            cal["events"][n]["description"] = t
    return {"months": sorted(months), "month": month, "calendar": cal, "translated": translated}


@app.get("/api/tibia/news/{news_id}")
def tibia_news_item(news_id: int, lang: str = "", _: dict = Depends(require_session)):
    row = store.tibia_news_item(news_id)
    if row is None:
        raise HTTPException(404, "Notícia não encontrada.")
    _news_with_content([row])
    _translate_news([row], _lang(lang))
    return {**_news_out(row), "offline": row.get("content_html") is None}


@app.api_route("/api/health", methods=["GET", "HEAD"])  # HEAD: monitores externos (UptimeRobot grátis só usa HEAD)
def health():
    return {"ok": True, "app": APP_NAME, "version": __version__}


# ------------------------------------------------------------------ 0.23.0: app para Windows descontinuado
# O 4rt3mi5 agora é só o site. O botão de download saiu do ar e o app instalado não conversa mais com o servidor.
SITE_URL = "https://artemishunt.com.br"
DESKTOP_GONE = f"O app de Windows do 4rt3mi5 foi descontinuado. Use o 4rt3mi5 pelo navegador: {SITE_URL}"


@app.get("/api/download")
def download_meta():
    """0.23.0: não há mais instalador para baixar."""
    return {"available": False, "discontinued": True, "message": DESKTOP_GONE, "site": SITE_URL}


@app.get("/download", include_in_schema=False)
def download_redirect():
    """Endereço antigo do instalador: volta para o site."""
    return RedirectResponse("/", status_code=302, headers={"Cache-Control": "no-store"})

# ------------------------------------------------------------------ imagens da TibiaWiki guardadas no banco
# O site pede /img/wiki/<Nome>.gif; na primeira vez o servidor busca na TibiaWiki BR e guarda no banco.
# Depois disso a imagem sai do banco, sem depender da wiki. Se a wiki não responder, o navegador é
# mandado para o endereço original (que o CSP já permite).
WIKI_IMG_URL = "https://www.tibiawiki.com.br/wiki/Especial:Redirecionar/file/{}.gif"
_IMG_NAME = re.compile(r"[\w À-ÿ'().,&+!-]{1,80}")
IMG_MAX = 300_000
IMG_MISS_RETRY = timedelta(days=7)     # imagem que não existe: tenta de novo depois de uma semana
IMG_FETCH_LIMIT = (120, 60)             # buscas novas na wiki (todas as pessoas juntas) por minuto
_img_fetches: deque = deque()


def _fetch_wiki_image(name: str) -> tuple[str, bytes] | None | bool:
    """(tipo, bytes) se achou; None se não existe na wiki; False se a wiki não respondeu."""
    import urllib.error
    import urllib.parse
    import urllib.request
    url = WIKI_IMG_URL.format(urllib.parse.quote(name.replace(" ", "_")))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (4rt3mi5 image cache)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            host = urllib.parse.urlparse(r.geturl()).hostname or ""
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            if not host.endswith("tibiawiki.com.br") or not ctype.startswith("image/"):
                return None
            data = r.read(IMG_MAX + 1)
            return None if len(data) > IMG_MAX else (ctype, data)
    except urllib.error.HTTPError as e:
        return None if e.code == 404 else False
    except OSError:
        return False


def _img_budget() -> bool:
    limit, window = IMG_FETCH_LIMIT
    now = time.monotonic()
    while _img_fetches and now - _img_fetches[0] > window:
        _img_fetches.popleft()
    if len(_img_fetches) >= limit:
        return False
    _img_fetches.append(now)
    return True


@app.get("/img/wiki/{file}", include_in_schema=False)
async def wiki_image(file: str, request: Request):
    name = file[:-4] if file.lower().endswith(".gif") else file
    name = " ".join(name.replace("_", " ").split())
    if not _IMG_NAME.fullmatch(name):
        return Response(status_code=404)
    if _rate_limited(client_ip(request), "img"):
        return Response(status_code=429, headers={"Retry-After": "60"})
    cached = store.wiki_image(name)
    if cached is not None and cached["data"] is not None:
        return Response(cached["data"], media_type=cached["content_type"],
                        headers={"Cache-Control": "public, max-age=2592000, immutable"})
    original = WIKI_IMG_URL.format(name.replace(" ", "_"))
    if cached is not None and datetime.fromisoformat(cached["fetched_at"]) > datetime.now().astimezone() - IMG_MISS_RETRY:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=86400"})
    if not _img_budget():
        return RedirectResponse(original, status_code=302)
    got = await asyncio.to_thread(_fetch_wiki_image, name)
    if got is False:
        return RedirectResponse(original, status_code=302)
    store.save_wiki_image(name, got[0] if got else None, got[1] if got else None)
    if got is None:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=86400"})
    return Response(got[1], media_type=got[0], headers={"Cache-Control": "public, max-age=2592000, immutable"})


_LOCAL_ORIGIN = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")


def _log_login(request: Request, access: dict) -> None:
    store.log_login(access["key"], "app" if _LOCAL_ORIGIN.match(request.headers.get("origin", "")) else "site")


@app.post("/api/auth")
def auth(request: Request, session: tuple = Depends(optional_device), x_account_token: str = Header(default="")):
    access, device = session
    if device is not None:  # abertura do app/site já liberado = 1 entrada (histórico do painel do criador)
        _log_login(request, access)
    acc = store.account_by_token(x_account_token) if x_account_token else None
    owner = store.account_for_key(access["key"]) if acc else None
    return {"valid": True, "expires_at": user_expires(access), "claimed": bool(access.get("main_char")),
            "device_verified": device is not None,
            "other_account": bool(owner and owner["id"] != acc["id"])}  # 0.16.0: código já é de outra conta


# ------------------------------------------------------------------ 0.16.0: contas (login com senha)
USERNAME_RE = re.compile(r"[A-Za-z0-9]{3,20}")
PASSWORD_RE = re.compile(r"[A-Za-z0-9_!@-]{6,64}")
LOGIN_FAIL_LIMIT = 30     # 30 senhas erradas...
LOGIN_BLOCK = 30 * 60     # ...bloqueiam o IP por 30 minutos
WRONG_PASSWORD = "Conta/Senha incorreta(s)."  # 0.17.0: não diz qual dos dois está errado
LOGIN_BLOCKED = "Muitas tentativas com senha errada. Por segurança, o acesso ficou bloqueado por 30 minutos."
ACCOUNT_NEEDED = "Entre na sua conta de novo."
_login_fails: dict[str, int] = {}
_login_blocked: dict[str, float] = {}


class AccountIn(BaseModel):
    username: Annotated[str, Field(max_length=40)]
    password: Annotated[str, Field(max_length=100)]
    confirm: Annotated[str | None, Field(default=None, max_length=100)] = None
    device_token: Annotated[str, Field(default="", max_length=100)] = ""


def require_account(x_account_token: str = Header(default="")) -> dict:
    acc = store.account_by_token(x_account_token)
    if acc is None:
        raise HTTPException(401, {"message": ACCOUNT_NEEDED, "reason": "account"})
    return acc


def _login_check_blocked(ip: str) -> None:
    until = _login_blocked.get(ip)
    if until and time.monotonic() < until:
        raise HTTPException(429, {"message": LOGIN_BLOCKED, "reason": "login_blocked"})
    if until:
        _login_blocked.pop(ip, None)


def _login_fail(ip: str) -> None:
    n = _login_fails.get(ip, 0) + 1
    if n >= LOGIN_FAIL_LIMIT:
        _login_blocked[ip] = time.monotonic() + LOGIN_BLOCK
        _login_fails.pop(ip, None)
        raise HTTPException(429, {"message": LOGIN_BLOCKED, "reason": "login_blocked"})
    _login_fails[ip] = n
    if len(_login_fails) > 5000:
        for k in list(_login_fails)[:1000]:
            _login_fails.pop(k, None)


def _account_enter(acc: dict, token: str, device_token: str = "") -> dict:
    """Depois da senha (ou ao reabrir): devolve a chave da conta e um aparelho liberado, se já houver personagem."""
    out = {"token": token, "username": acc["username"], "key": None, "device_token": None, "expires_at": None,
           "store_claimed": bool(acc["store_claimed"]), "key_expired": False}
    key = store.get_key(acc["access_key"]) if acc["access_key"] else None
    if key is None:
        return out
    out.update(key=key["key"], expires_at=user_expires(key))
    if store.is_expired(key):  # 0.17.0: chave vencida continua na conta; a pessoa renova e volta de onde parou
        out["key_expired"] = True
        return out
    if key.get("main_char"):  # a conta já passou pela verificação: este aparelho entra direto
        out["device_token"] = (device_token if store.device_valid(key["key"], device_token)
                               else store.issue_device(key["key"], key["main_char"]))
    return out


@app.post("/api/account/register")
def account_register(body: AccountIn):
    if not USERNAME_RE.fullmatch(body.username):
        raise HTTPException(422, "A conta deve ter de 3 a 20 letras ou números, sem espaços nem caracteres especiais.")
    if not PASSWORD_RE.fullmatch(body.password):
        raise HTTPException(422, "A senha deve ter de 6 a 64 caracteres: números, letras e os especiais _ ! @ -")
    if body.confirm is not None and body.confirm != body.password:
        raise HTTPException(422, "As senhas não são iguais.")
    acc = store.create_account(body.username, body.password)
    if acc is None:
        raise HTTPException(409, "Essa conta já existe. Escolha outro nome ou toque em Entrar.")
    return _account_enter(acc, store.new_account_session(acc["id"]))


@app.post("/api/account/login")
def account_login(body: AccountIn, request: Request):
    ip = client_ip(request)
    _login_check_blocked(ip)
    acc = store.check_password(body.username.strip(), body.password)
    if acc is None:
        _login_fail(ip)
        raise HTTPException(401, {"message": WRONG_PASSWORD, "reason": "password"})
    _login_fails.pop(ip, None)
    return _account_enter(acc, store.new_account_session(acc["id"]), body.device_token)


class ResumeIn(BaseModel):
    device_token: Annotated[str, Field(default="", max_length=100)] = ""


@app.post("/api/account/resume")
def account_resume(body: ResumeIn, x_account_token: str = Header(default=""), acc: dict = Depends(require_account)):
    """Reabrir o app/site já logado."""
    return _account_enter(acc, x_account_token, body.device_token)


@app.post("/api/account/renew")
def account_renew(x_account_token: str = Header(default=""), acc: dict = Depends(require_account)):
    """0.17.0: renovação grátis de 7 dias pela conta, inclusive com a chave já vencida."""
    key = store.get_key(acc["access_key"]) if acc["access_key"] else None
    if key is None:
        raise HTTPException(404, "Sua conta ainda não tem chave de acesso.")
    renewed = store.renew_account_key(key["key"])
    return {**_account_enter(store.account(acc["id"]), x_account_token), "renewed": renewed}


class ResetIn(BaseModel):
    username: Annotated[str, Field(max_length=40)]
    code: Annotated[str, Field(max_length=40)]
    password: Annotated[str, Field(max_length=100)]
    confirm: Annotated[str | None, Field(default=None, max_length=100)] = None


@app.post("/api/account/reset")
def account_reset(body: ResetIn, request: Request):
    """0.17.0: nova senha com o código de uso único que o adm mandou pelo WhatsApp."""
    ip = client_ip(request)
    _login_check_blocked(ip)
    if not PASSWORD_RE.fullmatch(body.password):
        raise HTTPException(422, "A senha deve ter de 6 a 64 caracteres: números, letras e os especiais _ ! @ -")
    if body.confirm is not None and body.confirm != body.password:
        raise HTTPException(422, "As senhas não são iguais.")
    acc = store.use_reset_code(body.username.strip(), body.code, body.password)
    if acc is None:
        _login_fail(ip)  # conta com as senhas erradas: 30 erros bloqueiam o IP
        raise HTTPException(401, {"message": "Conta ou código incorretos (ou o código já venceu).", "reason": "password"})
    _login_fails.pop(ip, None)
    return _account_enter(acc, store.new_account_session(acc["id"]))


@app.post("/api/account/logout")
def account_logout(x_account_token: str = Header(default="")):
    store.end_account_session(x_account_token)
    return {"ok": True}


@app.post("/api/account/link")
def account_link(access: dict = Depends(require_session), acc: dict = Depends(require_account)):
    """Liga à conta a chave que acabou de passar pela verificação neste aparelho."""
    if not store.link_account_key(acc["id"], access["key"]):
        raise HTTPException(409, {"message": "Esse código de acesso já pertence a outra conta.", "reason": "key_taken"})
    return {"ok": True, "key": access["key"]}


WHATSAPP_RE = re.compile(r"\d{10,15}")
RECOVERY_REASONS = {"lost_code", "char_taken", "key_taken"}


class RecoveryIn(BaseModel):
    whatsapp: Annotated[str, Field(max_length=30)]
    reason: Annotated[str, Field(max_length=20)]
    character: Annotated[str | None, Field(default=None, max_length=NAME_MAX)] = None


@app.post("/api/recovery")
def recovery(body: RecoveryIn, acc: dict = Depends(require_account)):
    """Pedido para o adm chamar no WhatsApp e recuperar o código de acesso."""
    phone = re.sub(r"\D", "", body.whatsapp)
    if not WHATSAPP_RE.fullmatch(phone):
        raise HTTPException(422, "Digite o WhatsApp com DDD, só números (ex.: 21 99999-9999).")
    if body.reason not in RECOVERY_REASONS:
        raise HTTPException(422, "Motivo inválido.")
    if body.character and not _VALID_NAME.fullmatch(body.character):
        raise HTTPException(422, "Nome de personagem inválido.")
    if len(store.open_recoveries(acc["id"])) >= 3:
        raise HTTPException(429, "Você já enviou pedidos. Aguarde o administrador entrar em contato.")
    store.add_recovery(acc, phone, body.reason, body.character)
    return {"ok": True}


class LostLoginIn(BaseModel):
    whatsapp: Annotated[str, Field(max_length=30)]
    username: Annotated[str, Field(default="", max_length=40)] = ""
    character: Annotated[str | None, Field(default=None, max_length=NAME_MAX)] = None


LOST_LOGIN_PER_IP = 3          # pedidos por IP a cada 24 h (rota sem login)
LOST_LOGIN_MAX_OPEN = 100      # teto de pedidos abertos desse tipo
_lost_login_hits: dict[str, list[float]] = {}


@app.post("/api/recovery/login")
def recovery_login(body: LostLoginIn, request: Request):
    """0.17.0: "Esqueceu conta/senha?" — quem não consegue entrar deixa o WhatsApp para o adm."""
    phone = re.sub(r"\D", "", body.whatsapp)
    if not WHATSAPP_RE.fullmatch(phone):
        raise HTTPException(422, "Escolha o país e digite o WhatsApp com DDD, só números.")
    username = body.username.strip()
    if username and not USERNAME_RE.fullmatch(username):
        username = ""  # o que a pessoa lembra pode estar errado; só guarda se for um nome possível
    if body.character and not _VALID_NAME.fullmatch(body.character):
        raise HTTPException(422, "Nome de personagem inválido.")
    ip = client_ip(request)
    now = time.monotonic()
    hits = [t for t in _lost_login_hits.get(ip, []) if now - t < 86400]
    if len(hits) >= LOST_LOGIN_PER_IP or store.count_open_recoveries("lost_login") >= LOST_LOGIN_MAX_OPEN:
        raise HTTPException(429, "Você já enviou pedidos. Aguarde o administrador entrar em contato.")
    _lost_login_hits[ip] = hits + [now]
    store.add_recovery(None, phone, "lost_login", body.character, username)
    return {"ok": True}


# ------------------------------------------------------------------ 0.13.0: uso das telas (só contadores)
TRACK_PAGES = {"home", "loot", "stack", "boss", "hunts", "rank", "ach", "chars", "news", "settings",
               "download", "subs", "parties"}  # 0.21.0; 0.23.0: 🤝 Substituições; 0.24.0: 🛡️ parties


class TrackIn(BaseModel):
    page: str = Field(max_length=20)
    action: bool = False


@app.post("/api/track")
def track(body: TrackIn, _: dict = Depends(require_session)):
    """Conta visita/ação por tela e por dia, sem guardar quem foi (painel do criador)."""
    if body.page not in TRACK_PAGES:
        raise HTTPException(422, "Tela desconhecida.")
    store.track_screen(body.page, body.action, ach.local_day(datetime.now(timezone.utc).isoformat()).isoformat())
    return {"ok": True}


# ------------------------------------------------------------------ 0.21.0: contato com o administrador
# Tela aberta a qualquer pessoa (inclusive sem conta, como a CipSoft). Contra robôs: campo escondido ":boom:",
# CAPTCHA próprio (prova de trabalho, sem script de fora) e limites por IP e por dia.
CONTACT_EMAIL = os.environ.get("ARTEMIS_CONTACT_EMAIL", "contato@artemishunt.com.br")  # o endereço que aparece na tela
CONTACT_MAX = 3000
CONTACT_SUBJECT_MAX = 120
CONTACT_PER_IP = (3, 3600)       # 3 mensagens por hora por IP
CONTACT_PER_DAY = 60             # teto de mensagens (todas as pessoas) em 24 h
CONTACT_LANGS = {"pt-BR", *("en", "es", "ja", "de", "pl", "fr", "ru")}
EMAIL_RE = re.compile(r"[^@\s<>\"',;]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})+")
CAPTCHA_SECRET = secrets.token_bytes(32)   # muda a cada reinício: desafios antigos deixam de valer
_captcha_used: dict[str, float] = {}
_contact_hits: dict[str, list[float]] = {}
CAPTCHA_FAILED = "A confirmação de que você não é um robô expirou. Envie de novo."


class ContactIn(BaseModel):
    email: Annotated[str, Field(max_length=254)]
    subject: Annotated[str, Field(default="", max_length=CONTACT_SUBJECT_MAX)] = ""
    message: Annotated[str, Field(max_length=CONTACT_MAX)]
    lang: Annotated[str, Field(default="pt-BR", max_length=8)] = "pt-BR"
    captcha: dict = Field(default_factory=dict)
    boom: Annotated[str, Field(default="", max_length=500, alias=":boom:")] = ""  # campo escondido: só robô preenche


@app.get("/api/contact")
def contact_info():
    return {"to": CONTACT_EMAIL, "max": CONTACT_MAX, "subject_max": CONTACT_SUBJECT_MAX}


@app.get("/api/contact/challenge")
def contact_challenge():
    return captcha.issue(CAPTCHA_SECRET)


def _deliver_contact(contact_id: int, email: str, subject: str, message: str, lang: str, when: str) -> None:
    if mailer.send(email, subject, message, lang, when):
        store.mark_contact(contact_id, sent=True)


@app.post("/api/contact")
def contact_send(body: ContactIn, request: Request):
    lang = body.lang if body.lang in CONTACT_LANGS else "pt-BR"
    if body.boom.strip():  # robô: finge que deu certo (ele não percebe) e não envia nada a ninguém
        store.add_contact(body.email[:254], "", body.message[:200], lang, robot=True)
        return {"ok": True}
    email = body.email.strip()
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(422, "Digite o seu e-mail completo, por exemplo nome@gmail.com.")
    subject = " ".join(body.subject.split())  # sem quebras de linha (o assunto vai no cabeçalho do e-mail)
    message = body.message.replace("\r\n", "\n").strip()
    if len(message) < 10:
        raise HTTPException(422, "Escreva a sua mensagem (pelo menos 10 caracteres).")
    try:
        captcha.verify(CAPTCHA_SECRET, body.captcha, _captcha_used)
    except captcha.CaptchaError:
        raise HTTPException(400, {"message": CAPTCHA_FAILED, "reason": "captcha"})
    ip, now = client_ip(request), time.monotonic()
    limit, window = CONTACT_PER_IP
    hits = [t for t in _contact_hits.get(ip, []) if now - t < window]
    if len(hits) >= limit or store.contacts_since(datetime.now(timezone.utc) - timedelta(days=1)) >= CONTACT_PER_DAY:
        raise HTTPException(429, {"message": "Você já enviou mensagens agora há pouco. Aguarde um pouco para enviar outra.",
                                  "reason": "rate"})
    _contact_hits[ip] = hits + [now]
    if len(_contact_hits) > 5000:
        for k in list(_contact_hits)[:1000]:
            _contact_hits.pop(k, None)
    contact_id = store.add_contact(email, subject, message, lang, robot=False)
    when = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
    threading.Thread(target=_deliver_contact, args=(contact_id, email, subject, message, lang, when), daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------ 0.13.0: loja (chave grátis)
STORE_FREE_DAYS = 7
STORE_FREE_PER_DAY = 20   # no máximo 20 chaves grátis por dia no total
STORE_SALT = secrets.token_hex(16)  # IP vira hash com sal que muda a cada reinício: o banco nunca guarda o IP


def _store_free_on() -> bool:
    return store.meta("store_free") != "off"


@app.get("/api/store")
def store_info():
    return {"free": _store_free_on(), "free_days": STORE_FREE_DAYS}


@app.post("/api/store/free")
def store_free(request: Request, acc: dict = Depends(require_account)):
    if not _store_free_on():
        raise HTTPException(403, "A chave gratuita está pausada no momento. Peça um código para quem te indicou o 4rt3mi5.")
    # 0.16.0: a loja gera a chave uma vez só por conta (é o cadastro)
    if acc["store_claimed"] or (acc["access_key"] and store.validate_key(acc["access_key"])):
        raise HTTPException(409, "Sua conta já gerou a chave gratuita. Se perdeu o acesso, fale com o administrador.")
    ip_hash = hashlib.sha256((STORE_SALT + client_ip(request)).encode()).hexdigest()
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    if store.store_claims_since(day_ago, ip_hash):
        raise HTTPException(429, "Você já gerou uma chave gratuita hoje. Use a que recebeu ou tente amanhã.")
    if store.store_claims_since(day_ago) >= STORE_FREE_PER_DAY:
        raise HTTPException(429, "As chaves gratuitas de hoje acabaram. Tente de novo amanhã.")
    store.add_store_claim(ip_hash)
    k = store.create_key(STORE_FREE_DAYS, f"Loja (grátis) · {acc['username']}")
    store.link_account_key(acc["id"], k["key"], store_claim=True)
    return {"key": k["key"], "expires_at": k["expires_at"]}


CHAR_TAKEN = "Este personagem já possui código de acesso."


def _check_char_free(key: str, name: str) -> None:
    """0.15.0: personagem em uma chave só, e no máximo 50 personagens por chave."""
    owner = store.char_owner(name)
    if owner and owner != key:
        raise HTTPException(409, {"message": CHAR_TAKEN, "reason": "char_taken"})
    if not owner and store.char_count(key) >= store.MAX_CHARS_PER_KEY:
        raise HTTPException(400, f"Sua chave já tem {store.MAX_CHARS_PER_KEY} personagens, o máximo. "
                                 "Remova um em Meus personagens para adicionar outro.")


@app.post("/api/verify/start")
def verify_start(body: CharIn, request: Request, session: tuple = Depends(optional_device)):
    access, device = session
    # 0.25.0: personagem já verificado há menos de 30 dias, ou verificado à mão: entra sem consultar o TibiaData
    # Aparelho já conhecido (com token) dispensa a checagem por 30 dias; verificação manual vale em qualquer aparelho.
    # Chave copiada num aparelho novo continua precisando provar o personagem no comentário.
    nome = " ".join(body.character.split())
    info = store.trust_info(nome)
    if store.is_linked(access["key"], nome) and store.trust_valid(nome) and \
            (device is not None or bool(info and info["manual"])):
        token = device or store.issue_device(access["key"], nome)
        _log_login(request, access)
        return {"token": token, "character": nome, "me": me_payload(access), "trusted": True}
    # Sem o TibiaData (fora do ar ou com erro para esse nome) o login não pode travar: o código é gerado
    # mesmo assim, com mais tempo. A prova continua sendo o código no comentário, conferido em verify/check.
    minutes, unconfirmed = 60, False
    try:
        name = char_or_404(body.character).name
    except HTTPException as e:
        if e.status_code != 503:
            raise
        name = " ".join((body.character or "").split())
        if not _VALID_NAME.fullmatch(name):
            raise HTTPException(422, "Nome de personagem inválido.")
        minutes, unconfirmed = 240, True
    owner = store.char_owner(name)
    if owner and owner != access["key"]:  # 0.23.0: o dono fica sabendo que alguém tentou vincular o personagem dele
        store.note_char_claim(name)
    _check_char_free(access["key"], name)
    # Contato de confiança (main forçado pelo criador): entra direto, sem código de verificação.
    if access.get("trusted") and store.is_linked(access["key"], name):
        token = device or store.issue_device(access["key"], name)
        _log_login(request, access)
        return {"token": token, "character": name, "me": me_payload(access), "trusted": True}
    # Código já tem dono: um aparelho novo só pode verificar com um personagem já vinculado.
    if access.get("main_char") and device is None and not store.is_linked(access["key"], name):
        raise HTTPException(403, KEY_TAKEN)
    v = store.start_verification(access["key"], name, minutes=minutes)
    out = {"code": v["code"], "character": name, "expires_at": v["expires_at"]}
    if unconfirmed:
        out["unconfirmed"] = True
        out["hint"] = ("O TibiaData está instável agora, então ainda não conferimos o personagem. "
                       "Coloque o código no comentário do personagem no tibia.com e toque em conferir; "
                       "o código vale por 4 horas.")
    return out


@app.post("/api/verify/check")
def verify_check(body: CodeIn, request: Request, session: tuple = Depends(optional_device)):
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
    _check_char_free(access["key"], ch.name)  # outra chave pode ter verificado o mesmo personagem nesse meio tempo
    token = store.complete_verification(access["key"], v["code"], ch.name, device)
    store.trust_upsert(ch.name)  # 0.25.0: verificado agora; a próxima checagem automática é daqui a 30 dias
    _log_login(request, access)
    return {"token": token, "character": ch.name, "me": me_payload(access)}


@app.get("/api/me")
def me(access: dict = Depends(require_session)):
    return me_payload(access)


class PlayerTypeIn(BaseModel):
    player_type: Annotated[str, Field(max_length=20)]


# Tipos que a pessoa pode escolher. Tipos extras podem ser ligados no .env (ARTEMIS_EXTRA_PLAYER_TYPES);
# nome e descrição em data/player_types.json.
PLAYER_TYPES_OPEN = BASE_PLAYER_TYPES


def _open_player_types() -> tuple:
    return PLAYER_TYPES_OPEN + extra_player_types()


def _sharing_types() -> tuple:
    """Quem junta sessão e Input Analyzer ao que é da PT (os tipos extras contam como Hardcore)."""
    return ("hardcore", "comum") + extra_player_types()


def _hardcore_types() -> tuple:
    return ("hardcore",) + extra_player_types()


def _extra_type_info() -> dict:
    extra = [t for t in _open_player_types() if t not in PLAYER_TYPES_OPEN]
    if not extra:
        return {}
    try:
        info = json.loads((DATA_DIR / "player_types.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    return {t: info.get(t, {}) for t in extra}


@app.post("/api/prefs/player-type")
def set_player_type(body: PlayerTypeIn, access: dict = Depends(require_session)):
    """0.20.0: tipo de player (na criação da conta e em ⚙️ Configurações; vale para a conta toda)."""
    if body.player_type not in _open_player_types():
        raise HTTPException(422, "Tipo de player inválido.")
    store.set_player_type(access["key"], body.player_type)
    return me_payload(access)


@app.post("/api/key/renew-free")
def renew_free(access: dict = Depends(require_session)):
    """0.14.0: o próprio usuário renova 7 dias grátis. 0.15.0: só quando faltam menos de 3 dias e com personagem verificado."""
    if access.get("lifetime"):
        return {"renewed": False, "days_left": None, "me": me_payload(access)}
    if not access.get("main_char"):
        raise HTTPException(403, "Verifique um personagem antes de renovar a chave.")
    renewed, current = store.renew_free(access["key"])
    current = current or access
    left = (datetime.fromisoformat(current["expires_at"]) - datetime.now(timezone.utc)).total_seconds() / 86400
    return {"renewed": renewed, "days_left": int(left), "free_days": store.FREE_RENEW_DAYS,
            "window_days": store.RENEW_WINDOW_DAYS, "me": me_payload(current)}


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


# ------------------------------------------------------------------ 0.23.0: 🤝 personagem certo e substituições
NOT_IN_PARTY_UPLOAD = "Nenhum personagem seu está nesse Party Hunt Analyser."
NOT_IN_PARTY_HINT = "Jogou no personagem de outra pessoa? Peça a ela um link de envio (☰ → 🤝 Substituições)."
NO_GRANT = "Você não está autorizado a enviar por esse personagem (ou a autorização acabou)."
LINK_NOT_FOUND = "Link de envio não encontrado. Confira com quem te enviou."
LINK_CLOSED = "Esse link de envio não vale mais (venceu, foi cancelado ou chegou ao limite de envios). Peça um novo."
LINK_OUT_OF_TIME = "Essa hunt não é do período do link de envio."
LINK_HOURS = (6, 24, 72, 168)
LINK_WINDOW = timedelta(hours=14)  # o horário do analyser é o do PC de quem jogou (outro fuso)


def _party_char(players: list[dict], nickname: str, access: dict) -> tuple[str, str | None] | None:
    """Personagem do código que está na PT: (nome, de qual personagem trocou) ou None.
    Se o personagem escolhido não está na PT mas outro do mesmo código está, troca sozinho."""
    in_party = {name_key(p["name"]) for p in players}
    mine = store.key_chars(access["key"])
    if name_key(nickname) in in_party and any(name_key(c["name"]) == name_key(nickname) for c in mine):
        return next(c["name"] for c in mine if name_key(c["name"]) == name_key(nickname)), None
    for c in sorted(mine, key=lambda c: not c["is_main"]):
        if name_key(c["name"]) in in_party:
            return c["name"], nickname
    return None


def _grant_for(char_names, access: dict, scope: str) -> tuple[dict, str] | None:
    """Jogador autorizado: link ativo que deixa um personagem deste código enviar por um destes personagens."""
    mine = [c["name"] for c in store.key_chars(access["key"])]
    wanted = {name_key(n) for n in char_names}
    for g in store.grants_for(mine):
        if g["name_key"] in wanted and scope in g["scopes"] and g["owner_key"] != access["key"]:
            return g, next(n for n in mine if name_key(n) == g["operator_key"])
    return None


def _who(via: str, played_by: str | None) -> dict:
    return {"via": via, "other_player": 1, "played_by": played_by}


def _in_link_window(link: dict, started_at: str) -> None:
    """A hunt precisa ser do período do link (com folga de fuso): nada de mandar hunt antiga por ele."""
    try:
        t = datetime.fromisoformat(started_at).replace(tzinfo=None)
        lo = datetime.fromisoformat(link["created_at"]).replace(tzinfo=None) - LINK_WINDOW
        hi = datetime.fromisoformat(link["expires_at"]).replace(tzinfo=None) + LINK_WINDOW
    except (TypeError, ValueError):
        return
    if not lo <= t <= hi:
        raise HTTPException(422, LINK_OUT_OF_TIME)


def _spend_link(link: dict) -> None:
    if not store.use_link(link["id"]):
        raise HTTPException(410, {"message": LINK_CLOSED, "reason": "link"})


def _check_duplicate(table: str, data: dict, name: str, owner_key: str) -> None:
    """A mesma sessão (mesmos horários e números) não fica salva em dois personagens."""
    dup = store.session_by_content(table, session_content_hash(data))
    if not dup or dup["name_key"] == name_key(name):
        return
    if dup["uploader_key"] == owner_key or store.is_linked(owner_key, dup["name"]):
        raise HTTPException(409, {"message": f"Essa sessão já está salva em {dup['name']}.",
                                  "hint": "A mesma sessão não fica em dois personagens. Escolheu o personagem errado? "
                                          "Apague a sessão de lá e envie de novo.", "reason": "duplicate"})
    raise HTTPException(409, {"message": "Essa sessão já foi enviada por outra conta.",
                              "hint": "Se o personagem é seu, fale com o administrador.", "reason": "duplicate"})


def _hunts_at(names: list[str], started_at: str, ended_at: str, boss: bool = False) -> list[tuple[str, dict]]:
    """Lootsplits (comuns ou de bosses) destes personagens que cruzam o horário da sessão: [(name_key, report)]."""
    try:
        lo = (datetime.fromisoformat(started_at) - timedelta(hours=12)).isoformat()
        hi = (datetime.fromisoformat(ended_at) + boss_core.LINK_TOLERANCE).isoformat()
    except (TypeError, ValueError):
        return []
    return [(k, rep) for k, rep in store.party_hunts_between(names, lo, hi, boss)
            if rep.get("ended_at") and boss_core.overlaps(started_at, ended_at, rep["started_at"], rep["ended_at"])]


def _overlapping_char(started_at: str, ended_at: str, access: dict, boss: bool = False) -> str | None:
    """Stacker: se só um personagem do código tem um lootsplit no mesmo horário, a sessão é dele."""
    chars = {name_key(c["name"]): c["name"] for c in store.key_chars(access["key"])}
    found = {chars[k] for k, _ in _hunts_at(list(chars.values()), started_at, ended_at, boss) if k in chars}
    return found.pop() if len(found) == 1 else None


# ------------------------------------------------------------------ lootsplit
def _parse_party(raw: str) -> dict:
    try:
        return report_from_text(raw)
    except ParseError as e:
        raise HTTPException(422, str(e))


def _public(row: dict, access: dict) -> dict:
    """Esconde dados internos e diz se quem está vendo pode apagar (só quem enviou)."""
    owner = row.pop("uploader_key", None)
    for k in ("submitted_by", "fingerprint", "name_key", "content_hash"):
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


# 0.20.0: o que cada membro da PT juntou ao lootsplit. Quantidade de criaturas e de itens fica só com o dono.
_MEMBER_PUBLIC = ("started_at", "ended_at", "duration_seconds", "xp", "raw_xp", "balance", "supplies",
                  "damage", "damage_h", "healing", "healing_h")


def _input_view(i: dict) -> dict:
    return {**i, **damage_core.summary(i)}


SAME_PERIOD_SECONDS = 60  # folga entre o relógio do Hunt Session Analyser e o do Party Hunt Analyser


def _discrepancy(s: dict, h: dict) -> list[str]:
    """Sessão do membro x a linha dele no Party Hunt Analyser. Só conta quando é o mesmo período da party hunt.
    Loot type Leader: o loot fica com o líder, então só os supplies são comparados. Market: loot, supplies e balance."""
    try:
        same = all(abs((datetime.fromisoformat(s[a]) - datetime.fromisoformat(h[b])).total_seconds()) <= SAME_PERIOD_SECONDS
                   for a, b in (("started_at", "started_at"), ("ended_at", "ended_at")))
    except (KeyError, TypeError, ValueError):
        return []
    p = next((p for p in h.get("players", []) if name_key(p["name"]) == name_key(s["name"])), None)
    if not same or p is None:
        return []
    mine = {"supplies": s.get("supplies", 0), "balance": s.get("balance", 0),
            "loot": s.get("balance", 0) + s.get("supplies", 0)}  # no Tibia, Balance = Loot − Supplies
    fields = ("supplies",) if (h.get("loot_type") or "").strip().lower() == "leader" else ("loot", "supplies", "balance")
    return [f for f in fields if p.get(f) is not None and mine[f] != p[f]]


def _member_view(s: dict, access: dict, h: dict | None = None) -> dict:
    own = s.get("uploader_key") == access["key"]
    out = {"name": s["name"], "own": own, **{k: s.get(k, 0) for k in _MEMBER_PUBLIC},
           "other_player": bool(s.get("other_player")), "played_by": s.get("played_by")}
    out["discrepancy"] = _discrepancy(s, h) if h else []
    out["xp_h"] = _per_hour(out["xp"], out["duration_seconds"])
    out["balance_h"] = _per_hour(out["balance"], out["duration_seconds"])
    if own:
        out["kills"] = [{"key": c, "count": n} for c, n in s.get("kills", [])]
        out["loot"] = [{"key": k, "count": n} for k, n in s.get("loot", [])]
    return out


def _place_ref(place_id: int | None, cache: dict) -> dict | None:
    if not place_id:
        return None
    if place_id not in cache:
        p = store.place(place_id)
        cache[place_id] = {"id": p["id"], "name": p["name"]} if p else None
    return cache[place_id]


def _auto_subs(players: list[str], hunt_id: int, rosters: dict[int, dict[str, str]]) -> dict[str, str | None]:
    """0.23.0: 🔁 Substituto automático. A formação de costume são os lootsplits do mesmo tamanho com quase a mesma
    PT (no máximo 1 diferente). Quem aparece em 60% deles é "fixo". Se falta exatamente 1 fixo e entrou exatamente
    1 que não é fixo, esse é o substituto (no lugar de quem faltou). Precisa de pelo menos 2 lootsplits parecidos."""
    keys = {name_key(p): p for p in players}
    n = len(keys)
    if n < 2:
        return {}
    similar = [r for hid, r in rosters.items() if hid != hunt_id and len(r) == n and len(keys.keys() & r.keys()) >= n - 1]
    if len(similar) < 2:
        return {}
    counts: dict[str, int] = {}
    for r in similar:
        for k in r:
            counts[k] = counts.get(k, 0) + 1
    core = {k for k, c in counts.items() if c * 10 >= len(similar) * 6}
    extras = [k for k in keys if k not in core]
    missing = [k for k in core if k not in keys]
    if len(extras) != 1 or len(missing) != 1:
        return {}
    in_place = next(r[missing[0]] for r in similar if missing[0] in r)
    return {keys[extras[0]]: in_place}


def _tags_view(players: list[dict], tags: list[dict], auto: dict[str, str | None]) -> dict[str, dict]:
    """Marcações de cada jogador: {nome: {"other": bool, "played_by": str|None, "sub": {"auto": bool, "for": nome}}}."""
    by_key = {name_key(p["name"]): p["name"] for p in players}
    out: dict[str, dict] = {}
    manual = {}
    for t in tags:
        name = by_key.get(t["name_key"])
        if not name:
            continue
        if t["tag"] == "other":
            out.setdefault(name, {}).update(other=True, played_by=t["played_by"])
        else:
            manual[name] = t["tag"]
    for name in by_key.values():
        if manual.get(name) == "sub":
            out.setdefault(name, {})["sub"] = {"auto": False, "for": None}
        elif manual.get(name) != "nosub" and name in auto:
            out.setdefault(name, {})["sub"] = {"auto": True, "for": auto[name]}
        if name in out or manual.get(name):  # "não é substituto" sozinho também precisa chegar na tela
            out.setdefault(name, {})["sub_manual"] = manual.get(name)
    return out


def _is_orphan(h: dict, cache: dict) -> bool:
    """Lootsplit enviado por quem não estava na PT (antes da 0.23.0 isso era possível)."""
    up = h.get("uploader_key")
    if not up:
        return True
    if up not in cache:
        cache[up] = {name_key(c["name"]) for c in store.key_chars(up)}
    return not any(name_key(p["name"]) in cache[up] for p in h["players"])


def _hunts_out(hunts: list[dict], access: dict, kind: str = "hunt") -> list[dict]:
    """Lootsplits para a tela: local da hunt e, só para quem estava na PT, o que os membros compartilharam,
    as marcações (🤝 jogado por outra pessoa / 🔁 substituto) e se dá para assumir o lootsplit."""
    mine = {name_key(c["name"]) for c in store.key_chars(access["key"])}
    ids = [h["id"] for h in hunts if h.get("id")]
    inputs, members = store.inputs_for("hunt", ids), store.party_sessions_for(ids)
    tags = store.tags_for(kind, ids)
    party_ids = [h["id"] for h in hunts if h.get("id") and any(name_key(p["name"]) in mine for p in h["players"])]
    rosters = {}
    if kind == "hunt" and party_ids:
        names = {name_key(p["name"]) for h in hunts if h.get("id") in party_ids for p in h["players"]}
        rosters = store.rosters_with(sorted(names))
    places: dict = {}
    owners: dict = {}
    out = []
    for h in hunts:
        in_party = any(name_key(p["name"]) in mine for p in h["players"])
        hid = h.get("id")
        raw = dict(h)
        orphan = in_party and hid and _is_orphan(raw, owners)
        h = _public(h, access)
        h["place"] = _place_ref(h.get("place_id"), places)
        h["in_party"] = in_party
        h["inputs"] = [_input_view(i) for i in inputs.get(hid, [])] if in_party else []
        h["member_sessions"] = [_member_view(s, access, raw) for s in members.get(hid, [])] if in_party else []
        auto = {}
        if in_party:  # 0.24.0: a party registrada manda; sem ela, o palpite pelos lootsplits parecidos
            names = [p["name"] for p in raw["players"]]
            auto = _registered_subs(names, kind) or (_auto_subs(names, hid, rosters) if kind == "hunt" else {})
        h["tags"] = _tags_view(raw["players"], tags.get(hid, []), auto) if in_party else {}
        h["can_claim"] = bool(orphan) and not h["can_delete"]
        h["orphan"] = bool(orphan)
        out.append(h)
    return out


@app.get("/api/hunts/{name}")
def player_hunts(name: str, access: dict = Depends(require_session)):
    return {"hunts": _hunts_out(store.hunts_for_player(name), access)}


@app.delete("/api/hunt/{hunt_id}")
def delete_hunt(hunt_id: int, access: dict = Depends(require_session)):
    _delete_own("hunts", hunt_id, access)
    return {"deleted": hunt_id}


class RulesIn(BaseModel):
    excluded: Annotated[list[Name], Field(max_length=10)] = []
    fixed: Annotated[dict[Name, Annotated[int, Field(ge=0, le=100_000_000_000)]], Field(max_length=10)] = {}


class PaidIn(BaseModel):
    payer: Name
    receiver: Name
    paid: bool = True


def _load_hunt(kind: str, hunt_id: int) -> dict:
    h = store.hunt(hunt_id) if kind == "hunt" else store.boss_hunt(hunt_id)
    if h is None:
        raise HTTPException(404, "Lootsplit não encontrado (talvez tenha sido apagado).")
    return h


def _hunt_payload(kind: str, hunt_id: int, access: dict) -> dict:
    h = _load_hunt(kind, hunt_id)
    return _hunts_out([h], access)[0] if kind == "hunt" else _boss_hunt_view(h, access)


def _boss_hunt_view(h: dict, access: dict, owners: dict | None = None) -> dict:
    """Lootsplit de bosses para a tela (0.23.0: com as marcações e o "assumir")."""
    raw = dict(h)
    orphan = _is_orphan(raw, owners if owners is not None else {})
    out = _public(h, access)
    out["tags"] = _tags_view(raw["players"], store.tags_for("boss", [raw["id"]])[raw["id"]],
                             _registered_subs([p["name"] for p in raw["players"]], "boss"))
    out["orphan"] = orphan
    out["can_claim"] = orphan and not out["can_delete"]
    return out


def _set_rules(kind: str, hunt_id: int, body: RulesIn, access: dict) -> dict:
    """Regras de divisão: só quem enviou o lootsplit define. Zera as marcações de "já paguei"."""
    h = _load_hunt(kind, hunt_id)
    if h.get("uploader_key") != access["key"]:
        raise HTTPException(403, "Só quem enviou o lootsplit pode mudar as regras de divisão.")
    if not any(store.is_linked(access["key"], p["name"]) for p in h["players"]):  # 0.23.0: quem não estava na PT, não
        raise HTTPException(403, "Só quem estava na PT pode mudar as regras de divisão.")
    names = {p["name"].lower(): p["name"] for p in h["players"]}
    unknown = [n for n in [*body.excluded, *body.fixed] if n.lower() not in names]
    if unknown:
        raise HTTPException(422, f"{unknown[0]} não está nesse lootsplit.")
    excluded = sorted({names[n.lower()] for n in body.excluded})
    fixed = {names[n.lower()]: v for n, v in body.fixed.items() if names[n.lower()] not in excluded}
    if len(excluded) + len(fixed) >= len(names):
        raise HTTPException(422, "Pelo menos um jogador precisa continuar na divisão igual.")
    rules = {"excluded": excluded, "fixed": fixed} if excluded or fixed else None
    store.set_split_rules(kind, hunt_id, rules, access["key"])
    return {"hunt": _hunt_payload(kind, hunt_id, access)}


def _set_paid(kind: str, hunt_id: int, body: PaidIn, access: dict) -> dict:
    """'Já paguei' / 'recebi': quem marca precisa ter o pagador ou o recebedor vinculado ao código."""
    h = _load_hunt(kind, hunt_id)
    t = next((t for t in h["transfers"] if name_key(t["payer"]) == name_key(body.payer)
              and name_key(t["receiver"]) == name_key(body.receiver)), None)
    if t is None:
        raise HTTPException(404, "Essa transferência não existe nesse lootsplit.")
    if not (store.is_linked(access["key"], t["payer"]) or store.is_linked(access["key"], t["receiver"])):
        raise HTTPException(403, {"message": "Só quem paga ou quem recebe pode marcar essa transferência.",
                                  "hint": FORBIDDEN_HINT})
    store.set_paid(kind, hunt_id, t["payer"], t["receiver"], t["amount"], access["key"], body.paid)
    return {"hunt": _hunt_payload(kind, hunt_id, access)}


@app.post("/api/hunt/{hunt_id}/rules")
def hunt_rules(hunt_id: int, body: RulesIn, access: dict = Depends(require_session)):
    return _set_rules("hunt", hunt_id, body, access)


# ------------------------------------------------------------------ 0.23.0: marcações e "assumir lootsplit"
class TagIn(BaseModel):
    name: Name
    other: bool | None = None                           # 🤝 jogado por outra pessoa (só o dono do personagem)
    played_by: Name | None = None                       # quem jogou (opcional)
    sub: Literal["auto", "yes", "no"] | None = None     # 🔁 substituto (qualquer um da PT)


def _clean_name(name: str | None) -> str | None:
    if not name:
        return None
    n = " ".join(name.split())
    if not _VALID_NAME.fullmatch(n):
        raise HTTPException(422, "Nome de personagem inválido.")
    return n


def _set_tags(kind: str, hunt_id: int, body: TagIn, access: dict) -> dict:
    h = _load_hunt(kind, hunt_id)
    names = {name_key(p["name"]): p["name"] for p in h["players"]}
    target = names.get(name_key(body.name))
    if target is None:
        raise HTTPException(422, f"{body.name} não está nesse lootsplit.")
    if not any(store.is_linked(access["key"], n) for n in names.values()):
        raise HTTPException(403, {"message": "Só quem estava na PT pode marcar.", "hint": FORBIDDEN_HINT})
    if body.other is not None:
        if not store.is_linked(access["key"], target):
            raise HTTPException(403, "Só o dono do personagem marca que outra pessoa jogou.")
        store.set_tag(kind, hunt_id, target, "other", body.other, _clean_name(body.played_by), access["key"])
    if body.sub is not None:
        if body.sub == "auto":
            store.set_tag(kind, hunt_id, target, "sub", False)
            store.set_tag(kind, hunt_id, target, "nosub", False)
        else:
            store.set_tag(kind, hunt_id, target, "sub" if body.sub == "yes" else "nosub", True, None, access["key"])
    return {"hunt": _hunt_payload(kind, hunt_id, access)}


def _claim(kind: str, hunt_id: int, access: dict) -> dict:
    h = _load_hunt(kind, hunt_id)
    mine = [p["name"] for p in h["players"] if store.is_linked(access["key"], p["name"])]
    if not mine:
        raise HTTPException(403, {"message": "Só quem estava na PT pode assumir o lootsplit.", "hint": FORBIDDEN_HINT})
    if not _is_orphan(h, {}):
        raise HTTPException(409, "Esse lootsplit já foi enviado por alguém da PT.")
    store.claim_hunt(kind, hunt_id, access["key"], mine[0])
    return {"hunt": _hunt_payload(kind, hunt_id, access)}


@app.post("/api/hunt/{hunt_id}/tags")
def hunt_tags(hunt_id: int, body: TagIn, access: dict = Depends(require_session)):
    return _set_tags("hunt", hunt_id, body, access)


@app.post("/api/hunt/{hunt_id}/claim")
def hunt_claim(hunt_id: int, access: dict = Depends(require_session)):
    return _claim("hunt", hunt_id, access)


@app.post("/api/hunt/{hunt_id}/paid")
def hunt_paid(hunt_id: int, body: PaidIn, access: dict = Depends(require_session)):
    return _set_paid("hunt", hunt_id, body, access)


@app.post("/api/lootsplit/preview")
def lootsplit_preview(body: UploadIn, _: dict = Depends(require_session)):
    """Só calcula, sem salvar (usado quando o envio não é permitido)."""
    return _parse_party(body.raw_text)


# ------------------------------------------------------------------ 0.22.3: sem conta (Lootsplit e 2 notícias)
class PublicLootIn(BaseModel):
    raw_text: Annotated[str, Field(min_length=1, max_length=RAW_MAX)]


@app.post("/api/public/lootsplit")
def public_lootsplit(body: PublicLootIn):
    """Lootsplit para quem não tem conta: só calcula e devolve. Nada é gravado no banco."""
    return _parse_party(body.raw_text)


PUBLIC_NEWS = 2  # notícias que quem não tem conta pode ler (o resto pede a conta)


@app.get("/api/public/news")
def public_news(lang: str = ""):
    """As 2 notícias mais novas do tibia.com (pela TibiaData), no idioma escolhido na tela de entrada."""
    rows = _news_with_content(store.tibia_news_latest(("news",), PUBLIC_NEWS))
    _translate_news(rows, _lang(lang))
    return {"updated_at": store.meta("tibia_news_ok_at"), "news": [_news_out(r) for r in rows]}


@app.post("/api/lootsplit")
def lootsplit_upload(body: UploadIn, access: dict = Depends(require_session)):
    """0.23.0: só salva se um personagem do código está na PT (troca sozinho para ele) ou se o dono de um
    personagem da PT autorizou este jogador (fica salvo para o dono, marcado como jogado por outra pessoa)."""
    report = _parse_party(body.raw_text)
    require_uploader(body.nickname, access)
    got = _party_char(report["players"], body.nickname, access)
    if got:
        name, switched = got
        hunt, created = store.add_hunt(report, body.raw_text, name, access["key"])
        return {"created": created, "hunt": _hunts_out([hunt], access)[0], "rewards": grant_rewards(access["key"]),
                "saved_as": name, "switched_from": switched}
    grant = _grant_for([p["name"] for p in report["players"]], access, "party")
    if grant is None:
        raise HTTPException(403, {"message": NOT_IN_PARTY_UPLOAD, "hint": NOT_IN_PARTY_HINT})
    link, me = grant
    _in_link_window(link, report["started_at"])
    _spend_link(link)
    hunt, created = store.add_hunt(report, body.raw_text, link["name"], link["owner_key"], via="operator")
    tagged = store.set_tag("hunt", hunt["id"], link["name"], "other", True, me, access["key"])
    if not (created or tagged):
        store.refund_link(link["id"])
    return {"created": created, "hunt": _hunts_out([store.hunt(hunt["id"])], access)[0], "rewards": [],
            "saved_as": link["name"], "for_owner": True}


# ------------------------------------------------------------------ 0.20.0: local da hunt, Input Analyser e sessões da PT
PLACE_EDIT_LIMIT = 2  # trocas do local depois de definido; a primeira escolha não conta
PLACE_LOCKED = "Para alterar novamente entre em contato com o administrador."
INPUT_ONLY_HARDCORE = "O Player Novato não compartilha o Input Analyzer. Troque o tipo de player em ⚙️ Configurações."
SESSION_NOT_NOVATO = "O Player Novato não compartilha a sessão. Troque o tipo de player em ⚙️ Configurações."
INPUT_LOCKED = "Esse Input Analyzer já foi salvo e não pode ser editado."


class PlaceSet(BaseModel):
    place_id: int = Field(ge=1)


class RawIn(BaseModel):
    raw_text: Annotated[str, Field(min_length=1, max_length=RAW_MAX)]


class MemberRawIn(RawIn):
    nickname: Name
    for_char: Name | None = None  # 0.23.0: jogador autorizado juntando a sessão pelo dono


def _change_place(table: str, row_id: int, place_id: int, access: dict) -> dict:
    """Define o local (grátis) ou troca (no máximo 2 vezes; depois só o administrador)."""
    st = store.place_state(table, row_id)
    if st is None:
        raise HTTPException(404, "Não encontrado (talvez tenha sido apagado).")
    if st["uploader_key"] != access["key"]:
        raise HTTPException(403, "Só quem enviou pode definir o local da hunt.")
    place = store.place(place_id)
    if place is None:
        raise HTTPException(404, "Hunt não encontrada.")
    if st["place_id"] != place_id:
        is_change = st["place_id"] is not None
        if is_change and st["place_edits"] >= PLACE_EDIT_LIMIT:
            raise HTTPException(403, PLACE_LOCKED)
        store.update_place(table, row_id, place_id, is_change)
        st = store.place_state(table, row_id)
    return {"place": {"id": place["id"], "name": place["name"]}, "place_edits": st["place_edits"],
            "locked": st["place_edits"] >= PLACE_EDIT_LIMIT}


def _parse_input(raw: str) -> dict:
    try:
        return damage_core.parse_input(raw)
    except ParseError as e:
        raise HTTPException(422, str(e))


def _require_type(access: dict, allowed: tuple, message: str) -> None:
    if store.player_type(access["key"]) not in allowed:
        raise HTTPException(403, message)


def _party_member(hunt_id: int, nickname: str, access: dict) -> tuple[dict, str]:
    """Personagem do código que estava nesse lootsplit (0.23.0: troca sozinho para o personagem certo)."""
    h = _load_hunt("hunt", hunt_id)
    require_uploader(nickname, access)
    got = _party_char(h["players"], nickname, access)
    if got is None:
        raise HTTPException(403, {"message": NOT_IN_PARTY_HUNT, "hint": "Use o personagem que estava na PT."})
    return h, got[0]


NOT_IN_PARTY_HUNT = "Seu personagem não está nesse lootsplit."


@app.post("/api/hunt/{hunt_id}/place")
def hunt_place(hunt_id: int, body: PlaceSet, access: dict = Depends(require_session)):
    return _change_place("hunts", hunt_id, body.place_id, access)


@app.post("/api/hunt/{hunt_id}/input")
def hunt_input(hunt_id: int, body: MemberRawIn, access: dict = Depends(require_session)):
    """Input Analyser de um membro da PT (só Player Hardcore). Salvou, não edita."""
    _require_type(access, _sharing_types(), INPUT_ONLY_HARDCORE)
    _, name = _party_member(hunt_id, body.nickname, access)
    data = _parse_input(body.raw_text)
    row, created = store.add_input("hunt", hunt_id, name, data, access["key"])
    if not created:
        raise HTTPException(409, INPUT_LOCKED)
    return {"input": _input_view(row), "hunt": _hunt_payload("hunt", hunt_id, access)}


@app.post("/api/hunt/{hunt_id}/session")
def hunt_member_session(hunt_id: int, body: MemberRawIn, access: dict = Depends(require_session)):
    """Hunt Session Analyser de um membro da PT junto ao lootsplit (Player Comum ou Hardcore).
    0.23.0: o jogador autorizado (for_char) junta pelo dono; vale o tipo de player do dono."""
    try:
        session = parse_solo_session(body.raw_text)
    except ParseError as e:
        raise HTTPException(422, str(e))
    link = None
    if body.for_char:
        h = _load_hunt("hunt", hunt_id)
        require_uploader(body.nickname, access)
        grant = _grant_for([body.for_char], access, "party")
        if grant is None or grant[0]["name_key"] not in {name_key(p["name"]) for p in h["players"]}:
            raise HTTPException(403, NO_GRANT)
        link, me = grant
        if store.player_type(link["owner_key"]) not in _sharing_types():
            raise HTTPException(403, SESSION_NOT_NOVATO)
        name, owner_key, who = link["name"], link["owner_key"], _who("operator", me)
    else:
        _require_type(access, _sharing_types(), SESSION_NOT_NOVATO)
        h, name = _party_member(hunt_id, body.nickname, access)
        owner_key, who = access["key"], None
    ended = h.get("ended_at")
    if ended and not boss_core.overlaps(session.started_at, session.ended_at, h["started_at"], ended):
        raise HTTPException(422, "Essa sessão não é do mesmo horário do lootsplit.")
    if link:
        _spend_link(link)
    _, created = store.add_party_session(hunt_id, name, session.to_dict(), owner_key, who)
    if not created:
        if link:
            store.refund_link(link["id"])
        raise HTTPException(409, "Você já juntou a sua sessão a esse lootsplit." if not link
                            else f"A sessão de {name} já está junto a esse lootsplit.")
    return {"hunt": _hunt_payload("hunt", hunt_id, access)}


# ------------------------------------------------------------------ conquistas e sequência de dias
def _upload_days(key: str) -> set:
    return {ach.local_day(t) for t in store.upload_times(key)}


def grant_rewards(key: str) -> list[dict]:
    """Concede (uma vez só) +7 dias de validade a cada 30 dias seguidos enviando hunts/sessões."""
    out = []
    for rid in ach.streak_rewards(_upload_days(key), store.pause_days(key)):
        r = store.grant_reward(key, rid, ach.STREAK_REWARD_DAYS)
        if r:
            out.append(r)
    return out


def streak_payload(key: str) -> dict:
    info = ach.streak_info(_upload_days(key), frozen=store.pause_days(key))
    current = store.validate_key(key) or {}
    info.update(rewards=store.rewards(key), expires_at=user_expires(current))
    return info


@app.get("/api/streak")
def streak(access: dict = Depends(require_session)):
    """Sequência de dias do código de quem está vendo (cartão do Início)."""
    granted = grant_rewards(access["key"])
    return {**streak_payload(access["key"]), "granted": granted}


@app.get("/api/achievements/{name}")
def achievements(name: str, access: dict = Depends(require_session)):
    """Conquistas do personagem (qualquer um pode ver) + a sequência de dias do código de quem está vendo."""
    sessions, _ = _enriched_sessions(name, access)
    hunts = store.hunts_for_player(name)
    granted = grant_rewards(access["key"])
    items = ach.evaluate(name, sessions, hunts, store.sold_count(name), store.pause_days(store.char_owner(name) or ""))
    return {"name": name, "achievements": items, "unlocked": sum(a["unlocked"] for a in items), "total": len(items),
            "streak": streak_payload(access["key"]), "granted": granted}


@app.get("/api/vocations")
def vocations(names: str = "", _: dict = Depends(require_session)):
    """Vocação de até 20 personagens (para colorir a PT). Usa o cache; consulta o TibiaData só os que faltam."""
    wanted = [" ".join(n.split()) for n in names.split(",") if n.strip()][:20]
    wanted = [n for n in wanted if _VALID_NAME.fullmatch(n)]
    known = store.char_infos(wanted)
    out, fetched = {}, 0
    for n in wanted:
        info = known.get(name_key(n))
        if info is None and fetched < 10:
            fetched += 1
            try:
                ch = lookup_character(n)
            except HTTPException:
                ch = None
            info = {"vocation": ch.vocation, "level": ch.level} if ch else None
        out[n] = info["vocation"] if info else None
    return out


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



def _per_hour(value: int, seconds: int) -> int:
    return round(value * 3600 / seconds) if seconds else 0


def _records(sessions: list[dict]) -> list[dict]:
    sessions = [s for s in sessions if not s.get("other_player")]  # 0.23.0: recorde é de quem jogou no próprio
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


_exp_cache: dict[str, tuple[float, tuple[int, int] | None]] = {}


def current_experience(ch, sessions: list[dict]) -> tuple[int, str]:
    """XP atual do personagem e a origem ("highscore" ou "level").

    Usa o highscore de experiência do mundo (top 1000, atualizado ~1x/dia) e soma
    o XP das sessões enviadas depois da atualização. Fora do top 1000, parte do
    início do level atual (tabela oficial de experiência).
    """
    level = ch.level
    k = name_key(ch.name)
    hit = _exp_cache.get(k)
    if hit and time.monotonic() - hit[0] < 1800:
        hs = hit[1]
    else:
        hs = fetch_experience(ch.name, ch.world, level) if ch.world else None
        _exp_cache[k] = (time.monotonic(), hs)
    floor, ceil = xp_at(level), xp_at(level + 1) - 1
    if not hs:
        return floor, "level"
    xp, age_min = hs
    since = (datetime.now() - timedelta(minutes=age_min)).isoformat()
    xp += sum(s["xp"] for s in sessions if (s.get("ended_at") or s["started_at"]) >= since)
    if level_for_xp(xp) < level:  # highscore antigo demais: o level do site é mais novo
        return floor, "level"
    return min(max(xp, floor), ceil), "highscore"


def _forecast(name: str, sessions: list[dict]) -> dict | None:
    try:
        ch = lookup_character(name)
    except HTTPException:
        ch = None
    if not ch:
        return None
    level = ch.level
    cur, source = current_experience(ch, sessions)
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    xp_week = sum(s["xp"] for s in sessions if s["started_at"] >= week_ago)
    secs = sum(s["duration_seconds"] for s in sessions)
    xp_h = _per_hour(sum(s["xp"] for s in sessions), secs)
    per_day = xp_week / 7
    lvl_size = xp_to_next_level(level)
    pct = round((cur - xp_at(level)) * 100 / lvl_size, 1) if lvl_size else 0

    def row(target: int) -> dict:
        need = max(0, xp_at(target) - cur)
        return {"level": target, "total_xp": xp_at(target), "xp_left": need,
                "days": round(need / per_day, 1) if per_day else None,
                "hours": round(need / xp_h, 1) if xp_h else None}

    targets = [level + i for i in range(1, 6)]
    for step in (50, 100):
        m = (level // step + 1) * step
        if m not in targets:
            targets.append(m)
    table = [row(t) for t in sorted(targets)]
    nxt = table[0]
    mark = (level // 50 + 1) * 50
    mrow = next(r for r in table if r["level"] == mark)
    return {
        "level": level, "xp_now": cur, "xp_source": source, "level_pct": pct,
        "xp_per_day": round(per_day), "xp_per_hour": xp_h,
        "next_level": level + 1, "xp_next_level": nxt["xp_left"],
        "days_next_level": nxt["days"], "hours_next_level": nxt["hours"],
        "mark": mark, "xp_mark": mrow["xp_left"], "days_mark": mrow["days"],
        "table": table,
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


def _enriched_sessions(name: str, access: dict) -> tuple[list[dict], dict]:
    """Sessões do Stacker com hunt, criaturas, itens, valor do loot e lucro líquido; e os preços usados."""
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
    # 0.20.0: Input Analyser de cada sessão (só aparece para quem enviou)
    inputs = store.inputs_for("solo", [s["id"] for s in sessions if s["can_delete"]])
    for s in sessions:
        got = inputs.get(s["id"]) or []
        s["input"] = _input_view(got[0]) if got else None
        s["place_locked"] = s.get("place_edits", 0) >= PLACE_EDIT_LIMIT
    return sessions, prices


# 0.20.0: quantidade de criaturas mortas e de itens coletados é do dono do personagem; os outros veem só o geral
_OWNER_ONLY_SESSION = ("kills", "loot", "loot_value", "net_profit", "input", "place_edits", "place_locked",
                       "played_by", "via", "content_hash", "other_player")  # 0.23.0: quem jogou fica só com o dono


def _generic_only(data: dict) -> dict:
    for s in data["sessions"]:
        for k in _OWNER_ONLY_SESSION:
            s.pop(k, None)
    p = data["period"]
    p.update(items=[], kills=[], loot_value=0, net_profit=0, net_profit_per_hour=0, unpriced=0)
    data.update(prices={}, goals=[], sell=[], alerts=[], by_place=None,
                records=[r for r in data["records"] if r["label"] not in ("Maior lucro líquido/h", "Maior loot numa sessão")])
    return data


def _by_place(sessions: list[dict]) -> dict | None:
    """📊 Comparar as suas hunts: XP/h e balance/h de cada local (sessões de 10 min ou mais)."""
    acc: dict[int, dict] = {}
    for s in sessions:
        if not s.get("place") or s["duration_seconds"] < COMPARE_MIN_SECONDS or s.get("other_player"):
            continue
        a = acc.setdefault(s["place"]["id"], {"place": s["place"]["name"], "sessions": 0, "seconds": 0, "xp": 0,
                                              "balance": 0, "best_xp_h": 0, "best_gold_h": None})
        a["sessions"] += 1
        a["seconds"] += s["duration_seconds"]
        a["xp"] += s["xp"]
        a["balance"] += s["balance"]
        a["best_xp_h"] = max(a["best_xp_h"], _per_hour(s["xp"], s["duration_seconds"]))
        g = _per_hour(s["balance"], s["duration_seconds"])
        a["best_gold_h"] = g if a["best_gold_h"] is None else max(a["best_gold_h"], g)
    rows = []
    for a in acc.values():
        rows.append({"place": a["place"], "sessions": a["sessions"], "hours": round(a["seconds"] / 3600, 1),
                     "xp_h": _per_hour(a["xp"], a["seconds"]), "gold_h": _per_hour(a["balance"], a["seconds"]),
                     "best_xp_h": a["best_xp_h"], "best_gold_h": a["best_gold_h"] or 0})
    if not rows:
        return None
    rows.sort(key=lambda r: -r["xp_h"])
    return {"rows": rows, "best_xp": rows[0]["place"], "best_gold": max(rows, key=lambda r: r["gold_h"])["place"]}


@app.get("/api/stacker/{name}")
def stacker(name: str, period: int = 7, access: dict = Depends(require_session)):
    period = period if period in PERIOD_DAYS else 7
    sessions, prices = _enriched_sessions(name, access)
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
    owner = store.is_linked(access["key"], name)
    data = {
        "is_owner": owner,
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
        "by_place": _by_place(sessions),
    }
    return data if owner else _generic_only(data)


def require_owner(name: str, access: dict) -> None:
    if not store.is_linked(access["key"], name):
        raise HTTPException(403, "Só o dono do personagem pode alterar isso.")


class GoalIn(BaseModel):
    period: Literal["day", "week"]
    metric: Literal["xp", "loot"]
    target: int | None = Field(default=None, ge=0, le=10**13)


@app.post("/api/goals/{name}")
def set_goal(name: str, body: GoalIn, access: dict = Depends(require_session)):
    require_owner(name, access)
    if body.period not in ("day", "week") or body.metric not in ("xp", "loot"):
        raise HTTPException(422, "Meta inválida.")
    store.set_goal(name, body.period, body.metric, body.target if body.target and body.target > 0 else None)
    return {"goals": store.goals(name)}


class SellIn(BaseModel):
    item: Annotated[str, Field(min_length=1, max_length=80)]
    target: int | None = Field(default=None, ge=0, le=10_000_000)


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
    name: Annotated[str, Field(max_length=60)]
    city: Annotated[str, Field(max_length=40)] | None = None


# Nomes de hunt criados por usuários: letras (com acento), números, espaço e pontuação simples.
_PLACE_NAME = re.compile(r"[\w À-ÿ'().,&/-]+")
PLACES_PER_KEY = 30


@app.get("/api/places")
def list_places(_: dict = Depends(require_session)):
    return store.places()


@app.post("/api/places")
def create_place(body: PlaceIn, access: dict = Depends(require_session)):
    name = " ".join(body.name.split())
    city = " ".join((body.city or "").split()) or None
    if not 3 <= len(name) <= 60:
        raise HTTPException(422, "Nome da hunt deve ter de 3 a 60 caracteres.")
    if not _PLACE_NAME.fullmatch(name) or (city and not _PLACE_NAME.fullmatch(city)):
        raise HTTPException(422, "Use só letras, números, espaços e pontuação simples no nome da hunt.")
    if store.places_created_by(access["key"]) >= PLACES_PER_KEY:
        raise HTTPException(429, f"Limite de {PLACES_PER_KEY} hunts criadas por código de acesso atingido.")
    return store.create_place(name, city, access["key"])


@app.post("/api/stacker/session/{session_id}/place")
def set_place(session_id: int, body: PlaceSet, access: dict = Depends(require_session)):
    """Local da sessão: escolher é livre; trocar depois, só 2 vezes (0.20.0)."""
    out = _change_place("solo_sessions", session_id, body.place_id, access)
    row = store.solo_session(session_id)
    out["compare"] = _compare_with_average(row["name"], row) if row else None
    return out


@app.post("/api/stacker/session/{session_id}/input")
def solo_input(session_id: int, body: RawIn, access: dict = Depends(require_session)):
    """Input Analyser da sessão do Stacker (só Player Hardcore). Salvou, não edita."""
    _require_type(access, _sharing_types(), INPUT_ONLY_HARDCORE)
    row = store.solo_session(session_id)
    if row is None:
        raise HTTPException(404, "Sessão não encontrada.")
    if row["uploader_key"] != access["key"]:
        raise HTTPException(403, "Só quem enviou a sessão pode juntar o Input Analyzer.")
    data = _parse_input(body.raw_text)
    saved, created = store.add_input("solo", session_id, row["name"], data, access["key"])
    if not created:
        raise HTTPException(409, INPUT_LOCKED)
    return {"input": _input_view(saved)}


def _place_stats(mode: str, **kw) -> list[dict]:
    """0.22.0: hunts solo comparam com hunts solo; hunts em party, com hunts em party."""
    return store.party_place_stats(**kw) if mode == "party" else store.place_stats(**kw)


@app.get("/api/places/ranking")
def places_ranking(sort: str = "xp", min_level: int | None = None, max_level: int | None = None, mode: str = "solo",
                   _: dict = Depends(require_session)):
    mode = "party" if mode == "party" else "solo"
    rows = _place_stats(mode, min_level=min_level, max_level=max_level)
    key = "gold_per_hour" if sort == "gold" else "xp_per_hour"
    return {"sort": sort, "mode": mode, "rows": sorted(rows, key=lambda r: -r[key])}


@app.get("/api/places/mine")
def places_mine(nick: str, mode: str = "solo", access: dict = Depends(require_session)):
    """Histórico do próprio personagem por hunt (solo ou party), da que mais rende XP/h para a que menos rende."""
    mode = "party" if mode == "party" else "solo"
    if not store.is_linked(access["key"], nick):
        return {"mode": mode, "rows": []}
    rows = _place_stats(mode, name=nick)
    return {"mode": mode, "rows": sorted(rows, key=lambda r: (-r["xp_per_hour"], -r["gold_per_hour"]))}


@app.get("/api/places/compare")
def places_compare(ids: str, nick: str = "", mode: str = "solo", access: dict = Depends(require_session)):
    """Básico (XP/h, gold/h, level) para todas as hunts. Detalhes (criaturas, itens, dano) só das hunts do próprio
    player; o dano recebido de todos (Input Analyzers públicos) só para o Player Hardcore."""
    mode = "party" if mode == "party" else "solo"
    place_ids = [int(i) for i in ids.split(",") if i.strip().isdigit()][:3]
    general = {r["id"]: r for r in _place_stats(mode, place_ids=place_ids)}
    own = bool(nick) and store.is_linked(access["key"], nick)  # "Seu ..." só do próprio personagem
    mine = {r["id"]: r for r in _place_stats(mode, place_ids=place_ids, name=nick)} if own else {}
    hardcore = store.player_type(access["key"]) in _hardcore_types()
    out = []
    for pid in place_ids:
        p = store.place(pid)
        if not p:
            continue
        row = {"place": p, "stats": general.get(pid), "mine": mine.get(pid), "top_kills": [], "top_items": [],
               "my_damage": None, "damage": None}
        if mine.get(pid):
            kills, loot = store.party_place_top(pid, nick) if mode == "party" else store.place_top(pid, name=nick)
            loot_keys = [store.resolve_item(k) for k, _ in loot]
            prices = store.price_info(loot_keys, access["key"])
            items = _sum_counts((store.resolve_item(k), n) for k, n in loot)
            for it in items:
                it["value"] = it["count"] * prices[it["key"]]["unit_price"]
                it["name"] = prices[it["key"]]["name"]
            top_items = sorted((it for it in items if it["value"] > 0), key=lambda it: -it["value"])[:5]
            row["top_kills"] = [{"key": k, "count": n} for k, n in kills]
            row["top_items"] = [{"key": it["key"], "name": it["name"], "count": it["count"], "value": it["value"]} for it in top_items]
            my_inputs = store.inputs_for_place(pid, mode=mode, name=nick)
            row["my_damage"] = damage_core.combine(my_inputs) if my_inputs else None
        if hardcore:
            inputs = store.inputs_for_place(pid, mode=mode)
            row["damage"] = damage_core.combine(inputs) if inputs else None
        out.append(row)
    return out


# ------------------------------------------------------------------ 🥇 ranking entre amigos (só quem aceitar)
RANKING_METRICS = {"xp", "xp_h", "profit", "profit_h", "hours"}


class RankingJoinIn(BaseModel):
    join: bool


@app.get("/api/ranking")
def ranking(period: int = 7, metric: str = "xp", nick: str = "", others: int = 0, _: dict = Depends(require_session)):
    """Ranking das sessões do Stacker de quem entrou no ranking. Quem não entrou nunca aparece.
    0.23.0: sessões jogadas por outra pessoa só entram com others=1."""
    period = period if period in (7, 30) else 7
    metric = metric if metric in RANKING_METRICS else "xp"
    since = (datetime.now() - timedelta(days=period)).isoformat(timespec="seconds")
    rows = []
    for r in store.ranking_rows(since, include_others=bool(others)):
        secs = r["seconds"]
        rows.append({"name": r["name"], "vocation": r["vocation"], "level": r["level"], "sessions": r["sessions"],
                     "xp": r["xp"], "profit": r["balance"], "hours": round(secs / 3600, 1),
                     "xp_h": _per_hour(r["xp"], secs), "profit_h": _per_hour(r["balance"], secs)})
    rows.sort(key=lambda r: (-r[metric], r["name"]))
    return {"period": period, "metric": metric, "rows": rows, "joined": bool(nick) and store.ranking_member(nick),
            "others": bool(others)}


@app.post("/api/ranking/{name}")
def ranking_join(name: str, body: RankingJoinIn, access: dict = Depends(require_session)):
    """Entrar/sair do ranking: só o dono do personagem decide."""
    real = require_uploader(name, access)
    store.ranking_join(real, body.join)
    return {"joined": store.ranking_member(real)}


# ------------------------------------------------------------------ 0.25.0: XP do TibiaData (30/90 dias) e ranking pessoal
XP_DAYS = (30, 90)
XP_TRACK_START = date(2026, 11, 21)              # o tracker só conta XP a partir deste dia
XP_NOTE_UNTIL = XP_TRACK_START + timedelta(days=90)  # a observação com a data some sozinha depois disso
XP_UPDATE_HOUR = 9                                # snapshot diário às 09h (horário de Brasília, UTC-3)
BRT = timezone(timedelta(hours=-3))


class CustomRankIn(BaseModel):
    character: Name


class TrustIn(BaseModel):
    character: Name
    manual: bool = True


def _scan_now() -> dict:
    """0.26.0: varredura de todos os mundos (XP, skills e demais categorias). Roda 1 vez por dia, às 09h BRT.
    Guarda só os personagens acompanhados (cadastrados no site e citados em party session) e compara com o dia anterior."""
    day = datetime.now(BRT).date().isoformat()
    tracked = {name_key(n): n for n in store.xp_tracked_names()}
    return rankscan.run_scan(store, day=day, tracked=tracked, fetch_page=fetch_highscore_page,
                             fetch_worlds=fetch_worlds_list, key_fn=name_key, categories=HIGHSCORE_CATEGORIES)


def _xp_snapshot_all() -> int:
    """Compatibilidade: o snapshot de XP agora sai da varredura. Devolve quantos acompanhados foram encontrados."""
    return _scan_now().get("matched", 0)


def _seconds_until_next_update(now: datetime | None = None) -> float:
    """Segundos até o próximo 09h BRT (hoje, se ainda não passou; senão amanhã)."""
    agora = now or datetime.now(BRT)
    alvo = agora.replace(hour=XP_UPDATE_HOUR, minute=0, second=0, microsecond=0)
    if alvo <= agora:
        alvo += timedelta(days=1)
    return (alvo - agora).total_seconds()


def _xp_rows(names: list[str], days: int) -> list[dict]:
    """XP ganho nos últimos `days` dias, só a partir de 21/11/2026 e do 1º ponto de cada personagem.
    partial = a contagem começou depois da janela (histórico ainda curto)."""
    hoje = datetime.now(BRT).date()
    janela = (hoje - timedelta(days=days)).isoformat()
    corte = XP_TRACK_START.isoformat()
    inicio = max(janela, corte)
    rows = []
    for n in names:
        latest = store.xp_latest(n)
        if latest is None:
            rows.append({"name": n, "xp": None, "gain": None, "since": None, "partial": True})
            continue
        # referência: último ponto até o início da contagem, desde que não seja anterior a 21/11/2026;
        # se não houver, o primeiro ponto a partir daí; se ainda não houver nenhum, ganho zero por enquanto
        ref = store.xp_baseline(n, inicio)
        if ref is None or ref["day"] < corte:
            ref = store.xp_first_from(n, inicio) or latest
        base = ref
        rows.append({"name": n, "xp": latest["xp"], "gain": latest["xp"] - base["xp"], "since": base["day"],
                     "partial": base["day"] > janela})
    rows.sort(key=lambda r: (r["gain"] is None, -(r["gain"] or 0), r["name"].lower()))
    return rows


@app.get("/api/xp-ranking")
def xp_ranking(days: int = 30, scope: str = "board", access: dict = Depends(require_session)):
    """scope=board: todos os personagens cadastrados no site (público). scope=mine: a lista pessoal de quem pediu.
    Lê só os snapshots guardados às 09h BRT; não consulta o TibiaData."""
    days = days if days in XP_DAYS else 30
    if scope == "mine":
        names = [c["name"] for c in store.custom_list(access["key"])]
    else:
        names = store.xp_board_names()
    hoje = datetime.now(BRT).date()
    return {"days": days, "scope": "mine" if scope == "mine" else "board", "rows": _xp_rows(names, days),
            "update": {"hour": XP_UPDATE_HOUR, "tz": "America/Sao_Paulo (UTC-3)"},
            "track_start": XP_TRACK_START.isoformat(),
            "note_visible": hoje < XP_NOTE_UNTIL, "note_until": XP_NOTE_UNTIL.isoformat()}


@app.post("/api/xp-ranking/mine")
def xp_mine_add(body: CustomRankIn, access: dict = Depends(require_session)):
    nome = " ".join(body.character.split())
    if not _VALID_NAME.fullmatch(nome):
        raise HTTPException(422, "Nome de personagem inválido.")
    store.custom_add(access["key"], nome)
    return {"ok": True, "names": [c["name"] for c in store.custom_list(access["key"])]}


@app.delete("/api/xp-ranking/mine/{name}")
def xp_mine_remove(name: str, access: dict = Depends(require_session)):
    store.custom_remove(access["key"], " ".join(name.split()))
    return {"ok": True, "names": [c["name"] for c in store.custom_list(access["key"])]}


def _admin_gate(request: Request, x_admin_token: str = Header(default="")) -> None:
    require_admin(request, x_admin_token)  # definido mais abaixo; chamado só na requisição


@app.post("/api/admin/xp-snapshot", dependencies=[Depends(_admin_gate)])
def xp_snapshot_now():
    """Roda a varredura agora, sem esperar as 09h (pode repetir: a comparação é sempre com o último valor guardado)."""
    return _scan_now()


@app.get("/api/admin/scan-stats", dependencies=[Depends(_admin_gate)])
def scan_stats():
    """Painel de admin: tempo da primeira carga, tempo de cada atualização e totais."""
    runs = store.scan_runs(30)
    primeira = next((r for r in reversed(store.scan_runs(1000)) if r["first_load"] and r["ok"]), None)
    ok = [r for r in runs if r["ok"]]
    return {
        "first_load": primeira,
        "last": ok[0] if ok else None,
        "avg_seconds": round(sum(r["seconds"] for r in ok) / len(ok), 1) if ok else None,
        "tracked_players": store.rank_count(),
        "runs": runs,
        "schedule": {"hour": XP_UPDATE_HOUR, "tz": "America/Sao_Paulo (UTC-3)"},
    }


@app.post("/api/admin/char-trust", dependencies=[Depends(_admin_gate)])
def char_trust_admin(body: TrustIn):
    """Verificação manual pelo administrador: o personagem entra sem depender do TibiaData, sempre."""
    nome = " ".join(body.character.split())
    if not _VALID_NAME.fullmatch(nome):
        raise HTTPException(422, "Nome de personagem inválido.")
    store.trust_upsert(nome, manual=body.manual)
    return {"ok": True, "character": nome, "trust": store.trust_info(nome)}


# ------------------------------------------------------------------ 0.26.1: rankings (geral, por jogador)
RANK_PAGE = 100
# XP aqui NUNCA é o total do personagem: o ranking de XP é sempre o ganho em 30/90 dias (aba Usuários do Artemis)
RANK_METRICS = ["level", "magiclevel", "shielding", "distancefighting", "clubfighting", "swordfighting",
                "axefighting", "fistfighting", "fishing", "achievements", "charmpoints", "goshnarstaint",
                "loyaltypoints", "dromescore", "bosspoints", "bountypoints", "weeklytasks", "phosphorusrecord"]


@app.get("/api/rank/geral")
def rank_geral(metric: str = "level", page: int = 1, _: dict = Depends(require_session)):
    """Ranking geral: top 1000 por métrica, de todos os mundos. 100 por página."""
    metric = metric if metric in RANK_METRICS else "level"
    page = min(max(page, 1), 10)
    rows = store.rank_top_page(metric, (page - 1) * RANK_PAGE, RANK_PAGE)
    return {"metric": metric, "page": page, "pages": 10, "per_page": RANK_PAGE, "day": store.rank_top_day(),
            "metrics": RANK_METRICS, "rows": rows}


@app.get("/api/rank/player/{name}")
def rank_player(name: str, _: dict = Depends(require_session)):
    """Janela pública de um jogador acompanhado: XP diária, mensal e trimestral (a partir de 21/11/2026), HP/mana/cap
    calculados e alterações de skill, achievements e charm points (sem trocas de mundo)."""
    p = store.rank_player(" ".join(name.split()))
    if p is None:
        raise HTTPException(404, "Personagem não acompanhado.")
    corte = XP_TRACK_START.isoformat()
    pts = store.xp_series(p["name"], corte)
    diarios = [{"day": b["day"], "gain": b["xp"] - a["xp"]} for a, b in zip(pts, pts[1:])]
    mensais, trimestrais = {}, {}
    for d in diarios:
        ano, mes = d["day"][:4], int(d["day"][5:7])
        mensais[f"{ano}-{mes:02d}"] = mensais.get(f"{ano}-{mes:02d}", 0) + d["gain"]
        tri = f"{ano}-T{(mes - 1) // 3 + 1}"
        trimestrais[tri] = trimestrais.get(tri, 0) + d["gain"]
    # alterações de skills/achievements/charm points; o XP total não aparece (XP é só o ganho em 30/90 dias)
    mudancas = [m for m in store.rank_changes_for(p["name"], corte)
                if m["kind"] != "world" and m["category"] != "experience"]
    return {
        "name": p["name"], "world": p["world"], "vocation": p["vocation"], "level": p["level"],
        "calc": vocation_core.calcular(p["level"], p["vocation"]),
        "xp": {"d30": _xp_rows([p["name"]], 30)[0], "d90": _xp_rows([p["name"]], 90)[0]},
        "charts": {"daily": diarios[-90:],
                   "monthly": [{"month": k, "gain": v} for k, v in sorted(mensais.items())],
                   "quarterly": [{"quarter": k, "gain": v} for k, v in sorted(trimestrais.items())]},
        "changes": mudancas[:60],
        "track_start": corte, "updated_day": p["updated_day"],
    }


class PriceIn(BaseModel):
    item: Annotated[str, Field(min_length=1, max_length=80)]
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
    switched, link, who, owner_key = None, None, None, access["key"]
    if body.for_char:  # 0.23.0: jogador autorizado enviando pelo dono
        grant = _grant_for([body.for_char], access, "solo")
        if grant is None:
            raise HTTPException(403, NO_GRANT)
        link, me = grant
        _in_link_window(link, session.started_at)
        name, owner_key, who = link["name"], link["owner_key"], _who("operator", me)
    else:  # 0.23.0: a sessão é do mesmo horário de um lootsplit de outro personagem seu? Salva nele.
        other = _overlapping_char(session.started_at, session.ended_at, access)
        if other and name_key(other) != name_key(name):
            switched, name = name, other
    _check_duplicate("solo_sessions", session.to_dict(), name, owner_key)
    if body.place_id is not None and store.place(body.place_id) is None:
        raise HTTPException(404, "Hunt não encontrada.")
    try:  # level do personagem no momento do envio (para o level médio das hunts)
        ch = lookup_character(name)
        level = ch.level if ch else None
    except HTTPException:
        level = None
    if link:
        _spend_link(link)
    row, created = store.add_solo(name, session.fingerprint(name), session.to_dict(), owner_key, body.raw_text,
                                  body.place_id, level, who)
    row.pop("raw_text", None)
    if link:
        if not created:
            store.refund_link(link["id"])
        return {"created": created, "session": _public(row, access), "rewards": [], "rare": [], "compare": None,
                "saved_as": name, "for_owner": True}
    return {"created": created, "session": _public(row, access), "rewards": grant_rewards(access["key"]),
            "rare": _session_rare(session, False, access) if created else [],
            "compare": _compare_with_average(name, row), "saved_as": name, "switched_from": switched}


COMPARE_MIN_SECONDS = 600  # sessões curtas distorcem a média (mesmo corte do ranking de Hunts)


def _compare_with_average(name: str, row: dict) -> dict | None:
    """Sessão x média do próprio personagem na mesma hunt (XP/h e balance/h)."""
    place = store.place(row["place_id"]) if row.get("place_id") else None
    if place is None or row["duration_seconds"] < COMPARE_MIN_SECONDS or row.get("other_player"):
        return None
    others = [s for s in store.solo_for_player(name)  # 0.23.0: sem as sessões jogadas por outra pessoa
              if s["place_id"] == place["id"] and s["id"] != row["id"] and s["duration_seconds"] >= COMPARE_MIN_SECONDS
              and not s.get("other_player")]
    out = {"place": place["name"], "sessions": len(others),
           "xp_h": _per_hour(row["xp"], row["duration_seconds"]),
           "gold_h": _per_hour(row["balance"], row["duration_seconds"])}
    if not others:
        return out
    secs = sum(s["duration_seconds"] for s in others)
    out["avg_xp_h"] = _per_hour(sum(s["xp"] for s in others), secs)
    out["avg_gold_h"] = _per_hour(sum(s["balance"] for s in others), secs)

    def pct(v: int, avg: int) -> int | None:
        return round((v - avg) * 100 / abs(avg)) if avg else None
    out["xp_pct"], out["gold_pct"] = pct(out["xp_h"], out["avg_xp_h"]), pct(out["gold_h"], out["avg_gold_h"])
    return out


@app.delete("/api/stacker/session/{session_id}")
def delete_solo(session_id: int, access: dict = Depends(require_session)):
    _delete_own("solo_sessions", session_id, access)
    return {"deleted": session_id}


# ------------------------------------------------------------------ 👑 rotação de bosses
BOSS_PRIVATE = "Os dados de bosses são privados: só o dono do personagem vê."
NOT_IN_PARTY = "Seu personagem não está nesse Party Hunt Analyser."


class BossSessionIn(BaseModel):
    raw_text: Annotated[str, Field(min_length=1, max_length=RAW_MAX)]
    nickname: Name
    mode: Literal["solo", "party"]
    for_char: Name | None = None  # 0.23.0: jogador autorizado enviando pelo dono


class BossSplitIn(BaseModel):
    raw_text: Annotated[str, Field(min_length=1, max_length=RAW_MAX)]
    nickname: Name
    session_id: int | None = Field(default=None, ge=1)  # sessão de boss que a pessoa acabou de enviar


def _hunt_brief(h: dict) -> dict:
    return {"id": h["id"], "started_at": h["started_at"], "players_count": h["players_count"],
            "profit_each": h["profit_each"], "players": [p["name"] for p in h["players"]]}


def _link_session_to_party(row: dict) -> dict | None:
    """Sessão sem lootsplit: procura uma party de bosses do mesmo personagem no mesmo horário."""
    best = None
    for h in store.boss_hunts_for(row["name"]):
        if boss_core.overlaps(row["started_at"], row["ended_at"], h["started_at"], h["ended_at"]):
            gap = abs((datetime.fromisoformat(h["started_at"]) - datetime.fromisoformat(row["started_at"])).total_seconds())
            if best is None or gap < best[0]:
                best = (gap, h)
    if best is None:
        return None
    store.link_boss_session(row["id"], best[1]["id"])
    return best[1]


@app.post("/api/bosses/session")
def boss_session_upload(body: BossSessionIn, access: dict = Depends(require_session)):
    """Hunt Session Analyser de bosses (solo ou party). Fica visível só para o dono."""
    try:
        session = parse_solo_session(body.raw_text)
    except ParseError as e:
        raise HTTPException(422, str(e))
    name = require_uploader(body.nickname, access)
    switched, link, who, owner_key = None, None, None, access["key"]
    if body.for_char:  # 0.23.0: jogador autorizado enviando pelo dono
        grant = _grant_for([body.for_char], access, "boss")
        if grant is None:
            raise HTTPException(403, NO_GRANT)
        link, me = grant
        _in_link_window(link, session.started_at)
        name, owner_key, who = link["name"], link["owner_key"], _who("operator", me)
    else:
        other = _overlapping_char(session.started_at, session.ended_at, access, boss=True)
        if other and name_key(other) != name_key(name):
            switched, name = name, other
    _check_duplicate("boss_sessions", session.to_dict(), name, owner_key)
    if link:
        _spend_link(link)
    row, created = store.add_boss_session(name, "boss|" + session.fingerprint(name), session.to_dict(), body.mode,
                                          owner_key, who)
    if link and not created:
        store.refund_link(link["id"])
    hunt = store.boss_hunt(row["boss_hunt_id"]) if row["boss_hunt_id"] else _link_session_to_party(row)
    mine = link is None
    return {"created": created, "session_id": row["id"], "mode": row["mode"],
            "bosses": boss_core.bosses_in(session.kills),
            "rare": _session_rare(session, True, access) if created and mine else [],
            "party": _hunt_brief(hunt) if hunt else None, "rewards": grant_rewards(access["key"]) if mine else [],
            "saved_as": name, "switched_from": switched, "for_owner": not mine}


@app.post("/api/bosses/lootsplit")
def boss_lootsplit(body: BossSplitIn, access: dict = Depends(require_session)):
    """Lootsplit de bosses: aparece na aba de bosses de todos da PT e puxa as sessões deles do mesmo horário."""
    report = _parse_party(body.raw_text)
    require_uploader(body.nickname, access)
    got = _party_char(report["players"], body.nickname, access)  # 0.23.0: troca sozinho para o personagem da PT
    if got is None:
        grant = _grant_for([p["name"] for p in report["players"]], access, "boss")
        if grant is None:
            raise HTTPException(403, {"message": NOT_IN_PARTY, "hint": NOT_IN_PARTY_HINT})
        link, me = grant
        _in_link_window(link, report["started_at"])
        _spend_link(link)
        hunt, created = store.add_boss_hunt(report, link["name"], link["owner_key"], via="operator")
        tagged = store.set_tag("boss", hunt["id"], link["name"], "other", True, me, access["key"])
        if not (created or tagged):
            store.refund_link(link["id"])
        linked = _link_party_sessions(report, hunt)
        return {"created": created, "hunt": _public(store.boss_hunt(hunt["id"]), access), "linked": linked, "rewards": [],
                "saved_as": link["name"], "for_owner": True}
    uploader, switched = got
    own = None
    if body.session_id is not None:
        own = store.boss_session(body.session_id)
        if own is None:
            raise HTTPException(404, "Sessão de boss não encontrada.")
        if own["uploader_key"] != access["key"] or own["name_key"] not in {name_key(p["name"]) for p in report["players"]}:
            raise HTTPException(403, "Essa sessão não é sua.")
    hunt, created = store.add_boss_hunt(report, uploader, access["key"])
    linked = 0
    if own is not None:
        store.link_boss_session(own["id"], hunt["id"])
        linked += 1
    linked += _link_party_sessions(report, hunt)
    return {"created": created, "hunt": _public(hunt, access), "linked": linked, "rewards": grant_rewards(access["key"]),
            "saved_as": uploader, "switched_from": switched}


def _link_party_sessions(report: dict, hunt: dict) -> int:
    """Sessões de boss dos membros, do mesmo horário, ainda sem lootsplit: ficam ligadas a esta party."""
    linked = 0
    for s in store.unlinked_boss_sessions([p["name"] for p in report["players"]]):
        if boss_core.overlaps(s["started_at"], s["ended_at"], hunt["started_at"], hunt["ended_at"]):
            store.link_boss_session(s["id"], hunt["id"])
            linked += 1
    return linked


def _rare(kills, resolved, whole_session: bool, prices: dict) -> list[dict]:
    """Drops raros de boss (very/extremely rare na TibiaWiki ou item caro), com o valor pelos preços do app."""
    drops = boss_core.rare_drops(kills, resolved, whole_session,
                                 lambda k: (prices.get(k) or {}).get("unit_price") or 0)
    return [{**d, "key": d["item"], "value": d["unit"] * d["count"]} for d in drops]


def _session_rare(session, whole_session: bool, access: dict) -> list[dict]:
    """Drops raros de uma sessão recém-enviada (para a comemoração no app)."""
    if not boss_core.bosses_in(session.kills):
        return []
    resolved = [(store.resolve_item(item_key(k)), n) for k, n in session.loot]
    prices = store.price_info(list({k for k, _ in resolved}), access["key"])
    out = _rare(session.kills, resolved, whole_session, prices)
    for d in out:
        d["name"] = prices[d["key"]]["name"]
    return out


def _valued(pairs, prices: dict) -> list[dict]:
    items = _sum_counts(pairs)
    for it in items:
        it["value"] = it["count"] * prices[it["key"]]["unit_price"]
    return sorted(items, key=lambda it: (-it["value"], -it["count"]))


@app.get("/api/bosses/{name}")
def bosses_overview(name: str, access: dict = Depends(require_session)):
    """👑 Rotação de bosses do personagem: só o dono vê (e as parties em que ele estava)."""
    if not store.is_linked(access["key"], name):
        raise HTTPException(403, {"message": BOSS_PRIVATE, "hint": FORBIDDEN_HINT})
    sessions = [_public(s, access) for s in store.boss_sessions_for(name)]
    kills, loot = store.boss_details([s["id"] for s in sessions])
    solo = store.solo_for_player(name)
    s_kills, s_loot = store.solo_details([s["id"] for s in solo])
    keys = {store.resolve_item(k) for rows in (*loot.values(), *s_loot.values()) for k, _ in rows}
    prices = store.price_info(list(keys), access["key"])
    owners: dict = {}
    hunts = {h["id"]: _boss_hunt_view(h, access, owners) for h in store.boss_hunts_for(name)}
    per_boss: dict[str, dict] = {}
    rare: list[dict] = []  # 💎 histórico de drops raros

    def add_boss(b: dict, count: int, value: int, when: str, source: str) -> None:
        pb = per_boss.setdefault(b["key"], {"key": b["key"], "name": b["name"], "class": b.get("class"), "kills": 0,
                                            "value": 0, "last": None, "from_hunts": 0})
        pb["kills"] += count
        pb["value"] += value
        pb["last"] = max(pb["last"] or "", when)
        if source == "hunt":
            pb["from_hunts"] += count

    for s in sessions:
        s["kills"] = [{"key": c, "count": n} for c, n in kills[s["id"]]]
        resolved = [(store.resolve_item(k), n) for k, n in loot[s["id"]]]
        s["loot"] = _valued(resolved, prices)
        s["loot_value"] = sum(it["value"] for it in s["loot"])
        s["net_profit"] = s["loot_value"] - s["supplies"]
        s["bosses"] = boss_core.bosses_in(kills[s["id"]])
        split = boss_core.attribute_loot(kills[s["id"]], resolved, whole_session=True)
        rest = sum(n * prices[k]["unit_price"] for k, n in split.pop("_outros", []))
        for b in s["bosses"]:
            v = sum(n * prices[k]["unit_price"] for k, n in split.get(b["key"], []))
            if len(s["bosses"]) == 1:
                v += rest  # um boss só na sessão: todo o loot é dele
            add_boss(b, b["count"], v, s["started_at"], "boss")
        for d in _rare(kills[s["id"]], resolved, True, prices):
            rare.append({**d, "started_at": s["started_at"], "source": "boss", "session_id": s["id"]})
        h = hunts.get(s.get("boss_hunt_id"))
        s["party"] = _hunt_brief(h) if h else None

    # Bosses mortos em sessões comuns do Hunt Session Stacker: loot estimado (itens exclusivos do boss).
    from_hunts = []
    for s in solo:
        found = boss_core.bosses_in(s_kills[s["id"]])
        if not found:
            continue
        resolved = [(store.resolve_item(k), n) for k, n in s_loot[s["id"]]]
        split = boss_core.attribute_loot(s_kills[s["id"]], resolved, whole_session=False)
        items = _valued(((k, n) for b in found for k, n in split.get(b["key"], [])), prices)
        for b in found:
            add_boss(b, b["count"], sum(n * prices[k]["unit_price"] for k, n in split.get(b["key"], [])), s["started_at"], "hunt")
        from_hunts.append({"session_id": s["id"], "started_at": s["started_at"], "bosses": found, "items": items,
                           "value": sum(it["value"] for it in items)})
        for d in _rare(s_kills[s["id"]], resolved, False, prices):
            rare.append({**d, "started_at": s["started_at"], "source": "hunt", "session_id": s["id"]})

    # 0.23.0: nome da rotação (pelos bosses mortos) e 🗃️ cofre de cada lootsplit / sessão sem lootsplit
    vault_h = store.vault("hunt", list(hunts))
    for h in hunts.values():
        linked = store.boss_sessions_of_hunt(h["id"])
        h["members"] = [m["name"] for m in linked]
        h_kills, _ = store.boss_details([m["id"] for m in linked])
        h["rotation"] = rot.identify([k for ks in h_kills.values() for k in ks])
        subs = [n for n, t in (h.get("tags") or {}).items() if t.get("sub")]
        h["vault"] = _vault_view({"kind": "hunt", "id": h["id"], "members": [p["name"] for p in h["players"]], "subs": subs,
                                  "day": h["started_at"]}, vault_h[h["id"]], access)
    solo_ids = [s["id"] for s in sessions if not s.get("boss_hunt_id") or s["boss_hunt_id"] not in hunts]
    vault_s = store.vault("session", solo_ids)
    for s in sessions:
        s["rotation"] = rot.identify(kills[s["id"]])
        if s["id"] in vault_s:
            s["vault"] = _vault_view({"kind": "session", "id": s["id"], "members": [s["name"]], "subs": [],
                                      "day": s["started_at"]}, vault_s[s["id"]], access)
    by_day: dict[tuple, list] = {}
    for s in sessions:
        by_day.setdefault((s["started_at"][:10], s["mode"]), []).append(s)
    rotations_by_day = []
    for (day, mode), ss in sorted(by_day.items(), reverse=True):
        r = rot.identify([k for s in ss for k in kills[s["id"]]])
        if r:
            rotations_by_day.append({"day": day, "mode": mode, "name": r["name"], "groups": r["groups"],
                                     "sessions": len(ss), "balance": sum(s["balance"] for s in ss)})
    linked_hunts = {s["boss_hunt_id"] for s in sessions if s.get("boss_hunt_id")}
    sessions_profit = sum(s["balance"] for s in sessions if s.get("boss_hunt_id") not in hunts)
    party_profit = sum(profit_of(h, name) for h in hunts.values())  # considera as regras de divisão
    hunts_value = sum(x["value"] for x in from_hunts)
    secs = sum(s["duration_seconds"] for s in sessions)
    totals = {
        "sessions": len(sessions), "solo": sum(1 for s in sessions if s["mode"] == "solo"),
        "party": sum(1 for s in sessions if s["mode"] == "party"), "parties": len(hunts),
        "boss_kills": sum(b["kills"] for b in per_boss.values()),
        "duration_seconds": secs, "xp": sum(s["xp"] for s in sessions),
        "supplies": sum(s["supplies"] for s in sessions), "balance": sum(s["balance"] for s in sessions),
        "loot_value": sum(s["loot_value"] for s in sessions),
        "sessions_profit": sessions_profit, "party_profit": party_profit, "hunts_value": hunts_value,
        "profit": sessions_profit + party_profit + hunts_value,
        "profit_per_hour": _per_hour(sessions_profit + party_profit, secs),
    }
    all_items = _valued(((it["key"], it["count"]) for s in sessions for it in s["loot"]), prices)
    # 💰 itens de boss que nenhum NPC compra: a pessoa informa o preço (entra na média de todos)
    boss_keys = {it["key"] for it in all_items} | {it["key"] for x in from_hunts for it in x["items"]}
    no_npc = sorted((k for k in boss_keys if not prices[k]["npc_price"] and prices[k].get("source") != "moeda"),
                    key=lambda k: (bool(prices[k]["unit_price"]), prices[k]["name"]))
    return {"name": name, "totals": totals, "bosses": sorted(per_boss.values(), key=lambda b: (-b["kills"], b["name"])),
            "sessions": sessions, "hunts": sorted(hunts.values(), key=lambda h: h["started_at"], reverse=True),
            "linked_hunts": len(linked_hunts), "from_hunts": from_hunts, "items": all_items, "prices": prices,
            "rare_drops": sorted(rare, key=lambda d: d["started_at"], reverse=True),
            "no_npc": no_npc, "unpriced": sum(1 for k in no_npc if not prices[k]["unit_price"]),
            "rotations": rotations_by_day, "fee": rot.fee_rule()}


def _delete_own_boss(table: str, row_id: int, access: dict) -> None:
    exists, owner = store.boss_uploader(table, row_id)
    if not exists:
        raise HTTPException(404, "Não encontrado (talvez já tenha sido apagado).")
    if owner != access["key"]:
        raise HTTPException(403, "Só quem enviou pode apagar.")
    store.delete_boss(table, row_id)


@app.delete("/api/bosses/session/{session_id}")
def delete_boss_session(session_id: int, access: dict = Depends(require_session)):
    _delete_own_boss("boss_sessions", session_id, access)
    return {"deleted": session_id}


def _require_boss_member(hunt_id: int, access: dict) -> None:
    """Lootsplit de boss é privado: só quem tem personagem da PT mexe nele."""
    h = _load_hunt("boss", hunt_id)
    if not any(store.is_linked(access["key"], p["name"]) for p in h["players"]):
        raise HTTPException(403, {"message": BOSS_PRIVATE, "hint": FORBIDDEN_HINT})


@app.post("/api/bosses/hunt/{hunt_id}/rules")
def boss_hunt_rules(hunt_id: int, body: RulesIn, access: dict = Depends(require_session)):
    _require_boss_member(hunt_id, access)
    return _set_rules("boss", hunt_id, body, access)


@app.post("/api/bosses/hunt/{hunt_id}/paid")
def boss_hunt_paid(hunt_id: int, body: PaidIn, access: dict = Depends(require_session)):
    _require_boss_member(hunt_id, access)
    return _set_paid("boss", hunt_id, body, access)


@app.delete("/api/bosses/hunt/{hunt_id}")
def delete_boss_hunt(hunt_id: int, access: dict = Depends(require_session)):
    _delete_own_boss("boss_hunts", hunt_id, access)
    return {"deleted": hunt_id}


@app.post("/api/bosses/hunt/{hunt_id}/tags")
def boss_hunt_tags(hunt_id: int, body: TagIn, access: dict = Depends(require_session)):
    _require_boss_member(hunt_id, access)
    return _set_tags("boss", hunt_id, body, access)


@app.post("/api/bosses/hunt/{hunt_id}/claim")
def boss_hunt_claim(hunt_id: int, access: dict = Depends(require_session)):
    _require_boss_member(hunt_id, access)
    return _claim("boss", hunt_id, access)


# ------------------------------------------------------------------ 0.23.0: 🗃️ cofre da rotação de bosses
VAULT_ITEM_MAX = 60
VAULT_GP_MAX = 100_000_000_000
NOT_VAULT_OWNER = "Só quem registrou esse drop pode alterar."


def _vault_ref(kind: str, ref_id: int, access: dict) -> dict:
    """Quem estava na rotação (os membros da divisão) e o dia do drop. Só quem estava lá mexe no cofre."""
    if kind == "hunt":
        h = store.boss_hunt(ref_id)
        if h is None:
            raise HTTPException(404, "Lootsplit não encontrado (talvez tenha sido apagado).")
        members = [p["name"] for p in h["players"]]
        tags = _tags_view(h["players"], store.tags_for("boss", [ref_id])[ref_id], _registered_subs(members, "boss"))
        subs = [n for n, t in tags.items() if t.get("sub")]
        day = h["started_at"]
    elif kind == "session":
        s = store.boss_session(ref_id)
        if s is None:
            raise HTTPException(404, "Sessão de boss não encontrada.")
        members, subs, day = [s["name"]], [], s["started_at"]
    else:
        raise HTTPException(404, "Não encontrado.")
    if not any(store.is_linked(access["key"], m) for m in members):
        raise HTTPException(403, {"message": BOSS_PRIVATE, "hint": FORBIDDEN_HINT})
    return {"kind": kind, "id": ref_id, "members": members, "subs": subs, "day": day}


def _transfers_with_paid(transfers: list[dict], paid: dict) -> list[dict]:
    for t in transfers:
        p = paid.get((name_key(t["payer"]), name_key(t["receiver"])))
        t["paid_at"] = p["paid_at"] if p and p["amount"] == t["amount"] else None
    return transfers


def _vault_view(ref: dict, data: dict, access: dict) -> dict:
    """Cofre de uma rotação: drops (estoque/vendido/usado), conjuntos usados e quem paga quem."""
    members, n = ref["members"], len(ref["members"])
    paid_d = store.payments_of("drop", [d["id"] for d in data["drops"]])
    paid_c = store.payments_of("craft", [c["id"] for c in data["crafts"]])
    drops = []
    for d in data["drops"]:
        fee = rot.market_fee(d["sold_total"] or 0, d["sold_at"]) if d["status"] == "sold" and d["market_fee"] else 0
        net = (d["sold_total"] or 0) - fee if d["status"] == "sold" else 0
        # chave do item: #número + dia do drop (vários itens iguais ficam distinguíveis)
        drops.append({"id": d["id"], "code": f"#{d['id']}", "dropped_on": d.get("dropped_on") or ref["day"][:10],
                      "item": d["item"], "qty": d["qty"], "dropped_by": d["dropped_by"], "price_each": d["price_each"],
                      "estimate": (d["price_each"] or 0) * d["qty"], "status": d["status"], "sold_total": d["sold_total"],
                      "market_fee": bool(d["market_fee"]), "fee": fee, "net": net, "each": net // n if n else 0,
                      "sold_at": d["sold_at"], "craft_id": d["craft_id"], "set": rot.set_of(d["item"]),
                      "can_edit": d["owner_key"] == access["key"], "created_at": d["created_at"],
                      "transfers": _transfers_with_paid(rot.shares(net, members, d["dropped_by"]), paid_d[d["id"]])})
    crafts = []
    for c in data["crafts"]:
        s = rot.SETS[c["set_key"]]
        cost = sum(int(b["cost"]) for b in c["bought"])
        fee = rot.market_fee(c["sold_total"] or 0, c["sold_at"]) if c["sold_total"] and c["market_fee"] else 0
        net = (c["sold_total"] or 0) - fee - cost if c["sold_total"] else 0
        crafts.append({"id": c["id"], "set": c["set_key"], "label": s["label"], "result": c["result"], "seller": c["seller"],
                       "bought": c["bought"], "cost": cost, "sold_total": c["sold_total"], "market_fee": bool(c["market_fee"]),
                       "fee": fee, "net": net, "each": net // n if n and net > 0 else 0,
                       "per_item": net // len(s["items"]) if net > 0 else 0, "sold_at": c["sold_at"],
                       "used": [{"id": d["id"], "code": f"#{d['id']}", "item": d["item"], "dropped_by": d["dropped_by"],
                                 "dropped_on": d.get("dropped_on") or ref["day"][:10]}
                                for d in data["drops"] if d["craft_id"] == c["id"]],
                       "can_edit": c["owner_key"] == access["key"],
                       "transfers": _transfers_with_paid(rot.shares(net, members, c["seller"]), paid_c[c["id"]])})
    sets = {}
    for key, s in rot.SETS.items():
        have = {i: sum(d["qty"] for d in data["drops"] if d["status"] == "stock" and d["item"] == i) for i in s["items"]}
        if any(have.values()):
            sets[key] = {"label": s["label"], "have": have, "missing": [i for i in s["items"] if not have[i]],
                         "results": s["results"], "npc": s["npc"]}
    return {"ref": {"kind": ref["kind"], "id": ref["id"]}, "members": members, "subs": ref["subs"], "day": ref["day"],
            "drops": drops, "crafts": crafts, "sets": sets}


def _vault_payload(kind: str, ref_id: int, access: dict) -> dict:
    ref = _vault_ref(kind, ref_id, access)
    return _vault_view(ref, store.vault(kind, [ref_id])[ref_id], access)


class VaultDropIn(BaseModel):
    item: Annotated[str, Field(min_length=2, max_length=VAULT_ITEM_MAX)]
    qty: int = Field(default=1, ge=1, le=1000)
    dropped_by: Name
    price_each: int | None = Field(default=None, ge=0, le=VAULT_GP_MAX)
    dropped_on: date | None = None  # dia do drop (padrão: o dia da rotação)


class VaultDropEdit(BaseModel):
    action: Literal["price", "sell", "stock"]
    price_each: int | None = Field(default=None, ge=0, le=VAULT_GP_MAX)
    sold_total: int | None = Field(default=None, ge=1, le=VAULT_GP_MAX)
    market_fee: bool = False


class BoughtIn(BaseModel):
    item: Annotated[str, Field(min_length=2, max_length=VAULT_ITEM_MAX)]
    cost: int = Field(ge=0, le=VAULT_GP_MAX)


class VaultCraftIn(BaseModel):
    set: Literal["crypt"]
    drop_ids: Annotated[list[int], Field(max_length=10)] = []
    bought: Annotated[list[BoughtIn], Field(max_length=10)] = []
    result: Annotated[str, Field(max_length=VAULT_ITEM_MAX)] | None = None
    seller: Name
    sold_total: int | None = Field(default=None, ge=1, le=VAULT_GP_MAX)
    market_fee: bool = False


class VaultCraftEdit(BaseModel):
    result: Annotated[str, Field(max_length=VAULT_ITEM_MAX)] | None = None
    sold_total: int | None = Field(default=None, ge=1, le=VAULT_GP_MAX)
    market_fee: bool = False


class VaultPaidIn(PaidIn):
    kind: Literal["drop", "craft"]
    id: int = Field(ge=1)


def _member(ref: dict, name: str, what: str) -> str:
    real = next((m for m in ref["members"] if name_key(m) == name_key(name)), None)
    if real is None:
        raise HTTPException(422, f"{name} não estava nessa rotação.")
    return real


def _clean_item(item: str) -> str:
    item = rot.canonical_item(item)
    if not _PLACE_NAME.fullmatch(item):
        raise HTTPException(422, "Use só letras, números e pontuação simples no nome do item.")
    return item


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@app.get("/api/vault/{kind}/{ref_id}")
def vault_get(kind: str, ref_id: int, access: dict = Depends(require_session)):
    return _vault_payload(kind, ref_id, access)


@app.post("/api/vault/{kind}/{ref_id}/drops")
def vault_add_drop(kind: str, ref_id: int, body: VaultDropIn, access: dict = Depends(require_session)):
    """Registrar um drop da rotação (pode ter caído para outro membro)."""
    ref = _vault_ref(kind, ref_id, access)
    who = _member(ref, body.dropped_by, "dropped_by")
    if len(store.vault(kind, [ref_id])[ref_id]["drops"]) >= 200:
        raise HTTPException(429, "Esse cofre já tem drops demais.")
    day = body.dropped_on.isoformat() if body.dropped_on else ref["day"][:10]
    if day > (date.today() + timedelta(days=1)).isoformat() or day < "2000-01-01":
        raise HTTPException(422, "Data do drop inválida.")
    store.add_vault_drop(kind, ref_id, _clean_item(body.item), body.qty, who, body.price_each, access["key"], day)
    return _vault_payload(kind, ref_id, access)


def _own_drop(drop_id: int, access: dict) -> dict:
    d = store.vault_drop(drop_id)
    if d is None:
        raise HTTPException(404, "Drop não encontrado (talvez tenha sido apagado).")
    _vault_ref(d["ref_kind"], d["ref_id"], access)
    if d["owner_key"] != access["key"]:
        raise HTTPException(403, NOT_VAULT_OWNER)
    return d


@app.post("/api/vault/drops/{drop_id}")
def vault_edit_drop(drop_id: int, body: VaultDropEdit, access: dict = Depends(require_session)):
    """Preço (só quem registrou), vendido (com ou sem a taxa do Market) ou de volta ao estoque."""
    d = _own_drop(drop_id, access)
    if d["status"] == "used":
        raise HTTPException(409, "Esse drop já foi usado num conjunto. Desfaça o uso para mexer nele.")
    if body.action == "price":
        store.update_vault_drop(drop_id, price_each=body.price_each)
    elif body.action == "sell":
        if not body.sold_total:
            raise HTTPException(422, "Informe por quanto foi vendido (valor total).")
        store.update_vault_drop(drop_id, status="sold", sold_total=body.sold_total, market_fee=1 if body.market_fee else 0,
                                sold_at=_now())
    else:
        store.update_vault_drop(drop_id, status="stock", sold_total=None, market_fee=0, sold_at=None)
    return _vault_payload(d["ref_kind"], d["ref_id"], access)


@app.delete("/api/vault/drops/{drop_id}")
def vault_delete_drop(drop_id: int, access: dict = Depends(require_session)):
    d = _own_drop(drop_id, access)
    if d["status"] == "used":
        raise HTTPException(409, "Esse drop já foi usado num conjunto. Desfaça o uso para mexer nele.")
    store.delete_vault_drop(drop_id)
    return _vault_payload(d["ref_kind"], d["ref_id"], access)


@app.post("/api/vault/{kind}/{ref_id}/crafts")
def vault_add_craft(kind: str, ref_id: int, body: VaultCraftIn, access: dict = Depends(require_session)):
    """Usar um conjunto (ex.: uma Crypt Rune de cada): as do estoque + as que faltaram e foram compradas."""
    ref = _vault_ref(kind, ref_id, access)
    s = rot.SETS[body.set]
    stock = {d["id"]: d for d in store.vault(kind, [ref_id])[ref_id]["drops"] if d["status"] == "stock"}
    used = {}
    for did in body.drop_ids:
        d = stock.get(did)
        if d is None or d["item"] not in s["items"] or d["item"] in used:
            raise HTTPException(422, "Escolha um item de cada tipo que está no estoque desta rotação.")
        used[d["item"]] = did
    bought = []
    for b in body.bought:
        item = rot.canonical_item(b.item)
        if item not in s["items"] or item in used or any(x["item"] == item for x in bought):
            raise HTTPException(422, "Os itens comprados precisam ser os que faltaram no conjunto.")
        bought.append({"item": item, "cost": b.cost})
    if len(used) + len(bought) != len(s["items"]):
        raise HTTPException(422, f"O conjunto precisa de um de cada: {', '.join(s['items'])}.")
    seller = _member(ref, body.seller, "seller")
    result = _clean_item(body.result) if body.result else None
    ids = [store.take_one_vault_drop(did) for did in used.values()]  # tudo conferido: separa 1 de cada do estoque
    cid = store.add_vault_craft(kind, ref_id, body.set, ids, bought, result, seller, access["key"])
    if body.sold_total:
        store.update_vault_craft(cid, sold_total=body.sold_total, market_fee=1 if body.market_fee else 0, sold_at=_now())
    return _vault_payload(kind, ref_id, access)


def _own_craft(craft_id: int, access: dict) -> dict:
    c = store.vault_craft(craft_id)
    if c is None:
        raise HTTPException(404, "Não encontrado (talvez já tenha sido apagado).")
    _vault_ref(c["ref_kind"], c["ref_id"], access)
    if c["owner_key"] != access["key"]:
        raise HTTPException(403, NOT_VAULT_OWNER)
    return c


@app.post("/api/vault/crafts/{craft_id}")
def vault_edit_craft(craft_id: int, body: VaultCraftEdit, access: dict = Depends(require_session)):
    c = _own_craft(craft_id, access)
    store.update_vault_craft(craft_id, result=_clean_item(body.result) if body.result else c["result"],
                             sold_total=body.sold_total, market_fee=1 if body.market_fee else 0,
                             sold_at=_now() if body.sold_total else None)
    return _vault_payload(c["ref_kind"], c["ref_id"], access)


@app.delete("/api/vault/crafts/{craft_id}")
def vault_delete_craft(craft_id: int, access: dict = Depends(require_session)):
    c = _own_craft(craft_id, access)
    store.delete_vault_craft(craft_id)
    return _vault_payload(c["ref_kind"], c["ref_id"], access)


@app.post("/api/vault/paid")
def vault_paid(body: VaultPaidIn, access: dict = Depends(require_session)):
    """'Já paguei' / 'recebi' da parte de cada um na venda de um drop ou de um conjunto."""
    row = store.vault_drop(body.id) if body.kind == "drop" else store.vault_craft(body.id)
    if row is None:
        raise HTTPException(404, "Não encontrado (talvez já tenha sido apagado).")
    payload = _vault_payload(row["ref_kind"], row["ref_id"], access)
    items = payload["drops"] if body.kind == "drop" else payload["crafts"]
    x = next(i for i in items if i["id"] == body.id)
    t = next((t for t in x["transfers"] if name_key(t["payer"]) == name_key(body.payer)
              and name_key(t["receiver"]) == name_key(body.receiver)), None)
    if t is None:
        raise HTTPException(404, "Essa transferência não existe.")
    if not (store.is_linked(access["key"], t["payer"]) or store.is_linked(access["key"], t["receiver"])):
        raise HTTPException(403, {"message": "Só quem paga ou quem recebe pode marcar essa transferência.", "hint": FORBIDDEN_HINT})
    store.set_paid(body.kind, body.id, t["payer"], t["receiver"], t["amount"], access["key"], body.paid)
    return _vault_payload(row["ref_kind"], row["ref_id"], access)


# ------------------------------------------------------------------ 0.24.0: 👥 parties registradas e 🗃️ cofre da party
PARTY_MAX_OWNED = 20
PARTY_MAX_MEMBERS = 15
PARTY_ITEMS_MAX = 500
PARTY_PRIVATE = "Só quem é da party (titular ou substituto) vê e mexe nela."
NOT_PARTY_OWNER = "Só quem criou a party muda a formação."
ORIGIN_LABEL = {"drop": "Drop", "service": "Service", "buy": "Compra"}


class PartyMemberIn(BaseModel):
    name: Name
    role: Literal["main", "sub"] = "main"


class PartyIn(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=40)]
    kind: Literal["hunt", "boss", "both"] = "both"
    rotation: Literal["graveborn"] | None = None
    members: Annotated[list[PartyMemberIn], Field(min_length=1, max_length=PARTY_MAX_MEMBERS)]


class PartyItemIn(BaseModel):
    item: Annotated[str, Field(min_length=2, max_length=VAULT_ITEM_MAX)]
    qty: int = Field(default=1, ge=1, le=1000)
    origin: Literal["drop", "service", "buy"] = "drop"
    cost_each: int | None = Field(default=None, ge=0, le=VAULT_GP_MAX)
    holder: Name
    obtained_on: date | None = None
    note: Annotated[str, Field(max_length=80)] | None = None
    client: Name | None = None                  # service: o serviçado
    rune_value: int | None = Field(default=None, ge=0, le=VAULT_GP_MAX)  # service: valor da runa (padrão: preço do cofre)


class PartyItemEdit(BaseModel):
    action: Literal["sell", "stock", "origin", "holder"]
    sold_total: int | None = Field(default=None, ge=1, le=VAULT_GP_MAX)
    market_fee: bool = False
    seller: Name | None = None
    origin: Literal["drop", "service", "buy"] | None = None
    cost_each: int | None = Field(default=None, ge=0, le=VAULT_GP_MAX)
    holder: Name | None = None
    client: Name | None = None
    rune_value: int | None = Field(default=None, ge=0, le=VAULT_GP_MAX)


class PartyPriceIn(BaseModel):
    item: Annotated[str, Field(min_length=2, max_length=VAULT_ITEM_MAX)]
    price: int | None = Field(default=None, ge=0, le=VAULT_GP_MAX)


class PartyCraftIn(BaseModel):
    set: Literal["crypt"]
    item_ids: Annotated[list[int], Field(min_length=1, max_length=10)]
    result: Annotated[str, Field(max_length=VAULT_ITEM_MAX)] | None = None
    holder: Name


class PartyCraftEdit(BaseModel):
    result: Annotated[str, Field(max_length=VAULT_ITEM_MAX)] | None = None
    sold_total: int | None = Field(default=None, ge=1, le=VAULT_GP_MAX)
    market_fee: bool = False
    seller: Name | None = None


class PartyPaidIn(PaidIn):
    kind: Literal["item", "craft", "service"]
    id: int = Field(ge=1)


def _party_access(party_id: int, access: dict) -> dict:
    p = store.party(party_id)
    if p is None:
        raise HTTPException(404, "Party não encontrada (talvez tenha sido apagada).")
    if p["owner_key"] != access["key"] and not any(store.is_linked(access["key"], m["name"]) for m in p["members"]):
        raise HTTPException(403, {"message": PARTY_PRIVATE, "hint": FORBIDDEN_HINT})
    return p


def _party_who(p: dict, name: str | None) -> str:
    real = next((m["name"] for m in p["members"] if name and name_key(m["name"]) == name_key(name)), None)
    if real is None:
        raise HTTPException(422, f"{name} não é da party {p['name']}.")
    return real


def _mains(p: dict) -> list[str]:
    return [m["name"] for m in p["members"] if m["role"] == "main"]


def _party_brief(p: dict, access: dict) -> dict:
    return {"id": p["id"], "name": p["name"], "kind": p["kind"], "rotation": p["rotation"],
            "set": party_core.ROTATION_SETS.get(p["rotation"] or ""),
            "members": p["members"], "can_edit": p["owner_key"] == access["key"], "created_at": p["created_at"]}


def _party_vault_view(p: dict, access: dict) -> dict:
    """Estoque total do cofre da party, quanto cada item vale, vendas (com quem paga quem) e crafts."""
    data = store.party_vault(p["id"])
    mains = _mains(p)
    prices = data["prices"]

    def price_of(item: str) -> int | None:
        r = prices.get(name_key(item))
        return r["price"] if r else None

    paid_i = store.payments_of("pitem", [i["id"] for i in data["items"]])
    paid_s = store.payments_of("psvc", [i["id"] for i in data["items"] if i["origin"] == "service"])
    paid_c = store.payments_of("pcraft", [c["id"] for c in data["crafts"]])
    items = []
    for i in data["items"]:
        price = price_of(i["item"])
        lo, hi = party_core.unit_range(i["origin"], i["cost_each"], price)
        out = {"id": i["id"], "code": f"#{i['id']}", "item": i["item"], "qty": i["qty"], "origin": i["origin"],
               "origin_label": ORIGIN_LABEL[i["origin"]], "cost_each": i["cost_each"], "holder": i["holder"],
               "obtained_on": i["obtained_on"], "note": i["note"], "status": i["status"], "price": price,
               "min": lo * i["qty"], "max": hi * i["qty"], "value": (price or 0) * i["qty"],
               "set": rot.set_of(i["item"]), "craft_id": i["craft_id"], "ref_price": i["ref_price"],
               "can_delete": i["owner_key"] == access["key"] or p["owner_key"] == access["key"], "created_at": i["created_at"],
               "client": i.get("client")}
        if i["origin"] == "service" and i.get("client"):
            sv = party_core.service_shares(i["cost_each"], i["qty"], mains, i["client"])
            out["service"] = {"client": i["client"], "rune_value": (i["cost_each"] or 0) * 2, "half": sv["total"],
                              "each": sv["each"], "transfers": _transfers_with_paid(sv["transfers"], paid_s[i["id"]])}
        if i["status"] == "sold":
            refunds = [(i["holder"], (i["cost_each"] or 0) * i["qty"])] if i["origin"] == "buy" else []
            s = party_core.sale(i["sold_total"], bool(i["market_fee"]), i["sold_at"], mains, i["seller"] or i["holder"], refunds)
            out.update(sold_total=i["sold_total"], market_fee=bool(i["market_fee"]), sold_at=i["sold_at"],
                       seller=i["seller"] or i["holder"], fee=s["fee"], refund=s["refund"], net=s["net"], each=s["each"],
                       transfers=_transfers_with_paid(s["transfers"], paid_i[i["id"]]))
        items.append(out)
    crafts = []
    for c in data["crafts"]:
        used = [x for x in items if x["craft_id"] == c["id"]]
        out = {"id": c["id"], "set": c["set_key"], "label": rot.SETS[c["set_key"]]["label"], "result": c["result"],
               "holder": c["holder"], "min": c["min_value"], "max": c["max_value"], "cost": c["cost"],
               "sold_total": c["sold_total"], "market_fee": bool(c["market_fee"]), "sold_at": c["sold_at"],
               "used": [{"id": u["id"], "code": u["code"], "item": u["item"], "origin": u["origin"], "cost_each": u["cost_each"],
                         "ref_price": u["ref_price"], "holder": u["holder"]} for u in used],
               "can_delete": c["owner_key"] == access["key"] or p["owner_key"] == access["key"], "created_at": c["created_at"]}
        if c["sold_total"]:
            refunds = [(u["holder"], u["cost_each"] or 0) for u in used if u["origin"] == "buy"]
            s = party_core.sale(c["sold_total"], bool(c["market_fee"]), c["sold_at"], mains, c["holder"], refunds)
            out.update(fee=s["fee"], refund=s["refund"], net=s["net"], each=s["each"],
                       transfers=_transfers_with_paid(s["transfers"], paid_c[c["id"]]))
        crafts.append(out)
    # estoque total por item (todas as unidades no estoque, de qualquer origem)
    stock: dict[str, dict] = {}
    for x in items:
        if x["status"] != "stock":
            continue
        s = stock.setdefault(name_key(x["item"]), {"item": x["item"], "qty": 0, "price": x["price"], "value": 0,
                                                   "min": 0, "max": 0, "origins": {"drop": 0, "service": 0, "buy": 0}})
        s["qty"] += x["qty"]
        s["value"] += x["value"]
        s["min"] += x["min"]
        s["max"] += x["max"]
        s["origins"][x["origin"]] += x["qty"]
    for k, r in prices.items():  # preço salvo de item que não está no estoque agora também aparece (para editar)
        stock.setdefault(k, {"item": r["item"], "qty": 0, "price": r["price"], "value": 0, "min": 0, "max": 0,
                             "origins": {"drop": 0, "service": 0, "buy": 0}})
    set_key = party_core.ROTATION_SETS.get(p["rotation"] or "")
    craft_set = None
    if set_key:
        s = rot.SETS[set_key]
        have = {it: sum(x["qty"] for x in items if x["status"] == "stock" and x["item"] == it) for it in s["items"]}
        craft_set = {"key": set_key, "label": s["label"], "items": s["items"], "results": s["results"], "npc": s["npc"],
                     "have": have, "missing": [it for it in s["items"] if not have[it]]}
    st = [x for x in items if x["status"] == "stock"]
    totals = {"units": sum(x["qty"] for x in st), "value": sum(x["value"] for x in st),
              "min": sum(x["min"] for x in st), "max": sum(x["max"] for x in st),
              "invested": sum((x["cost_each"] or 0) * x["qty"] for x in st if x["origin"] == "buy"),
              "unpriced": sorted({x["item"] for x in st if x["price"] is None})}
    return {"party": _party_brief(p, access), "mains": mains, "stock": sorted(stock.values(), key=lambda s: (-s["qty"], s["item"])),
            "items": items, "crafts": crafts, "craft_set": craft_set, "totals": totals, "fee": rot.fee_rule()}


def _clean_members(body: PartyIn, access: dict) -> list[dict]:
    seen, members = set(), []
    for m in body.members:
        n = _clean_name(m.name)
        if name_key(n) in seen:
            raise HTTPException(422, f"{n} está repetido na party.")
        seen.add(name_key(n))
        members.append({"name": n, "role": m.role})
    if not any(m["role"] == "main" for m in members):
        raise HTTPException(422, "A party precisa de pelo menos um titular.")
    if not any(store.is_linked(access["key"], m["name"]) for m in members):
        raise HTTPException(403, {"message": "Coloque pelo menos um personagem seu na party.", "hint": FORBIDDEN_HINT})
    return members


def _party_name(name: str) -> str:
    name = " ".join(name.split())
    if not _PLACE_NAME.fullmatch(name):
        raise HTTPException(422, "Use só letras, números e pontuação simples no nome da party.")
    return name


@app.get("/api/parties")
def parties_mine(access: dict = Depends(require_session)):
    """Parties em que algum personagem da conta está (ou que a conta criou)."""
    chars = [c["name"] for c in store.key_chars(access["key"])]
    return {"parties": [_party_brief(p, access) for p in store.parties_with(chars)],
            "rotations": [{"key": k, "label": next(g["label"] for g in rot.GROUPS if g["key"] == k),
                           "set": s, "set_label": rot.SETS[s]["label"]} for k, s in party_core.ROTATION_SETS.items()]}


@app.post("/api/parties")
def party_create(body: PartyIn, access: dict = Depends(require_session)):
    if store.parties_owned(access["key"]) >= PARTY_MAX_OWNED:
        raise HTTPException(429, f"Você já criou {PARTY_MAX_OWNED} parties. Apague uma que não usa mais.")
    pid = store.save_party(None, _party_name(body.name), body.kind, body.rotation, _clean_members(body, access), access["key"])
    return {"party": _party_brief(store.party(pid), access)}


@app.post("/api/parties/{party_id}")
def party_update(party_id: int, body: PartyIn, access: dict = Depends(require_session)):
    p = _party_access(party_id, access)
    if p["owner_key"] != access["key"]:
        raise HTTPException(403, NOT_PARTY_OWNER)
    members = _clean_members(body, access)
    # quem tem item guardado ou craft em mãos não sai da party (senão o cofre fica sem dono)
    vault = store.party_vault(party_id)
    keep = {name_key(i["holder"]) for i in vault["items"] if i["status"] == "stock"}
    keep |= {name_key(c["holder"]) for c in vault["crafts"] if not c["sold_total"]}
    gone = keep - {name_key(m["name"]) for m in members}
    if gone:
        raise HTTPException(409, "Quem ainda guarda itens do cofre precisa continuar na party (pode virar substituto).")
    store.save_party(party_id, _party_name(body.name), body.kind, body.rotation, members, access["key"])
    return {"party": _party_brief(store.party(party_id), access)}


@app.delete("/api/parties/{party_id}")
def party_delete(party_id: int, access: dict = Depends(require_session)):
    p = _party_access(party_id, access)
    if p["owner_key"] != access["key"]:
        raise HTTPException(403, NOT_PARTY_OWNER)
    store.delete_party(party_id)
    return {"deleted": party_id}


@app.get("/api/parties/{party_id}/vault")
def party_vault_get(party_id: int, access: dict = Depends(require_session)):
    return _party_vault_view(_party_access(party_id, access), access)


def _check_day(d: date | None) -> str:
    day = (d or date.today()).isoformat()
    if day > (date.today() + timedelta(days=1)).isoformat() or day < "2000-01-01":
        raise HTTPException(422, "Data inválida.")
    return day


def _service_terms(p: dict, item: str, client: str | None, rune_value: int | None) -> tuple[int, str]:
    """🟢 Service: a runa garantida do serviçado. A party paga a ele a metade do valor da runa (informado ou o preço do
    cofre), dividida entre os titulares. Devolve (metade, serviçado)."""
    client = _clean_name(client)
    if not client:
        raise HTTPException(422, "Informe quem é o serviçado (o personagem que recebe a metade da runa).")
    if rune_value is None:
        rune_value = next((r["price"] for k, r in store.party_vault(p["id"])["prices"].items() if k == name_key(item)), None)
    if not rune_value:
        raise HTTPException(422, f"Informe quanto vale a {item} (ou coloque o preço dela no cofre).")
    return party_core.service_half(rune_value), client


@app.post("/api/parties/{party_id}/vault/items")
def party_item_add(party_id: int, body: PartyItemIn, access: dict = Depends(require_session)):
    """Guardar um item no cofre: drop, service (runa garantida do serviçado) ou compra (preço pago obrigatório)."""
    p = _party_access(party_id, access)
    if body.origin == "buy" and body.cost_each is None:
        raise HTTPException(422, "Informe quanto foi pago (cada).")
    if len(store.party_vault(party_id)["items"]) >= PARTY_ITEMS_MAX:
        raise HTTPException(429, "Esse cofre já tem itens demais.")
    note = " ".join(body.note.split()) if body.note else None
    if note and not _PLACE_NAME.fullmatch(note):
        raise HTTPException(422, "Use só letras, números e pontuação simples na observação.")
    item, qty, cost, client = _clean_item(body.item), body.qty, body.cost_each if body.origin == "buy" else None, None
    if body.origin == "service":
        qty = 1  # uma runa garantida por service
        cost, client = _service_terms(p, item, body.client, body.rune_value)
    store.add_party_item(party_id, item, qty, body.origin, cost, _party_who(p, body.holder),
                         _check_day(body.obtained_on), note, access["key"], client)
    return _party_vault_view(p, access)


def _party_item_of(party_id: int, item_id: int, access: dict) -> tuple[dict, dict]:
    p = _party_access(party_id, access)
    i = store.party_item(item_id)
    if i is None or i["party_id"] != party_id:
        raise HTTPException(404, "Item não encontrado (talvez tenha sido apagado).")
    return p, i


@app.post("/api/parties/{party_id}/vault/items/{item_id}")
def party_item_edit(party_id: int, item_id: int, body: PartyItemEdit, access: dict = Depends(require_session)):
    """Vendido (pede o valor), de volta ao estoque, trocar a origem (sacolinha) ou quem guarda."""
    p, i = _party_item_of(party_id, item_id, access)
    if i["status"] == "used":
        raise HTTPException(409, "Esse item já foi usado num craft. Desfaça o craft para mexer nele.")
    if body.action == "sell":
        if not body.sold_total:
            raise HTTPException(422, "Informe por quanto foi vendido (valor total).")
        seller = _party_who(p, body.seller or i["holder"])
        store.update_party_item(item_id, status="sold", sold_total=body.sold_total, market_fee=1 if body.market_fee else 0,
                                sold_at=_now(), seller=seller)
    elif body.action == "stock":
        store.update_party_item(item_id, status="stock", sold_total=None, market_fee=0, sold_at=None, seller=None)
        store.forget_payments("pitem", item_id)
    elif body.action == "origin":
        if not body.origin:
            raise HTTPException(422, "Escolha a origem: Drop, Service ou Compra.")
        if body.origin == "buy" and body.cost_each is None:
            raise HTTPException(422, "Informe quanto foi pago (cada).")
        cost, client = (body.cost_each if body.origin == "buy" else None), None
        if body.origin == "service":
            if i["qty"] > 1:
                raise HTTPException(422, "Service é uma runa só. Separe a unidade antes (apague e guarde de novo).")
            cost, client = _service_terms(p, i["item"], body.client, body.rune_value)
        store.forget_payments("psvc", item_id)
        store.update_party_item(item_id, origin=body.origin, cost_each=cost, client=client)
    else:
        store.update_party_item(item_id, holder=_party_who(p, body.holder))
    return _party_vault_view(p, access)


@app.delete("/api/parties/{party_id}/vault/items/{item_id}")
def party_item_delete(party_id: int, item_id: int, access: dict = Depends(require_session)):
    p, i = _party_item_of(party_id, item_id, access)
    if i["owner_key"] != access["key"] and p["owner_key"] != access["key"]:
        raise HTTPException(403, "Só quem guardou o item (ou quem criou a party) pode apagar.")
    if i["status"] == "used":
        raise HTTPException(409, "Esse item já foi usado num craft. Desfaça o craft para mexer nele.")
    store.delete_party_item(item_id)
    return _party_vault_view(p, access)


@app.post("/api/parties/{party_id}/vault/prices")
def party_price_set(party_id: int, body: PartyPriceIn, access: dict = Depends(require_session)):
    """Quanto o item está valendo (média praticada). Qualquer membro muda a qualquer momento; vazio = sem preço."""
    p = _party_access(party_id, access)
    store.set_party_price(party_id, _clean_item(body.item), body.price, access["key"])
    return _party_vault_view(p, access)


@app.post("/api/parties/{party_id}/vault/crafts")
def party_craft_add(party_id: int, body: PartyCraftIn, access: dict = Depends(require_session)):
    """🔨 Craftar: uma unidade de cada item do conjunto, escolhida do estoque (qualquer sacolinha).
    Guarda a faixa de preço do item craftado; o valor de venda só é pedido quando vender."""
    p = _party_access(party_id, access)
    if party_core.ROTATION_SETS.get(p["rotation"] or "") != body.set:
        raise HTTPException(422, "Essa party não crafta esse conjunto.")
    s = rot.SETS[body.set]
    data = store.party_vault(party_id)
    stock = {i["id"]: i for i in data["items"] if i["status"] == "stock"}
    picked: dict[str, dict] = {}
    for iid in body.item_ids:
        i = stock.get(iid)
        if i is None or i["item"] not in s["items"] or i["item"] in picked:
            raise HTTPException(422, "Escolha um item de cada tipo que está no estoque do cofre.")
        picked[i["item"]] = i
    if len(picked) != len(s["items"]):
        raise HTTPException(422, f"O craft precisa de um de cada: {', '.join(s['items'])}. "
                                 "Se alguém comprou o que faltava, guarde antes como 🔴 Compra.")
    holder = _party_who(p, body.holder)
    result = _clean_item(body.result) if body.result else None
    if result and result not in s["results"]:
        raise HTTPException(422, f"Escolha um dos itens: {', '.join(s['results'])}.")
    prices = {k: r["price"] for k, r in data["prices"].items()}
    used, parts = [], []
    for i in picked.values():
        price = prices.get(name_key(i["item"]))
        parts.append({"origin": i["origin"], "cost_each": i["cost_each"], "price": price})
        used.append((store.split_party_item(i["id"]), price))  # tudo conferido: separa 1 unidade de cada
    cid = store.add_party_craft(party_id, body.set, used, result, holder, party_core.craft_range(parts), access["key"])
    return {**_party_vault_view(p, access), "craft_id": cid}


def _party_craft_of(party_id: int, craft_id: int, access: dict) -> tuple[dict, dict]:
    p = _party_access(party_id, access)
    c = store.party_craft(craft_id)
    if c is None or c["party_id"] != party_id:
        raise HTTPException(404, "Craft não encontrado (talvez tenha sido desfeito).")
    return p, c


@app.post("/api/parties/{party_id}/vault/crafts/{craft_id}")
def party_craft_edit(party_id: int, craft_id: int, body: PartyCraftEdit, access: dict = Depends(require_session)):
    """Item que saiu e venda (o valor só é pedido aqui, quando vender). Sem sold_total = ainda não vendido."""
    p, c = _party_craft_of(party_id, craft_id, access)
    s = rot.SETS[c["set_key"]]
    result = _clean_item(body.result) if body.result else c["result"]
    if result and result not in s["results"]:
        raise HTTPException(422, f"Escolha um dos itens: {', '.join(s['results'])}.")
    holder = _party_who(p, body.seller) if body.seller else c["holder"]
    if not body.sold_total:
        store.forget_payments("pcraft", craft_id)
    store.update_party_craft(craft_id, result=result, holder=holder, sold_total=body.sold_total,
                             market_fee=1 if body.sold_total and body.market_fee else 0,
                             sold_at=_now() if body.sold_total else None)
    return _party_vault_view(p, access)


@app.delete("/api/parties/{party_id}/vault/crafts/{craft_id}")
def party_craft_delete(party_id: int, craft_id: int, access: dict = Depends(require_session)):
    p, c = _party_craft_of(party_id, craft_id, access)
    if c["owner_key"] != access["key"] and p["owner_key"] != access["key"]:
        raise HTTPException(403, "Só quem registrou o craft (ou quem criou a party) pode desfazer.")
    store.delete_party_craft(craft_id)
    return _party_vault_view(p, access)


@app.post("/api/parties/{party_id}/vault/paid")
def party_paid(party_id: int, body: PartyPaidIn, access: dict = Depends(require_session)):
    """'Já paguei' / 'Recebi' de uma venda do cofre da party."""
    p = _party_access(party_id, access)
    view = _party_vault_view(p, access)
    rows = view["crafts"] if body.kind == "craft" else view["items"]
    x = next((r for r in rows if r["id"] == body.id), None) or {}
    pay_list = (x.get("service") or {}).get("transfers", []) if body.kind == "service" else x.get("transfers", [])
    t = next((t for t in pay_list if name_key(t["payer"]) == name_key(body.payer)
              and name_key(t["receiver"]) == name_key(body.receiver)), None)
    if t is None:
        raise HTTPException(404, "Essa transferência não existe.")
    if not (store.is_linked(access["key"], t["payer"]) or store.is_linked(access["key"], t["receiver"])):
        raise HTTPException(403, {"message": "Só quem paga ou quem recebe pode marcar essa transferência.", "hint": FORBIDDEN_HINT})
    store.set_paid({"item": "pitem", "craft": "pcraft", "service": "psvc"}[body.kind], body.id, t["payer"], t["receiver"], t["amount"],
                   access["key"], body.paid)
    return _party_vault_view(p, access)


def _registered_subs(players: list[str], kind: str) -> dict[str, str | None]:
    """🔁 Substitutos pelas parties registradas (kind = 'hunt' ou 'boss')."""
    return party_core.subs_from_parties(players, store.parties_with(players), kind)


@app.get("/api/rotations")
def rotations_catalog(_: dict = Depends(require_session)):
    """Grupos de bosses conhecidos e a regra da taxa do Market."""
    return {"groups": rot.catalog(), "fee": rot.fee_rule(), "fee_rules": [{"since": s[:10], "pct": p, "cap": c}
                                                                          for s, p, c in rot.FEE_RULES], "fee_min": rot.FEE_MIN}


# ------------------------------------------------------------------ 0.23.0: 🤝 quem jogou a sessão (dono marca)
class PlayerIn(BaseModel):
    other: bool
    played_by: Name | None = None


def _mark_session(table: str, session_id: int, body: PlayerIn, access: dict) -> dict:
    row = store.solo_session(session_id) if table == "solo_sessions" else store.boss_session(session_id)
    if row is None:
        raise HTTPException(404, "Sessão não encontrada.")
    if not store.is_linked(access["key"], row["name"]):
        raise HTTPException(403, "Só o dono do personagem pode alterar isso.")
    played_by = _clean_name(body.played_by) if body.other else None
    store.set_session_player(table, session_id, body.other, played_by)
    return {"other_player": body.other, "played_by": played_by}


@app.post("/api/stacker/session/{session_id}/player")
def solo_player(session_id: int, body: PlayerIn, access: dict = Depends(require_session)):
    return _mark_session("solo_sessions", session_id, body, access)


@app.post("/api/bosses/session/{session_id}/player")
def boss_player(session_id: int, body: PlayerIn, access: dict = Depends(require_session)):
    return _mark_session("boss_sessions", session_id, body, access)


# ------------------------------------------------------------------ 0.23.0: 🤝 links de envio (dono)
class LinkIn(BaseModel):
    character: Name
    operator: Name | None = None
    scopes: Annotated[list[Literal["solo", "party", "boss"]], Field(min_length=1, max_length=3)]
    hours: int = 24
    max_uses: int = Field(default=10, ge=1, le=50)


def _link_out(link: dict) -> dict:
    state = ("revoked" if link["revoked_at"] else "used" if link["uses"] >= link["max_uses"]
             else "active" if link["active"] else "expired")
    return {"id": link["id"], "character": link["name"], "operator": link["operator"], "scopes": link["scopes"],
            "created_at": link["created_at"], "expires_at": link["expires_at"], "max_uses": link["max_uses"],
            "uses": link["uses"], "state": state}


@app.post("/api/links")
def create_link(body: LinkIn, access: dict = Depends(require_session)):
    """Link de envio: quem receber envia os analyzers deste personagem (o link só envia; não lê nada)."""
    name = require_uploader(body.character, access)
    if body.hours not in LINK_HOURS:
        raise HTTPException(422, "Validade inválida.")
    operator = _clean_name(body.operator)
    if operator and store.is_linked(access["key"], operator):
        raise HTTPException(422, "Esse personagem já é seu. Informe o personagem de quem vai jogar por você.")
    if store.active_links_count(access["key"]) >= store.MAX_ACTIVE_LINKS:
        raise HTTPException(429, f"Você já tem {store.MAX_ACTIVE_LINKS} links de envio valendo. Cancele um para criar outro.")
    link, token = store.create_link(access["key"], name, operator, sorted(set(body.scopes)), body.hours, body.max_uses)
    return {"link": _link_out(link), "token": token}


@app.delete("/api/links/{link_id}")
def revoke_link(link_id: int, access: dict = Depends(require_session)):
    if not store.revoke_link(link_id, access["key"]):
        raise HTTPException(404, "Link não encontrado (ou já cancelado).")
    return {"links": [_link_out(x) for x in store.links_of(access["key"])]}


@app.get("/api/subs")
def subs_overview(access: dict = Depends(require_session)):
    """🤝 Substituições: meus links, por quem eu posso enviar (jogador autorizado) e o que joguei por outra pessoa."""
    chars = [c["name"] for c in store.key_chars(access["key"])]
    grants = [{"id": g["id"], "character": g["name"], "as": g["operator"], "scopes": g["scopes"],
               "expires_at": g["expires_at"], "uses_left": g["max_uses"] - g["uses"]}
              for g in store.grants_for(chars) if g["owner_key"] != access["key"]]
    return {"links": [_link_out(x) for x in store.links_of(access["key"])], "grants": grants,
            "played": store.played_for(chars), "hours": list(LINK_HOURS), "max_active": store.MAX_ACTIVE_LINKS}


# ------------------------------------------------------------------ 0.23.0: 🤝 página do link de envio (sem conta)
class LinkTokenIn(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=100)]


class LinkSendIn(LinkTokenIn):
    raw_text: Annotated[str, Field(min_length=1, max_length=RAW_MAX)]
    kind: Literal["hunt", "boss"] = "hunt"
    captcha: dict = Field(default_factory=dict)


def _open_link(token: str, request: Request) -> dict:
    ip = client_ip(request)
    _check_blocked(ip)
    link = store.link_by_token(token)
    if link is None:
        _record_fail(ip)  # adivinhar link conta como tentativa errada (bloqueia o IP)
        raise HTTPException(404, {"message": LINK_NOT_FOUND, "reason": "link"})
    if not link["active"]:
        raise HTTPException(410, {"message": LINK_CLOSED, "reason": "link"})
    return link


def _link_info(link: dict) -> dict:
    return {"character": link["name"], "operator": link["operator"], "scopes": link["scopes"],
            "expires_at": link["expires_at"], "uses_left": link["max_uses"] - link["uses"]}


@app.post("/api/link/info")
def link_info(body: LinkTokenIn, request: Request):
    return _link_info(_open_link(body.token, request))


@app.post("/api/link/send")
def link_send(body: LinkSendIn, request: Request):
    """Quem recebeu o link cola o analyser: fica salvo para o dono, marcado como jogado por outra pessoa."""
    link = _open_link(body.token, request)
    try:
        captcha.verify(CAPTCHA_SECRET, body.captcha, _captcha_used)
    except captcha.CaptchaError:
        raise HTTPException(400, {"message": CAPTCHA_FAILED, "reason": "captcha"})
    char, owner, text = link["name"], link["owner_key"], body.raw_text
    who = _who("link", link["operator"])
    scope_err = "Esse link não aceita esse tipo de envio. Peça um link que aceite"

    def need(scope: str, label: str) -> None:
        if scope not in link["scopes"]:
            raise HTTPException(403, f"{scope_err} {label}.")

    if "loot type" in text.lower():  # Party Hunt Analyser
        report = _parse_party(text)
        if name_key(char) not in {name_key(p["name"]) for p in report["players"]}:
            raise HTTPException(422, f"{char} não está nesse Party Hunt Analyser.")
        _in_link_window(link, report["started_at"])
        if body.kind == "boss":
            need("boss", "o lootsplit de bosses")
            _spend_link(link)
            hunt, created = store.add_boss_hunt(report, char, owner, via="link")
            _link_party_sessions(report, hunt)
            saved = "boss_lootsplit"
        else:
            need("party", "o lootsplit da PT")
            _spend_link(link)
            hunt, created = store.add_hunt(report, text, char, owner, via="link")
            saved = "lootsplit"
        tagged = store.set_tag("boss" if body.kind == "boss" else "hunt", hunt["id"], char, "other", True,
                               link["operator"], None)
        created = created or tagged
        summary = {"players": len(report["players"]), "profit_each": report["profit_each"],
                   "duration_seconds": report.get("duration_seconds")}
    else:  # Hunt Session Analyser
        try:
            session = parse_solo_session(text)
        except ParseError as e:
            raise HTTPException(422, str(e))
        _in_link_window(link, session.started_at)
        data = session.to_dict()
        if body.kind == "boss":
            need("boss", "as sessões de boss")
            _check_duplicate("boss_sessions", data, char, owner)
            party = _hunts_at([char], session.started_at, session.ended_at, boss=True)
            _spend_link(link)
            row, created = store.add_boss_session(char, "boss|" + session.fingerprint(char), data,
                                                  "party" if party else "solo", owner, who)
            if not row["boss_hunt_id"]:
                _link_session_to_party(row)
            saved = "boss_session"
        else:
            hunt = None
            if "party" in link["scopes"] and store.player_type(owner) in _sharing_types():
                found = _hunts_at([char], session.started_at, session.ended_at)
                hunt = found[0][1] if found else None
            if hunt:
                _spend_link(link)
                _, created = store.add_party_session(hunt["id"], char, data, owner, who)
                saved = "party_session"
            else:
                need("solo", "as sessões do Hunt Session Stacker")
                _check_duplicate("solo_sessions", data, char, owner)
                _spend_link(link)
                _, created = store.add_solo(char, session.fingerprint(char), data, owner, text, None, None, who)
                saved = "stacker"
        summary = {"xp": session.xp, "balance": session.balance, "duration_seconds": session.duration_seconds}
    if not created:
        store.refund_link(link["id"])
    fresh = store.link(link["id"])
    return {"ok": True, "created": created, "saved": saved, "character": char, "summary": summary,
            "uses_left": fresh["max_uses"] - fresh["uses"]}


# ------------------------------------------------------------------ administração (só o criador)
ADMIN_REMOTE_BLOCKED = "O painel de administração só funciona no próprio PC do servidor (http://localhost:8000/admin)."
_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded", "ngrok-trace-id")


def require_admin(request: Request, x_admin_token: str = Header(default="")) -> None:
    # Tudo que chega pelo túnel (ngrok) traz cabeçalhos de proxy: o painel não aceita acesso pela internet.
    if any(h in request.headers for h in _PROXY_HEADERS):
        raise HTTPException(403, ADMIN_REMOTE_BLOCKED)
    ip = "admin:" + client_ip(request)
    _check_blocked(ip)
    if not secrets.compare_digest(x_admin_token, CONFIG["admin_token"]):
        _record_fail(ip)
        raise HTTPException(401, "Senha de administrador inválida.")


class NewKeyIn(BaseModel):
    label: str = ""
    days: int = 7   # 0.15.0: ignorado; toda chave nasce com NEW_KEY_DAYS


NEW_KEY_DAYS = 7   # 0.15.0: toda chave nova (painel ou loja) começa com 7 dias


class DaysIn(BaseModel):
    days: int


def _admin_key(key: str) -> dict:
    k = store.get_key(key)  # 0.17.0: inclui chave vencida de conta (o adm pode renovar)
    if k is None:
        raise HTTPException(404, "Código não encontrado (ou já vencido e apagado).")
    return k


@app.get("/api/admin/keys", dependencies=[Depends(require_admin)])
def admin_keys():
    store.purge_expired()
    keys = store.keys_overview()
    for k in keys:  # 0.20.0: tipo de player de cada conta
        k["player_type"] = store.player_type(k["key"]) if store.player_type_chosen(k["key"]) else None
    return keys


# ------------------------------------------------------------------ 0.20.0: hunts de um personagem (local e trocas)
class AdminPlaceIn(BaseModel):
    kind: Literal["solo", "hunt"]
    id: int = Field(ge=1)
    place_id: int | None = Field(default=None, ge=1)
    reset_edits: bool = False


@app.get("/api/admin/chars/{name}/hunts", dependencies=[Depends(require_admin)])
def admin_char_hunts(name: str):
    """Sessões do Stacker e lootsplits do personagem, com o local e quantas trocas já foram usadas."""
    places: dict = {}
    sessions = [{"id": s["id"], "started_at": s["started_at"], "duration_seconds": s["duration_seconds"], "xp": s["xp"],
                 "balance": s["balance"], "place": _place_ref(s.get("place_id"), places), "place_edits": s.get("place_edits", 0)}
                for s in store.solo_for_player(name)]
    hunts = [{"id": h["id"], "started_at": h["started_at"], "duration_seconds": h["duration_seconds"],
              "players": [p["name"] for p in h["players"]], "place": _place_ref(h.get("place_id"), places),
              "place_edits": h.get("place_edits", 0)}
             for h in store.hunts_for_player(name)]
    return {"name": name, "sessions": sessions, "hunts": hunts, "edit_limit": PLACE_EDIT_LIMIT}


# 0.22.1: 📅 calendário — o administrador cola o HTML do Event Schedule do tibia.com; o servidor guarda só os dados
class CalendarIn(BaseModel):
    raw_html: Annotated[str, Field(min_length=20, max_length=400_000)]


@app.get("/api/admin/calendar", dependencies=[Depends(require_admin)])
def admin_calendar():
    return store.calendar_months()


@app.post("/api/admin/calendar", dependencies=[Depends(require_admin)])
def admin_calendar_save(body: CalendarIn):
    try:
        data = tibiacal.parse_calendar(body.raw_html)
    except tibiacal.CalendarError as e:
        raise HTTPException(422, str(e))
    store.save_calendar(data["month"], data, body.raw_html)
    busy = sum(1 for k, v in data["days"].items() if v and k.startswith(data["month"]))
    return {"month": data["month"], "events": sorted(data["events"]), "days_with_events": busy}


@app.delete("/api/admin/calendar/{month}", dependencies=[Depends(require_admin)])
def admin_calendar_undo(month: str):
    if not re.fullmatch(r"\d{4}-\d{2}", month) or not store.delete_calendar_latest(month):
        raise HTTPException(404, "Nenhum calendário desse mês.")
    return {"ok": True}


@app.get("/api/admin/places", dependencies=[Depends(require_admin)])
def admin_places():
    return [{"id": p["id"], "name": p["name"], "city": p.get("city")} for p in store.places()]


@app.post("/api/admin/place", dependencies=[Depends(require_admin)])
def admin_place(body: AdminPlaceIn):
    """O administrador troca o local (sem gastar as trocas da pessoa) e/ou libera de novo as 2 trocas."""
    table = "solo_sessions" if body.kind == "solo" else "hunts"
    if store.place_state(table, body.id) is None:
        raise HTTPException(404, "Não encontrado (talvez tenha sido apagado).")
    if body.place_id is not None:
        if store.place(body.place_id) is None:
            raise HTTPException(404, "Hunt não encontrada.")
        store.update_place(table, body.id, body.place_id, False)
    if body.reset_edits:
        store.reset_place_edits(table, body.id)
    st = store.place_state(table, body.id)
    return {"place": _place_ref(st["place_id"], {}), "place_edits": st["place_edits"], "edit_limit": PLACE_EDIT_LIMIT}


VIGIA_FILE = DATA_DIR / "vigia.json"  # escrito pelo tools/vigia.ps1 (Agendador do Windows)


@app.get("/api/admin/status", dependencies=[Depends(require_admin)])
def admin_status():
    """Backups automáticos e o último resultado do vigia do site (painel do criador)."""
    backups = sorted((p.name for p in BACKUP_DIR.glob("artemis-*.db")), reverse=True) if BACKUP_DIR.exists() else []
    try:
        vigia = json.loads(VIGIA_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        vigia = None
    return {"last_backup": store.meta("last_backup"), "backups": backups, "keep": BACKUP_KEEP, "vigia": vigia,
            "store_free": _store_free_on()}


@app.post("/api/admin/keys", dependencies=[Depends(require_admin)])
def admin_create(body: NewKeyIn):
    try:
        return store.create_key(NEW_KEY_DAYS, body.label.strip())
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/admin/keys/renew-all", dependencies=[Depends(require_admin)])
def admin_renew_all(body: DaysIn):
    try:
        return {"renewed": store.renew_all(body.days)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/admin/keys/{key}/renew", dependencies=[Depends(require_admin)])
def admin_renew(key: str, body: DaysIn):
    _admin_key(key)
    try:
        return store.renew_key(key, body.days)
    except ValueError as e:
        raise HTTPException(422, str(e))


class OnIn(BaseModel):
    on: bool


@app.post("/api/admin/keys/{key}/lifetime", dependencies=[Depends(require_admin)])
def admin_lifetime(key: str, body: OnIn):
    """"Amigo do adm": o código nunca vence (o vencimento some para a pessoa)."""
    _admin_key(key)
    return store.set_lifetime(key, body.on)


@app.get("/api/admin/keys/{key}/logins", dependencies=[Depends(require_admin)])
def admin_logins(key: str):
    return store.logins(key)


@app.get("/api/admin/screens", dependencies=[Depends(require_admin)])
def admin_screens(days: int = 7):
    days = 30 if days == 30 else 7
    since = ach.local_day(datetime.now(timezone.utc).isoformat()) - timedelta(days=days - 1)
    return {"days": days, "screens": store.screen_report(since.isoformat())}


_MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


@app.get("/api/admin/report", dependencies=[Depends(require_admin)])
def admin_report(month: str = ""):
    """0.21.0: números do mês para o relatório de visitas (fansites@tibia.com, até o dia 3)."""
    if not month:  # padrão: o mês que acabou (é ele que vai no relatório do começo do mês)
        today = ach.local_day(datetime.now(timezone.utc).isoformat())
        month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if not _MONTH_RE.fullmatch(month):
        raise HTTPException(422, "Mês no formato AAAA-MM.")
    return store.month_report(month)


@app.get("/api/admin/contacts", dependencies=[Depends(require_admin)])
def admin_contacts():
    """0.21.0: mensagens da tela de contato (e quantos robôs caíram no campo escondido)."""
    return {**store.contacts(), "email_on": mailer.configured(), "to": CONTACT_EMAIL}


@app.post("/api/admin/contacts/{contact_id}/read", dependencies=[Depends(require_admin)])
def admin_contact_read(contact_id: int, body: OnIn):
    if not store.mark_contact(contact_id, read=body.on):
        raise HTTPException(404, "Mensagem não encontrada.")
    return {"read": body.on}


RECOVERY_LABEL = {"lost_code":"Código de acesso: perdeu o código", "char_taken": "Código de acesso: personagem já tem código",
                  "key_taken": "Código de acesso: código já está em outra conta",
                  "lost_login": "Conta/senha: esqueceu a conta ou a senha"}


@app.get("/api/admin/recovery", dependencies=[Depends(require_admin)])
def admin_recovery():
    """0.16.0: quem pediu ajuda para recuperar o código (o painel abre o WhatsApp).
    0.17.0: também "esqueceu conta/senha", com as contas que batem com o que a pessoa lembra."""
    out = []
    for r in store.open_recoveries():
        acc = store.account(r["account_id"]) if r["account_id"] else None
        owner = store.char_owner(r["character"]) if r["character"] else None
        candidates = {}
        if r["reason"] == "lost_login":
            for a in (store.account_by_name(r["username"]), store.account_for_key(owner) if owner else None):
                if a:
                    candidates[a["id"]] = {"id": a["id"], "username": a["username"], "key": a["access_key"]}
        out.append({**r, "kind": "login" if r["reason"] == "lost_login" else "code",
                    "reason_label": RECOVERY_LABEL.get(r["reason"], r["reason"]),
                    "account_key": acc["access_key"] if acc else None, "char_key": owner,
                    "candidates": list(candidates.values())})
    return out


@app.post("/api/admin/accounts/{account_id}/reset-code", dependencies=[Depends(require_admin)])
def admin_reset_code(account_id: int):
    """0.17.0: código de uso único (24 h) para a pessoa criar nova senha. O adm nunca vê nem define a senha."""
    acc = store.account(account_id)
    if acc is None:
        raise HTTPException(404, "Conta não encontrada.")
    return {"username": acc["username"], "code": store.new_reset_code(account_id), "hours": store.RESET_HOURS}


@app.post("/api/admin/recovery/{request_id}/done", dependencies=[Depends(require_admin)])
def admin_recovery_done(request_id: int):
    if not store.finish_recovery(request_id):
        raise HTTPException(404, "Pedido não encontrado (ou já resolvido).")
    return {"done": True}


@app.post("/api/admin/store", dependencies=[Depends(require_admin)])
def admin_store(body: OnIn):
    store.set_meta("store_free", "on" if body.on else "off")
    return {"free": body.on}


@app.post("/api/admin/keys/{key}/trust", dependencies=[Depends(require_admin)])
def admin_force_main(key: str, body: CharIn):
    _admin_key(key)
    ch = char_or_404(body.character, fresh=True)
    _admin_char_free(key, ch.name)
    store.force_main(key, ch.name)
    return {"key": normalize_key(key), "main_char": ch.name, "trusted": True}


def _admin_char_free(key: str, name: str) -> None:
    owner = store.char_owner(name)
    if owner and owner != normalize_key(key):
        raise HTTPException(409, f"{name} já está na chave {owner}. Tire de lá (Resetar dono) antes.")
    if not owner and store.char_count(key) >= store.MAX_CHARS_PER_KEY:
        raise HTTPException(400, f"Essa chave já tem {store.MAX_CHARS_PER_KEY} personagens.")


@app.post("/api/admin/keys/{key}/chars", dependencies=[Depends(require_admin)])
def admin_add_char(key: str, body: CharIn):
    """0.15.0: validação manual — o criador vincula um personagem sem código de verificação."""
    _admin_key(key)
    ch = char_or_404(body.character, fresh=True)
    _admin_char_free(key, ch.name)
    store.add_char_manual(key, ch.name)
    return {"key": normalize_key(key), "character": ch.name, "chars": store.key_chars(normalize_key(key))}


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


@app.get("/admin.js", include_in_schema=False)
def admin_script(request: Request):
    """0.17.0: script do painel fora do HTML (CSP sem 'unsafe-inline'); só no PC do criador, como o painel."""
    if any(h in request.headers for h in _PROXY_HEADERS):
        raise HTTPException(404)
    return FileResponse(WEB_DIR / "admin.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/app.js", include_in_schema=False)
def app_script():
    """0.17.0: script do site fora do HTML (CSP sem 'unsafe-inline')."""
    return FileResponse(WEB_DIR / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ site
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/envio", include_in_schema=False)
def link_page():
    """0.23.0: página do link de envio (o código do link fica depois do #, que nunca chega ao servidor)."""
    return FileResponse(WEB_DIR / "envio.html", headers={"Cache-Control": "no-cache"})


@app.get("/envio.js", include_in_schema=False)
def link_script():
    return FileResponse(WEB_DIR / "envio.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


# Ícone do app na tela inicial (só é instalado se a pessoa tocar em "Sim" no aviso do site).
_STATIC = {"manifest.webmanifest": "application/manifest+json", "icon-192.png": "image/png",
           "icon-512.png": "image/png", "icon-maskable.png": "image/png",
           # 0.21.0: Fankit oficial da CipSoft (logo do Tibia no rodapé e arte das vocações)
           **{f"fk-{n}.png": "image/png" for n in ("tibia-logo", "voc-knight", "voc-paladin", "voc-druid", "voc-sorcerer")}}
# 0.19.0: idiomas (motor + dicionários). Sem cache longo: tradução nova chega na hora.
I18N_LANGS = ("en", "es", "ja", "de", "pl", "fr", "ru")  # 0.20.0: + alemão, polonês, francês e russo
_I18N = {"i18n.js": "text/javascript", **{f"i18n-{c}.json": "application/json" for c in I18N_LANGS}}


@app.get("/{filename}", include_in_schema=False)
def static_file(filename: str):
    if filename in _I18N:
        return FileResponse(WEB_DIR / filename, media_type=_I18N[filename], headers={"Cache-Control": "no-cache"})
    if filename not in _STATIC:  # lista fechada: nenhum outro arquivo da pasta sai por aqui
        raise HTTPException(404)
    return FileResponse(WEB_DIR / filename, media_type=_STATIC[filename], headers={"Cache-Control": "max-age=86400"})
