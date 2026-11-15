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
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import re
from collections import deque
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from artemis import APP_NAME, __version__
from artemis.core import achievements as ach
from artemis.core import bosses as boss_core
from artemis.core.parser import ParseError
from artemis.core.report import profit_of, report_from_text
from artemis.core.session import item_key, parse_solo_session
from artemis.core.levels import level_for_xp, xp_at, xp_to_next_level
from artemis.core.tibiadata import TibiaDataError, fetch_character, fetch_experience

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
    tasks = [asyncio.create_task(purge_loop()), asyncio.create_task(backup_loop())]
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
UPLOAD_PATHS = {"/api/lootsplit", "/api/stacker", "/api/places", "/api/lootsplit/preview",
                "/api/bosses/session", "/api/bosses/lootsplit", "/api/store/free",
                "/api/account/register", "/api/recovery", "/api/recovery/login"}
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
            "chars": store.key_chars(access["key"])}


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


CHANGELOG_FILE = Path(__file__).resolve().parent.parent / "data" / "changelog.json"


@app.get("/api/changelog")
def changelog():
    """Novidades de cada versão (aba 📰 Novidades). Público: não tem dado de ninguém."""
    try:
        data = json.loads(CHANGELOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"releases": []}
    return {"version": __version__, "releases": data.get("releases", [])}


@app.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "version": __version__}


# ------------------------------------------------------------------ download do instalador (botão do site)
# O instalador fica nas Releases públicas do GitHub. O latest.json da última versão diz o endereço exato e o
# SHA-256 do arquivo; com o SHA-256 o site mostra o link do relatório do VirusTotal daquela versão.
RELEASES_REPO = "https://github.com/50nnyc/4rt3mi5"
RELEASE_MANIFEST_URL = f"{RELEASES_REPO}/releases/latest/download/latest.json"
RELEASES_PAGE = f"{RELEASES_REPO}/releases/latest"
DL_CACHE_OK, DL_CACHE_FAIL = 600, 60   # segundos: guarda a resposta do GitHub (e um erro por pouco tempo)
_dl_cache: dict = {"at": -1e9, "ttl": 0, "info": None}
_VERSION_RX = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}")
_SHA_RX = re.compile(r"[0-9a-f]{64}")


def _parse_manifest(raw: bytes) -> dict | None:
    """Valida o latest.json: só aceita instalador do próprio repositório, com versão e SHA-256 no formato certo."""
    try:
        m = json.loads(raw.decode("utf-8-sig"))  # o build.ps1 grava com BOM
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(m, dict):
        return None
    version, url, sha = str(m.get("version", "")), str(m.get("url", "")), str(m.get("sha256", "")).lower()
    expected = f"{RELEASES_REPO}/releases/download/v{version}/4rt3mi5-Setup-{version}.exe"
    if not _VERSION_RX.fullmatch(version) or url != expected or not _SHA_RX.fullmatch(sha):
        return None
    # 0.17.1: a Release também traz o launcher congelado (sempre os mesmos bytes, então o SmartScreen não reclama).
    # Quando o manifesto diz o SHA-256 dele, o botão do site entrega o launcher no lugar do instalador da versão.
    lsha = str(m.get("launcher_sha256", "")).lower()
    if _SHA_RX.fullmatch(lsha):
        url, sha = f"{RELEASES_REPO}/releases/download/v{version}/4rt3mi5-Launcher.exe", lsha
    return {"version": version, "url": url, "sha256": sha, "virustotal": f"https://www.virustotal.com/gui/file/{sha}"}


def _fetch_manifest() -> dict | None:
    import urllib.request
    try:
        req = urllib.request.Request(RELEASE_MANIFEST_URL, headers={"User-Agent": "4rt3mi5-server"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return _parse_manifest(r.read(20_000))
    except OSError:
        return None


def download_info() -> dict | None:
    now = time.monotonic()
    if now - _dl_cache["at"] > _dl_cache["ttl"]:
        info = _fetch_manifest()
        _dl_cache.update(at=now, ttl=DL_CACHE_OK if info else DL_CACHE_FAIL, info=info)
    return _dl_cache["info"]


@app.get("/api/download")
def download_meta():
    """Versão, link e VirusTotal do instalador para Windows (público; o botão do site usa)."""
    info = download_info()
    if not info:
        return {"available": False, "page": RELEASES_PAGE}
    return {"available": True, "version": info["version"], "url": "/download", "sha256": info["sha256"],
            "virustotal": info["virustotal"], "page": RELEASES_PAGE}


@app.get("/download", include_in_schema=False)
def download_redirect():
    """Endereço curto e fixo do instalador: manda para o arquivo da última versão no GitHub."""
    info = download_info()
    return RedirectResponse(info["url"] if info else RELEASES_PAGE, status_code=302,
                            headers={"Cache-Control": "no-store"})


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
TRACK_PAGES = {"home", "loot", "stack", "boss", "hunts", "rank", "ach", "chars", "news"}


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


CHAR_TAKEN = "Este character já possui código de acesso."


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
    ch = char_or_404(body.character)
    _check_char_free(access["key"], ch.name)
    # Contato de confiança (main forçado pelo criador): entra direto, sem código de verificação.
    if access.get("trusted") and store.is_linked(access["key"], ch.name):
        token = device or store.issue_device(access["key"], ch.name)
        _log_login(request, access)
        return {"token": token, "character": ch.name, "me": me_payload(access), "trusted": True}
    # Código já tem dono: um aparelho novo só pode verificar com um personagem já vinculado.
    if access.get("main_char") and device is None and not store.is_linked(access["key"], ch.name):
        raise HTTPException(403, KEY_TAKEN)
    v = store.start_verification(access["key"], ch.name)
    return {"code": v["code"], "character": ch.name, "expires_at": v["expires_at"]}


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
    _log_login(request, access)
    return {"token": token, "character": ch.name, "me": me_payload(access)}


@app.get("/api/me")
def me(access: dict = Depends(require_session)):
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


def _set_rules(kind: str, hunt_id: int, body: RulesIn, access: dict) -> dict:
    """Regras de divisão: só quem enviou o lootsplit define. Zera as marcações de "já paguei"."""
    h = _load_hunt(kind, hunt_id)
    if h.get("uploader_key") != access["key"]:
        raise HTTPException(403, "Só quem enviou o lootsplit pode mudar as regras de divisão.")
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
    return {"hunt": _public(_load_hunt(kind, hunt_id), access)}


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
    return {"hunt": _public(_load_hunt(kind, hunt_id), access)}


@app.post("/api/hunt/{hunt_id}/rules")
def hunt_rules(hunt_id: int, body: RulesIn, access: dict = Depends(require_session)):
    return _set_rules("hunt", hunt_id, body, access)


@app.post("/api/hunt/{hunt_id}/paid")
def hunt_paid(hunt_id: int, body: PaidIn, access: dict = Depends(require_session)):
    return _set_paid("hunt", hunt_id, body, access)


@app.post("/api/lootsplit/preview")
def lootsplit_preview(body: UploadIn, _: dict = Depends(require_session)):
    """Só calcula, sem salvar (usado quando o envio não é permitido)."""
    return _parse_party(body.raw_text)


@app.post("/api/lootsplit")
def lootsplit_upload(body: UploadIn, access: dict = Depends(require_session)):
    report = _parse_party(body.raw_text)
    uploader = require_uploader(body.nickname, access)
    hunt, created = store.add_hunt(report, body.raw_text, uploader, access["key"])
    return {"created": created, "hunt": _public(hunt, access), "rewards": grant_rewards(access["key"])}


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
    return sessions, prices


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


class PlaceSet(BaseModel):
    place_id: int | None = Field(default=None, ge=1)


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


# ------------------------------------------------------------------ 🥇 ranking entre amigos (só quem aceitar)
RANKING_METRICS = {"xp", "xp_h", "profit", "profit_h", "hours"}


class RankingJoinIn(BaseModel):
    join: bool


@app.get("/api/ranking")
def ranking(period: int = 7, metric: str = "xp", nick: str = "", _: dict = Depends(require_session)):
    """Ranking das sessões do Stacker de quem entrou no ranking. Quem não entrou nunca aparece."""
    period = period if period in (7, 30) else 7
    metric = metric if metric in RANKING_METRICS else "xp"
    since = (datetime.now() - timedelta(days=period)).isoformat(timespec="seconds")
    rows = []
    for r in store.ranking_rows(since):
        secs = r["seconds"]
        rows.append({"name": r["name"], "vocation": r["vocation"], "level": r["level"], "sessions": r["sessions"],
                     "xp": r["xp"], "profit": r["balance"], "hours": round(secs / 3600, 1),
                     "xp_h": _per_hour(r["xp"], secs), "profit_h": _per_hour(r["balance"], secs)})
    rows.sort(key=lambda r: (-r[metric], r["name"]))
    return {"period": period, "metric": metric, "rows": rows, "joined": bool(nick) and store.ranking_member(nick)}


@app.post("/api/ranking/{name}")
def ranking_join(name: str, body: RankingJoinIn, access: dict = Depends(require_session)):
    """Entrar/sair do ranking: só o dono do personagem decide."""
    real = require_uploader(name, access)
    store.ranking_join(real, body.join)
    return {"joined": store.ranking_member(real)}


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
    return {"created": created, "session": _public(row, access), "rewards": grant_rewards(access["key"]),
            "rare": _session_rare(session, False, access) if created else [],
            "compare": _compare_with_average(name, row)}


COMPARE_MIN_SECONDS = 600  # sessões curtas distorcem a média (mesmo corte do ranking de Hunts)


def _compare_with_average(name: str, row: dict) -> dict | None:
    """Sessão x média do próprio personagem na mesma hunt (XP/h e balance/h)."""
    place = store.place(row["place_id"]) if row.get("place_id") else None
    if place is None or row["duration_seconds"] < COMPARE_MIN_SECONDS:
        return None
    others = [s for s in store.solo_for_player(name)
              if s["place_id"] == place["id"] and s["id"] != row["id"] and s["duration_seconds"] >= COMPARE_MIN_SECONDS]
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
    row, created = store.add_boss_session(name, "boss|" + session.fingerprint(name), session.to_dict(), body.mode,
                                          access["key"])
    hunt = store.boss_hunt(row["boss_hunt_id"]) if row["boss_hunt_id"] else _link_session_to_party(row)
    return {"created": created, "session_id": row["id"], "mode": row["mode"],
            "bosses": boss_core.bosses_in(session.kills),
            "rare": _session_rare(session, True, access) if created else [],
            "party": _hunt_brief(hunt) if hunt else None, "rewards": grant_rewards(access["key"])}


@app.post("/api/bosses/lootsplit")
def boss_lootsplit(body: BossSplitIn, access: dict = Depends(require_session)):
    """Lootsplit de bosses: aparece na aba de bosses de todos da PT e puxa as sessões deles do mesmo horário."""
    report = _parse_party(body.raw_text)
    uploader = require_uploader(body.nickname, access)
    players = {name_key(p["name"]) for p in report["players"]}
    if name_key(uploader) not in players:
        raise HTTPException(403, {"message": NOT_IN_PARTY, "hint": "Envie o lootsplit com o personagem que estava na PT."})
    own = None
    if body.session_id is not None:
        own = store.boss_session(body.session_id)
        if own is None:
            raise HTTPException(404, "Sessão de boss não encontrada.")
        if own["uploader_key"] != access["key"] or own["name_key"] != name_key(uploader):
            raise HTTPException(403, "Essa sessão não é sua.")
    hunt, created = store.add_boss_hunt(report, uploader, access["key"])
    linked = 0
    if own is not None:
        store.link_boss_session(own["id"], hunt["id"])
        linked += 1
    for s in store.unlinked_boss_sessions([p["name"] for p in report["players"]]):
        if boss_core.overlaps(s["started_at"], s["ended_at"], hunt["started_at"], hunt["ended_at"]):
            store.link_boss_session(s["id"], hunt["id"])
            linked += 1
    return {"created": created, "hunt": _public(hunt, access), "linked": linked, "rewards": grant_rewards(access["key"])}


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
    hunts = {h["id"]: _public(h, access) for h in store.boss_hunts_for(name)}
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

    for h in hunts.values():
        h["members"] = [m["name"] for m in store.boss_sessions_of_hunt(h["id"])]
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
            "no_npc": no_npc, "unpriced": sum(1 for k in no_npc if not prices[k]["unit_price"])}


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
    return store.keys_overview()


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


RECOVERY_LABEL = {"lost_code": "Código de acesso: perdeu o código", "char_taken": "Código de acesso: personagem já tem código",
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


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


# Ícone do app na tela inicial (só é instalado se a pessoa tocar em "Sim" no aviso do site).
_STATIC = {"manifest.webmanifest": "application/manifest+json", "icon-192.png": "image/png",
           "icon-512.png": "image/png", "icon-maskable.png": "image/png"}


@app.get("/{filename}", include_in_schema=False)
def static_file(filename: str):
    if filename not in _STATIC:  # lista fechada: nenhum outro arquivo da pasta sai por aqui
        raise HTTPException(404)
    return FileResponse(WEB_DIR / filename, media_type=_STATIC[filename], headers={"Cache-Control": "max-age=86400"})
