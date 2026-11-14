"""Banco de dados SQLite (abre no DB Browser for SQLite: data/artemis.db)."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from artemis.core.report import apply_rules

MAX_KEY_DAYS = 30


def hash_token(token: str) -> str:
    """Hash do token de aparelho: o banco guarda só isto, nunca o token."""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()
_KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I para não confundir

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_keys (
    key         TEXT PRIMARY KEY,
    label       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    main_char   TEXT,           -- definido na primeira verificação; prende o código ao dono
    trusted     INTEGER NOT NULL DEFAULT 0  -- contato de confiança: entra sem código de verificação
);
-- personagens comprovados (código de verificação no comentário) de cada código de acesso
CREATE TABLE IF NOT EXISTS key_chars (
    key          TEXT NOT NULL REFERENCES access_keys(key) ON DELETE CASCADE,
    name_key     TEXT NOT NULL,
    name         TEXT NOT NULL,
    verified_at  TEXT NOT NULL,
    PRIMARY KEY (key, name_key)
);
-- aparelhos (app/navegador) liberados para um código de acesso
CREATE TABLE IF NOT EXISTS devices (
    token       TEXT PRIMARY KEY,
    key         TEXT NOT NULL REFERENCES access_keys(key) ON DELETE CASCADE,
    character   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
-- códigos de verificação pendentes (valem 1 hora)
CREATE TABLE IF NOT EXISTS verifications (
    code        TEXT PRIMARY KEY,
    key         TEXT NOT NULL REFERENCES access_keys(key) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hunts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT UNIQUE NOT NULL,
    started_at    TEXT NOT NULL,
    submitted_by  TEXT,
    created_at    TEXT NOT NULL,
    raw_text      TEXT,
    report_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hunt_players (
    hunt_id  INTEGER NOT NULL REFERENCES hunts(id) ON DELETE CASCADE,
    name_key TEXT NOT NULL,
    name     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_hunt_players_name ON hunt_players(name_key);
CREATE INDEX IF NOT EXISTS ix_hunts_started ON hunts(started_at);
CREATE TABLE IF NOT EXISTS solo_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint      TEXT UNIQUE NOT NULL,
    name_key         TEXT NOT NULL,
    name             TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    ended_at         TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    session_label    TEXT,
    raw_xp           INTEGER NOT NULL DEFAULT 0,
    xp               INTEGER NOT NULL DEFAULT 0,
    supplies         INTEGER NOT NULL DEFAULT 0,
    balance          INTEGER NOT NULL DEFAULT 0,
    damage           INTEGER NOT NULL DEFAULT 0,
    damage_h         INTEGER NOT NULL DEFAULT 0,
    healing          INTEGER NOT NULL DEFAULT 0,
    healing_h        INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_solo_name ON solo_sessions(name_key, started_at);
-- 0.6.0: criaturas mortas e itens coletados em cada sessão do Stacker (nunca apagados por período)
CREATE TABLE IF NOT EXISTS solo_kills (
    session_id INTEGER NOT NULL REFERENCES solo_sessions(id) ON DELETE CASCADE,
    creature   TEXT NOT NULL,
    count      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS solo_loot (
    session_id INTEGER NOT NULL REFERENCES solo_sessions(id) ON DELETE CASCADE,
    item_key   TEXT NOT NULL,
    count      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_solo_loot ON solo_loot(session_id);
CREATE INDEX IF NOT EXISTS ix_solo_kills ON solo_kills(session_id);
-- Itens e NPCs importados da TibiaWiki BR (artemis/data/tibiawiki.json)
CREATE TABLE IF NOT EXISTS wiki_items (
    item_key     TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    npc_value    INTEGER NOT NULL DEFAULT 0,  -- preço padrão de venda para NPC
    best_price   INTEGER NOT NULL DEFAULT 0,  -- maior preço pago por um NPC (0 = nenhum NPC compra)
    primary_type TEXT
);
CREATE TABLE IF NOT EXISTS wiki_item_buyers (   -- todos os NPCs que compram o item e por quanto
    item_key TEXT NOT NULL,
    npc      TEXT NOT NULL,
    price    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_buyers ON wiki_item_buyers(item_key);
CREATE TABLE IF NOT EXISTS wiki_npcs (
    name     TEXT PRIMARY KEY,
    city     TEXT,
    location TEXT,
    x INTEGER, y INTEGER, z INTEGER
);
-- Preço informado pelos usuários para itens que nenhum NPC compra ("preco_temp").
-- Um valor por código de acesso; o preço do item é a média de todos.
CREATE TABLE IF NOT EXISTS item_user_prices (
    item_key   TEXT NOT NULL,
    access_key TEXT NOT NULL,
    price      INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (item_key, access_key)
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
-- 0.7.0: locais de hunt (TibiaWiki BR + criados pelos usuários)
CREATE TABLE IF NOT EXISTS hunt_places (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    city          TEXT,
    location      TEXT,
    level         INTEGER,          -- level recomendado (wiki)
    x INTEGER, y INTEGER, z INTEGER,
    premium       INTEGER,
    source        TEXT NOT NULL DEFAULT 'wiki',   -- 'wiki' ou 'user'
    created_by    TEXT
);
-- metas de XP/loot por personagem (dia e semana)
CREATE TABLE IF NOT EXISTS goals (
    name_key   TEXT NOT NULL,
    period     TEXT NOT NULL,   -- 'day' | 'week'
    metric     TEXT NOT NULL,   -- 'xp' | 'loot'
    target     INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (name_key, period, metric)
);
-- lista de venda: aviso quando juntar X de um item; "since" = última vez que marcou "vendi"
CREATE TABLE IF NOT EXISTS sell_watch (
    name_key TEXT NOT NULL,
    item_key TEXT NOT NULL,
    target   INTEGER,
    since    TEXT,
    PRIMARY KEY (name_key, item_key)
);
-- 0.10.0: recompensas já concedidas a um código (ex.: +7 dias por 30 dias seguidos enviando dados)
CREATE TABLE IF NOT EXISTS key_rewards (
    key        TEXT NOT NULL REFERENCES access_keys(key) ON DELETE CASCADE,
    reward_id  TEXT NOT NULL,
    days       INTEGER NOT NULL,
    granted_at TEXT NOT NULL,
    PRIMARY KEY (key, reward_id)
);
-- 0.11.0: 👑 Rotação de bosses. Separado das hunts/sessões comuns: só a própria pessoa
-- (e quem estava na PT) vê esses dados.
CREATE TABLE IF NOT EXISTS boss_hunts (       -- lootsplit de bosses (Party Hunt Analyser)
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT UNIQUE NOT NULL,
    started_at    TEXT NOT NULL,
    ended_at      TEXT NOT NULL,
    submitted_by  TEXT,
    uploader_key  TEXT,
    created_at    TEXT NOT NULL,
    report_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS boss_hunt_players (
    hunt_id  INTEGER NOT NULL REFERENCES boss_hunts(id) ON DELETE CASCADE,
    name_key TEXT NOT NULL,
    name     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_boss_hunt_players ON boss_hunt_players(name_key);
CREATE TABLE IF NOT EXISTS boss_sessions (    -- Hunt Session Analyser enviado na Rotação de bosses
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint      TEXT UNIQUE NOT NULL,
    name_key         TEXT NOT NULL,
    name             TEXT NOT NULL,
    mode             TEXT NOT NULL,          -- 'solo' | 'party'
    boss_hunt_id     INTEGER REFERENCES boss_hunts(id) ON DELETE SET NULL,
    started_at       TEXT NOT NULL,
    ended_at         TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    session_label    TEXT,
    raw_xp           INTEGER NOT NULL DEFAULT 0,
    xp               INTEGER NOT NULL DEFAULT 0,
    supplies         INTEGER NOT NULL DEFAULT 0,
    balance          INTEGER NOT NULL DEFAULT 0,
    damage           INTEGER NOT NULL DEFAULT 0,
    damage_h         INTEGER NOT NULL DEFAULT 0,
    healing          INTEGER NOT NULL DEFAULT 0,
    healing_h        INTEGER NOT NULL DEFAULT 0,
    uploader_key     TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_boss_sessions_name ON boss_sessions(name_key, started_at);
CREATE TABLE IF NOT EXISTS boss_kills (
    session_id INTEGER NOT NULL REFERENCES boss_sessions(id) ON DELETE CASCADE,
    creature   TEXT NOT NULL,
    count      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS boss_loot (
    session_id INTEGER NOT NULL REFERENCES boss_sessions(id) ON DELETE CASCADE,
    item_key   TEXT NOT NULL,
    count      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_boss_kills ON boss_kills(session_id);
CREATE INDEX IF NOT EXISTS ix_boss_loot ON boss_loot(session_id);
-- 0.12.0: regras de divisão do lootsplit (quem fica fora / valor fixo) e "já paguei" de cada transferência.
-- kind = 'hunt' (Lootsplit) ou 'boss' (lootsplit da Rotação de bosses).
CREATE TABLE IF NOT EXISTS hunt_rules (
    kind       TEXT NOT NULL,
    hunt_id    INTEGER NOT NULL,
    rules_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (kind, hunt_id)
);
CREATE TABLE IF NOT EXISTS hunt_payments (
    kind         TEXT NOT NULL,
    hunt_id      INTEGER NOT NULL,
    payer_key    TEXT NOT NULL,
    receiver_key TEXT NOT NULL,
    amount       INTEGER NOT NULL,     -- valor marcado; se a divisão mudar, a marcação deixa de valer
    paid_at      TEXT NOT NULL,
    marked_by    TEXT,
    PRIMARY KEY (kind, hunt_id, payer_key, receiver_key)
);
-- 0.12.0: personagens que aceitaram aparecer no 🥇 Ranking entre amigos
CREATE TABLE IF NOT EXISTS ranking_optin (
    name_key  TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    joined_at TEXT NOT NULL
);
-- 0.12.0: imagens da TibiaWiki guardadas no banco (o site busca na wiki só na primeira vez)
CREATE TABLE IF NOT EXISTS wiki_images (
    name         TEXT PRIMARY KEY,
    content_type TEXT,
    data         BLOB,                 -- NULL = não existe na wiki
    fetched_at   TEXT NOT NULL
);
-- 0.10.0: vocação/level dos personagens (TibiaData), para colorir por vocação sem consultar toda hora
CREATE TABLE IF NOT EXISTS char_info (
    name_key   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    vocation   TEXT,
    level      INTEGER,
    updated_at TEXT NOT NULL
);
"""

SOLO_COLUMNS = ("started_at", "ended_at", "duration_seconds", "session_label", "raw_xp", "xp",
                "supplies", "balance", "damage", "damage_h", "healing", "healing_h")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def name_key(name: str) -> str:
    return " ".join(name.split()).lower()


def normalize_key(key: str) -> str:
    return "".join(key.split()).upper()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(access_keys)")}
        if "main_char" not in cols:  # banco criado pela versão 0.2.0
            self._conn.execute("ALTER TABLE access_keys ADD COLUMN main_char TEXT")
        if "trusted" not in cols:  # banco criado antes da 0.4.0
            self._conn.execute("ALTER TABLE access_keys ADD COLUMN trusted INTEGER NOT NULL DEFAULT 0")
        for table in ("hunts", "solo_sessions"):  # 0.5.0: quem enviou (só ele pode apagar)
            if "uploader_key" not in {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN uploader_key TEXT")
        solo_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(solo_sessions)")}
        if "raw_text" not in solo_cols:
            self._conn.execute("ALTER TABLE solo_sessions ADD COLUMN raw_text TEXT")  # 0.6.0: texto original
        if "place_id" not in solo_cols:  # 0.7.0: em qual hunt foi a sessão e level do personagem no envio
            self._conn.execute("ALTER TABLE solo_sessions ADD COLUMN place_id INTEGER REFERENCES hunt_places(id)")
        if "level" not in solo_cols:
            self._conn.execute("ALTER TABLE solo_sessions ADD COLUMN level INTEGER")
        # 0.8.0: tokens de aparelho ficam só como hash (quem copiar o banco não consegue usá-los)
        for (tok,) in self._conn.execute("SELECT token FROM devices WHERE token NOT LIKE 'sha256:%'").fetchall():
            self._conn.execute("UPDATE devices SET token = ? WHERE token = ?", (hash_token(tok), tok))
        self._conn.commit()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ chaves
    def create_key(self, days: int = MAX_KEY_DAYS, label: str = "") -> dict:
        if not 1 <= days <= MAX_KEY_DAYS:
            raise ValueError(f"A validade deve ser de 1 a {MAX_KEY_DAYS} dias.")
        raw = "".join(secrets.choice(_KEY_ALPHABET) for _ in range(8))
        key = f"ART-{raw[:4]}-{raw[4:]}"
        now = utcnow()
        row = {"key": key, "label": label, "created_at": _iso(now), "expires_at": _iso(now + timedelta(days=days))}
        with self._lock:
            self._conn.execute(
                "INSERT INTO access_keys (key, label, created_at, expires_at) VALUES (:key, :label, :created_at, :expires_at)",
                row,
            )
            self._conn.commit()
        return row

    def validate_key(self, key: str) -> dict | None:
        """Chave válida e não expirada -> dados da chave. Expiradas são apagadas na hora."""
        key = normalize_key(key)
        if not key:
            return None
        row = self._conn.execute("SELECT * FROM access_keys WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= _iso(utcnow()):
            self.purge_expired()
            return None
        return dict(row)

    def purge_expired(self) -> int:
        """Apaga chaves vencidas (e, em cascata, personagens/aparelhos ligados) e verificações velhas."""
        now = _iso(utcnow())
        with self._lock:
            cur = self._conn.execute("DELETE FROM access_keys WHERE expires_at <= ?", (now,))
            self._conn.execute("DELETE FROM verifications WHERE expires_at <= ?", (now,))
            self._conn.commit()
            return cur.rowcount

    def renew_key(self, key: str, days: int = MAX_KEY_DAYS) -> dict | None:
        """Nova validade (a partir de agora, máx. 30 dias) mantendo personagens e aparelhos."""
        if not 1 <= days <= MAX_KEY_DAYS:
            raise ValueError(f"A validade deve ser de 1 a {MAX_KEY_DAYS} dias.")
        with self._lock:
            self._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?",
                               (_iso(utcnow() + timedelta(days=days)), normalize_key(key)))
            self._conn.commit()
        return self.validate_key(key)

    def reset_key(self, key: str) -> None:
        """Desvincula o dono: apaga personagens e aparelhos (a pessoa verifica de novo)."""
        key = normalize_key(key)
        with self._lock:
            for table in ("key_chars", "devices", "verifications"):
                self._conn.execute(f"DELETE FROM {table} WHERE key = ?", (key,))
            self._conn.execute("UPDATE access_keys SET main_char = NULL, trusted = 0 WHERE key = ?", (key,))
            self._conn.commit()

    def keys_overview(self) -> list[dict]:
        """Para o painel de administração: chaves com personagens e nº de aparelhos."""
        out = []
        for k in self.list_keys():
            k["trusted"] = bool(k.get("trusted"))
            k["chars"] = self.key_chars(k["key"])
            k["devices"], k["last_seen"] = self._conn.execute("SELECT COUNT(*), MAX(last_seen) FROM devices WHERE key = ?",
                                                              (k["key"],)).fetchone()
            out.append(k)
        return out

    def force_main(self, key: str, name: str) -> bool:
        """Atalho do criador: define o main sem código de verificação e marca como contato de confiança."""
        key = normalize_key(key)
        if self.validate_key(key) is None:
            return False
        now = _iso(utcnow())
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO key_chars VALUES (?, ?, ?, ?)", (key, name_key(name), name, now))
            self._conn.execute("UPDATE access_keys SET main_char = ?, trusted = 1 WHERE key = ?", (name, key))
            self._conn.commit()
        return True

    def set_trusted(self, key: str, trusted: bool) -> None:
        with self._lock:
            self._conn.execute("UPDATE access_keys SET trusted = ? WHERE key = ?", (int(trusted), normalize_key(key)))
            self._conn.commit()

    def issue_device(self, key: str, name: str) -> str:
        token = secrets.token_urlsafe(32)
        now = _iso(utcnow())
        with self._lock:
            self._conn.execute("INSERT INTO devices VALUES (?, ?, ?, ?, ?)", (hash_token(token), key, name, now, now))
            self._conn.commit()
        return token

    # ------------------------------------------------------------------ personagens / aparelhos
    def key_chars(self, key: str) -> list[dict]:
        main = (self._conn.execute("SELECT main_char FROM access_keys WHERE key = ?", (key,)).fetchone() or [None])[0]
        rows = self._conn.execute("SELECT name, verified_at FROM key_chars WHERE key = ? ORDER BY name", (key,)).fetchall()
        return [{"name": r["name"], "verified_at": r["verified_at"], "is_main": name_key(r["name"]) == name_key(main or "")}
                for r in rows]

    def is_linked(self, key: str, name: str) -> bool:
        return self._conn.execute("SELECT 1 FROM key_chars WHERE key = ? AND name_key = ?",
                                  (key, name_key(name))).fetchone() is not None

    def start_verification(self, key: str, name: str, minutes: int = 60) -> dict:
        code = "4RT3MI5-" + "".join(secrets.choice(_KEY_ALPHABET) for _ in range(6))
        now = utcnow()
        row = {"code": code, "key": key, "name": name, "created_at": _iso(now),
               "expires_at": _iso(now + timedelta(minutes=minutes))}
        with self._lock:
            self._conn.execute("DELETE FROM verifications WHERE key = ? AND lower(name) = lower(?)", (key, name))
            self._conn.execute("INSERT INTO verifications VALUES (:code, :key, :name, :created_at, :expires_at)", row)
            self._conn.commit()
        return row

    def get_verification(self, key: str, code: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM verifications WHERE key = ? AND code = ? AND expires_at > ?",
                                 (key, normalize_key(code), _iso(utcnow()))).fetchone()
        return dict(row) if row else None

    def complete_verification(self, key: str, code: str, name: str, device_token: str | None) -> str:
        """Vincula o personagem ao código (o 1º vira main) e devolve o token do aparelho."""
        now = _iso(utcnow())
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO key_chars VALUES (?, ?, ?, ?)", (key, name_key(name), name, now))
            self._conn.execute("UPDATE access_keys SET main_char = ? WHERE key = ? AND main_char IS NULL", (name, key))
            self._conn.execute("DELETE FROM verifications WHERE code = ?", (code,))
            if not device_token:
                device_token = secrets.token_urlsafe(32)
                self._conn.execute("INSERT INTO devices VALUES (?, ?, ?, ?, ?)", (hash_token(device_token), key, name, now, now))
            self._conn.commit()
        return device_token

    def device_valid(self, key: str, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            cur = self._conn.execute("UPDATE devices SET last_seen = ? WHERE token = ? AND key = ?",
                                     (_iso(utcnow()), hash_token(token), key))
            self._conn.commit()
            return cur.rowcount > 0

    def set_main(self, key: str, name: str) -> bool:
        if not self.is_linked(key, name):
            return False
        real = self._conn.execute("SELECT name FROM key_chars WHERE key = ? AND name_key = ?", (key, name_key(name))).fetchone()[0]
        with self._lock:
            self._conn.execute("UPDATE access_keys SET main_char = ? WHERE key = ?", (real, key))
            self._conn.commit()
        return True

    def unlink(self, key: str, name: str) -> bool:
        main = self._conn.execute("SELECT main_char FROM access_keys WHERE key = ?", (key,)).fetchone()[0]
        if name_key(name) == name_key(main or ""):
            return False  # o main não pode ser removido; troque o main antes
        with self._lock:
            cur = self._conn.execute("DELETE FROM key_chars WHERE key = ? AND name_key = ?", (key, name_key(name)))
            self._conn.commit()
            return cur.rowcount > 0

    def list_keys(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM access_keys ORDER BY expires_at")]

    def revoke_key(self, key: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM access_keys WHERE key = ?", (normalize_key(key),))
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ lootsplit
    def _hunt(self, row: sqlite3.Row, kind: str = "hunt") -> dict:
        report = apply_rules(json.loads(row["report_json"]), self.split_rules(kind, row["id"]))
        report.update(id=row["id"], submitted_by=row["submitted_by"], created_at=row["created_at"],
                      uploader_key=row["uploader_key"])
        paid = {(r["payer_key"], r["receiver_key"]): r for r in self._conn.execute(
            "SELECT * FROM hunt_payments WHERE kind = ? AND hunt_id = ?", (kind, row["id"]))}
        for t in report["transfers"]:
            p = paid.get((name_key(t["payer"]), name_key(t["receiver"])))
            t["paid_at"] = p["paid_at"] if p and p["amount"] == t["amount"] else None
        report["pending"] = sum(1 for t in report["transfers"] if not t["paid_at"])
        return report

    # ------------------------------------------------------------------ regras de divisão e "já paguei"
    def split_rules(self, kind: str, hunt_id: int) -> dict | None:
        row = self._conn.execute("SELECT rules_json FROM hunt_rules WHERE kind = ? AND hunt_id = ?", (kind, hunt_id)).fetchone()
        return json.loads(row[0]) if row else None

    def set_split_rules(self, kind: str, hunt_id: int, rules: dict | None, by_key: str) -> None:
        """Novas regras mudam os valores: as marcações de "já paguei" daquela hunt são zeradas."""
        with self._lock:
            self._conn.execute("DELETE FROM hunt_payments WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
            if rules:
                self._conn.execute("INSERT OR REPLACE INTO hunt_rules VALUES (?, ?, ?, ?, ?)",
                                   (kind, hunt_id, json.dumps(rules), _iso(utcnow()), by_key))
            else:
                self._conn.execute("DELETE FROM hunt_rules WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
            self._conn.commit()

    def set_paid(self, kind: str, hunt_id: int, payer: str, receiver: str, amount: int, by_key: str, paid: bool) -> None:
        with self._lock:
            if paid:
                self._conn.execute("INSERT OR REPLACE INTO hunt_payments VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (kind, hunt_id, name_key(payer), name_key(receiver), amount, _iso(utcnow()), by_key))
            else:
                self._conn.execute("DELETE FROM hunt_payments WHERE kind = ? AND hunt_id = ? AND payer_key = ? AND receiver_key = ?",
                                   (kind, hunt_id, name_key(payer), name_key(receiver)))
            self._conn.commit()

    def _forget_split(self, kind: str, hunt_id: int) -> None:
        """Hunt apagada: some com as regras e os pagamentos dela (chamar dentro do _lock)."""
        self._conn.execute("DELETE FROM hunt_payments WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
        self._conn.execute("DELETE FROM hunt_rules WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))

    def hunt(self, hunt_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()
        return self._hunt(row) if row else None

    def add_hunt(self, report: dict, raw_text: str, submitted_by: str, uploader_key: str | None = None) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM hunts WHERE fingerprint = ?", (report["fingerprint"],)).fetchone()
            if existing:
                return self._hunt(existing), False
            cur = self._conn.execute(
                "INSERT INTO hunts (fingerprint, started_at, submitted_by, created_at, raw_text, report_json, uploader_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (report["fingerprint"], report["started_at"], submitted_by, _iso(utcnow()), raw_text, json.dumps(report),
                 uploader_key),
            )
            hunt_id = cur.lastrowid
            self._conn.executemany(
                "INSERT INTO hunt_players (hunt_id, name_key, name) VALUES (?, ?, ?)",
                [(hunt_id, name_key(p["name"]), p["name"]) for p in report["players"]],
            )
            self._conn.commit()
            return self._hunt(self._conn.execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()), True

    def hunts_for_player(self, name: str, limit: int = 500) -> list[dict]:
        rows = self._conn.execute(
            "SELECT h.* FROM hunts h JOIN hunt_players p ON p.hunt_id = h.id "
            "WHERE p.name_key = ? ORDER BY h.started_at DESC, h.id DESC LIMIT ?",
            (name_key(name), limit),
        ).fetchall()
        return [self._hunt(r) for r in rows]

    def delete_hunt(self, hunt_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM hunts WHERE id = ?", (hunt_id,))
            self._forget_split("hunt", hunt_id)
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ stacker
    def uploader_of(self, table: str, row_id: int) -> tuple[bool, str | None]:
        """(existe?, código de acesso de quem enviou)."""
        assert table in ("hunts", "solo_sessions")
        row = self._conn.execute(f"SELECT uploader_key FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return (row is not None, row[0] if row else None)

    def add_solo(self, name: str, fingerprint: str, data: dict, uploader_key: str | None = None,
                 raw_text: str | None = None, place_id: int | None = None, level: int | None = None) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM solo_sessions WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if existing:
                return dict(existing), False
            cols = ", ".join(SOLO_COLUMNS)
            marks = ", ".join("?" for _ in SOLO_COLUMNS)
            cur = self._conn.execute(
                f"INSERT INTO solo_sessions (fingerprint, name_key, name, created_at, uploader_key, raw_text, place_id, level, {cols}) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, {marks})",
                (fingerprint, name_key(name), name, _iso(utcnow()), uploader_key, raw_text, place_id, level,
                 *(data[c] for c in SOLO_COLUMNS)),
            )
            sid = cur.lastrowid
            self._conn.executemany("INSERT INTO solo_kills VALUES (?, ?, ?)", [(sid, c, n) for c, n in data.get("kills", [])])
            self._conn.executemany("INSERT INTO solo_loot VALUES (?, ?, ?)", [(sid, i, n) for i, n in data.get("loot", [])])
            self._conn.commit()
            return dict(self._conn.execute("SELECT * FROM solo_sessions WHERE id = ?", (cur.lastrowid,)).fetchone()), True

    def solo_for_player(self, name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM solo_sessions WHERE name_key = ? ORDER BY started_at DESC, id DESC", (name_key(name),)
        ).fetchall()
        return [dict(r) for r in rows]

    def solo_details(self, session_ids: list[int]) -> tuple[dict, dict]:
        """{session_id: [(criatura, n)]}, {session_id: [(item_key, n)]}"""
        kills: dict[int, list] = {i: [] for i in session_ids}
        loot: dict[int, list] = {i: [] for i in session_ids}
        if session_ids:
            marks = ",".join("?" * len(session_ids))
            for r in self._conn.execute(f"SELECT * FROM solo_kills WHERE session_id IN ({marks}) ORDER BY count DESC", session_ids):
                kills[r["session_id"]].append((r["creature"], r["count"]))
            for r in self._conn.execute(f"SELECT * FROM solo_loot WHERE session_id IN ({marks}) ORDER BY count DESC", session_ids):
                loot[r["session_id"]].append((r["item_key"], r["count"]))
        return kills, loot

    # ------------------------------------------------------------------ itens / preços (TibiaWiki + usuários)
    COINS = {"gold coin": 1, "platinum coin": 100, "crystal coin": 10_000}

    def load_wiki(self, data: dict) -> dict:
        """Substitui a tabela de itens/NPCs pelos dados importados da TibiaWiki."""
        items, buyers = [], []
        for name, npc_value, sellto, ptype in data["items"]:
            key = name.lower().strip()
            prices = [(entry[0], entry[1] if len(entry) > 1 else npc_value) for entry in sellto]
            prices = [(npc, p) for npc, p in prices if p and p > 0]
            best = max((p for _, p in prices), default=0)
            items.append((key, name, npc_value or 0, best, ptype or None))
            buyers += [(key, npc, p) for npc, p in prices]
        def city(c: str) -> str | None:  # NPCs que viajam (Rashid, Yasir...) vêm com resto de HTML no lugar da cidade
            return "Viaja (local muda)" if not c or c.lower() in ("div", "span") else c
        npcs = [(n, city(v[0]), v[1] if v[1] and v[1].lower() not in ("div", "span") else None,
                 *(v[2] or (None, None, None))) for n, v in data["npcs"].items()]
        with self._lock:
            for t in ("wiki_items", "wiki_item_buyers", "wiki_npcs"):
                self._conn.execute(f"DELETE FROM {t}")
            self._conn.executemany("INSERT OR REPLACE INTO wiki_items VALUES (?, ?, ?, ?, ?)", items)
            self._conn.executemany("INSERT INTO wiki_item_buyers VALUES (?, ?, ?)", buyers)
            self._conn.executemany("INSERT OR REPLACE INTO wiki_npcs VALUES (?, ?, ?, ?, ?, ?)", npcs)
            self._conn.execute("INSERT OR REPLACE INTO meta VALUES ('wiki_imported_at', ?)", (data.get("imported_at", ""),))
            self._conn.commit()
        self._wiki_keys = None
        return {"items": len(items), "buyers": len(buyers), "npcs": len(npcs)}

    def wiki_imported_at(self) -> str | None:
        row = self._conn.execute("SELECT v FROM meta WHERE k = 'wiki_imported_at'").fetchone()
        return row[0] if row else None

    def resolve_item(self, key: str) -> str:
        """Acha o item da wiki mesmo no plural ("white mushrooms" -> "white mushroom")."""
        if getattr(self, "_wiki_keys", None) is None:
            self._wiki_keys = {r[0] for r in self._conn.execute("SELECT item_key FROM wiki_items")}
        if key in self._wiki_keys or key in self.COINS:
            return key
        for cand in (key[:-3] + "y" if key.endswith("ies") else None, key[:-2] if key.endswith("es") else None,
                     key[:-1] if key.endswith("s") else None):
            if cand and (cand in self._wiki_keys or cand in self.COINS):
                return cand
        return key

    def price_info(self, keys: list[str], access_key: str) -> dict[str, dict]:
        """Preço de cada item: NPC que paga mais (todos empatados no maior preço) ou média dos usuários."""
        out = {}
        for key in set(keys):
            info = {"key": key, "name": key.title(), "npc_price": 0, "buyers": [], "avg_price": None,
                    "avg_count": 0, "my_price": None, "type": None}
            if key in self.COINS:
                info.update(npc_price=self.COINS[key], source="moeda")
            row = self._conn.execute("SELECT * FROM wiki_items WHERE item_key = ?", (key,)).fetchone()
            if row:
                info.update(name=row["name"], npc_price=info["npc_price"] or row["best_price"], type=row["primary_type"])
                if row["best_price"]:
                    for b in self._conn.execute(
                        "SELECT b.npc, b.price, n.city, n.location, n.x, n.y, n.z FROM wiki_item_buyers b "
                        "LEFT JOIN wiki_npcs n ON n.name = b.npc WHERE b.item_key = ? AND b.price = ? "
                        "ORDER BY (b.npc LIKE 'Hireling%'), b.npc", (key, row["best_price"])
                    ):
                        info["buyers"].append({"npc": b["npc"], "price": b["price"], "city": b["city"],
                                               "location": b["location"],
                                               "coords": [b["x"], b["y"], b["z"]] if b["x"] is not None else None})
            avg = self._conn.execute("SELECT AVG(price), COUNT(*) FROM item_user_prices WHERE item_key = ?", (key,)).fetchone()
            if avg[1]:
                info.update(avg_price=round(avg[0]), avg_count=avg[1])
            mine = self._conn.execute("SELECT price FROM item_user_prices WHERE item_key = ? AND access_key = ?",
                                      (key, access_key)).fetchone()
            info["my_price"] = mine[0] if mine else None
            info.setdefault("source", "npc" if info["npc_price"] else ("media" if info["avg_price"] else None))
            info["unit_price"] = info["npc_price"] or info["avg_price"] or 0
            out[key] = info
        return out

    def set_user_price(self, key: str, access_key: str, price: int | None) -> None:
        with self._lock:
            if price is None or price <= 0:
                self._conn.execute("DELETE FROM item_user_prices WHERE item_key = ? AND access_key = ?", (key, access_key))
            else:
                self._conn.execute("INSERT OR REPLACE INTO item_user_prices VALUES (?, ?, ?, ?)",
                                   (key, access_key, price, _iso(utcnow())))
            self._conn.commit()

    # ------------------------------------------------------------------ hunts (locais)
    def load_places(self, data: dict) -> int:
        """Importa/atualiza os locais de hunt da wiki sem mudar os ids (sessões apontam para eles)."""
        with self._lock:
            for name, city, location, level, coords, premium in data["hunts"]:
                x, y, z = coords or (None, None, None)
                self._conn.execute("INSERT OR IGNORE INTO hunt_places (name, source) VALUES (?, 'wiki')", (name,))
                self._conn.execute(
                    "UPDATE hunt_places SET city=?, location=?, level=?, x=?, y=?, z=?, premium=?, source='wiki' WHERE name=?",
                    (city or None, location or None, level, x, y, z, int(bool(premium)), name))
            self._conn.execute("INSERT OR REPLACE INTO meta VALUES ('hunts_imported_at', ?)", (data.get("imported_at", ""),))
            self._conn.commit()
        return len(data["hunts"])

    def meta(self, k: str) -> str | None:
        row = self._conn.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
        return row[0] if row else None

    def set_meta(self, k: str, v: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, v))
            self._conn.commit()

    # ------------------------------------------------------------------ 🥇 ranking entre amigos (opcional)
    def ranking_join(self, name: str, join: bool) -> None:
        with self._lock:
            if join:
                self._conn.execute("INSERT OR IGNORE INTO ranking_optin VALUES (?, ?, ?)", (name_key(name), name, _iso(utcnow())))
            else:
                self._conn.execute("DELETE FROM ranking_optin WHERE name_key = ?", (name_key(name),))
            self._conn.commit()

    def ranking_member(self, name: str) -> bool:
        return self._conn.execute("SELECT 1 FROM ranking_optin WHERE name_key = ?", (name_key(name),)).fetchone() is not None

    def ranking_rows(self, since: str) -> list[dict]:
        """Totais do Stacker desde `since` de quem aceitou entrar no ranking (inclui quem não caçou: zeros)."""
        rows = self._conn.execute(
            "SELECT r.name, c.vocation, c.level, COUNT(s.id) AS sessions, COALESCE(SUM(s.xp), 0) AS xp, "
            "COALESCE(SUM(s.balance), 0) AS balance, COALESCE(SUM(s.duration_seconds), 0) AS seconds "
            "FROM ranking_optin r LEFT JOIN solo_sessions s ON s.name_key = r.name_key AND s.started_at >= ? "
            "LEFT JOIN char_info c ON c.name_key = r.name_key GROUP BY r.name_key", (since,))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ imagens da TibiaWiki (cache)
    def wiki_image(self, name: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT content_type, data, fetched_at FROM wiki_images WHERE name = ?", (name,)).fetchone()

    def save_wiki_image(self, name: str, content_type: str | None, data: bytes | None) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO wiki_images VALUES (?, ?, ?, ?)",
                               (name, content_type, data, _iso(utcnow())))
            self._conn.commit()

    # ------------------------------------------------------------------ backup
    def backup_to(self, path: Path) -> None:
        """Cópia consistente do banco (API de backup do SQLite), mesmo com o servidor no ar."""
        path.parent.mkdir(parents=True, exist_ok=True)
        dst = sqlite3.connect(path)
        try:
            with self._lock:
                self._conn.backup(dst)
        finally:
            dst.close()

    def places(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT p.id, p.name, p.city, p.level, p.source, COUNT(s.id) AS sessions FROM hunt_places p "
            "LEFT JOIN solo_sessions s ON s.place_id = p.id GROUP BY p.id ORDER BY p.name")
        return [dict(r) for r in rows]

    # Colunas que podem sair para o site. NUNCA incluir created_by (é o código de acesso de quem criou).
    _PLACE_COLS = "id, name, city, location, level, x, y, z, premium, source"

    def place(self, place_id: int) -> dict | None:
        row = self._conn.execute(f"SELECT {self._PLACE_COLS} FROM hunt_places WHERE id = ?", (place_id,)).fetchone()
        return dict(row) if row else None

    def places_created_by(self, key: str) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM hunt_places WHERE created_by = ?", (key,)).fetchone()[0]

    def create_place(self, name: str, city: str | None, created_by: str) -> dict:
        name = " ".join(name.split())
        with self._lock:
            row = self._conn.execute(f"SELECT {self._PLACE_COLS} FROM hunt_places WHERE name = ?", (name,)).fetchone()
            if row is None:
                cur = self._conn.execute("INSERT INTO hunt_places (name, city, source, created_by) VALUES (?, ?, 'user', ?)",
                                         (name, city or None, created_by))
                self._conn.commit()
                row = self._conn.execute(f"SELECT {self._PLACE_COLS} FROM hunt_places WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def set_session_place(self, session_id: int, place_id: int | None) -> None:
        with self._lock:
            self._conn.execute("UPDATE solo_sessions SET place_id = ? WHERE id = ?", (place_id, session_id))
            self._conn.commit()

    def place_stats(self, min_level: int | None = None, max_level: int | None = None,
                    place_ids: list[int] | None = None, name: str | None = None, min_seconds: int = 600) -> list[dict]:
        """XP/h, gold/h (balance), level médio e nº de jogadores por hunt. Ignora sessões com menos de 10 min."""
        where, args = ["s.duration_seconds >= ?"], [min_seconds]
        if min_level is not None:
            where.append("s.level >= ?"); args.append(min_level)
        if max_level is not None:
            where.append("s.level <= ?"); args.append(max_level)
        if place_ids:
            where.append(f"p.id IN ({','.join('?' * len(place_ids))})"); args += place_ids
        if name:
            where.append("s.name_key = ?"); args.append(name_key(name))
        rows = self._conn.execute(
            "SELECT p.id, p.name, p.city, p.level AS wiki_level, COUNT(s.id) AS sessions, COUNT(DISTINCT s.name_key) AS players, "
            "SUM(s.xp) AS xp, SUM(s.balance) AS balance, SUM(s.supplies) AS supplies, SUM(s.duration_seconds) AS seconds, "
            "ROUND(AVG(s.level)) AS avg_level, MIN(s.level) AS min_level, MAX(s.level) AS max_level "
            "FROM solo_sessions s JOIN hunt_places p ON p.id = s.place_id "
            f"WHERE {' AND '.join(where)} GROUP BY p.id", args)
        out = []
        for r in rows:
            d = dict(r)
            hours = d["seconds"] / 3600
            d["xp_per_hour"] = round(d["xp"] / hours) if hours else 0
            d["gold_per_hour"] = round(d["balance"] / hours) if hours else 0
            out.append(d)
        return out

    def place_top(self, place_id: int, limit: int = 5) -> tuple[list, list]:
        kills = self._conn.execute(
            "SELECT k.creature, SUM(k.count) AS n FROM solo_kills k JOIN solo_sessions s ON s.id = k.session_id "
            "WHERE s.place_id = ? GROUP BY k.creature ORDER BY n DESC LIMIT ?", (place_id, limit)).fetchall()
        loot = self._conn.execute(
            "SELECT l.item_key, SUM(l.count) AS n FROM solo_loot l JOIN solo_sessions s ON s.id = l.session_id "
            "WHERE s.place_id = ? GROUP BY l.item_key", (place_id,)).fetchall()
        return [(r[0], r[1]) for r in kills], [(r[0], r[1]) for r in loot]

    # ------------------------------------------------------------------ metas e lista de venda
    def goals(self, name: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT period, metric, target FROM goals WHERE name_key = ?", (name_key(name),))]

    def set_goal(self, name: str, period: str, metric: str, target: int | None) -> None:
        with self._lock:
            if not target:
                self._conn.execute("DELETE FROM goals WHERE name_key=? AND period=? AND metric=?", (name_key(name), period, metric))
            else:
                self._conn.execute("INSERT OR REPLACE INTO goals VALUES (?, ?, ?, ?, ?)",
                                   (name_key(name), period, metric, target, _iso(utcnow())))
            self._conn.commit()

    # ------------------------------------------------------------------ conquistas / recompensas
    def upload_times(self, key: str) -> list[str]:
        """Horários (UTC) em que este código enviou hunts ou sessões que continuam salvas."""
        rows = self._conn.execute(
            "SELECT created_at FROM hunts WHERE uploader_key = ? UNION ALL "
            "SELECT created_at FROM solo_sessions WHERE uploader_key = ? UNION ALL "
            "SELECT created_at FROM boss_hunts WHERE uploader_key = ? UNION ALL "
            "SELECT created_at FROM boss_sessions WHERE uploader_key = ?", (key, key, key, key))
        return [r[0] for r in rows]

    def rewards(self, key: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT reward_id, days, granted_at FROM key_rewards WHERE key = ? ORDER BY granted_at", (key,))]

    def grant_reward(self, key: str, reward_id: str, days: int) -> dict | None:
        """Soma `days` à validade do código, uma única vez por reward_id. Devolve o novo vencimento."""
        with self._lock:
            row = self._conn.execute("SELECT expires_at FROM access_keys WHERE key = ?", (key,)).fetchone()
            if row is None or self._conn.execute("SELECT 1 FROM key_rewards WHERE key = ? AND reward_id = ?",
                                                 (key, reward_id)).fetchone():
                return None
            base = max(datetime.fromisoformat(row[0]), utcnow())
            expires = _iso(base + timedelta(days=days))
            self._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?", (expires, key))
            self._conn.execute("INSERT INTO key_rewards VALUES (?, ?, ?, ?)", (key, reward_id, days, _iso(utcnow())))
            self._conn.commit()
        return {"reward_id": reward_id, "days": days, "expires_at": expires}

    def sold_count(self, name: str) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM sell_watch WHERE name_key = ? AND since IS NOT NULL",
                                  (name_key(name),)).fetchone()[0]

    def save_char_info(self, name: str, vocation: str | None, level: int | None) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO char_info VALUES (?, ?, ?, ?, ?)",
                               (name_key(name), name, vocation, level, _iso(utcnow())))
            self._conn.commit()

    def char_infos(self, names: list[str], max_age_days: int = 3) -> dict[str, dict]:
        """{name_key: {name, vocation, level}} dos que estão no cache e não são velhos demais."""
        keys = [name_key(n) for n in names]
        if not keys:
            return {}
        fresh = _iso(utcnow() - timedelta(days=max_age_days))
        marks = ",".join("?" * len(keys))
        rows = self._conn.execute(f"SELECT * FROM char_info WHERE name_key IN ({marks}) AND updated_at >= ?", (*keys, fresh))
        return {r["name_key"]: {"name": r["name"], "vocation": r["vocation"], "level": r["level"]} for r in rows}

    def sell_watch(self, name: str) -> dict[str, dict]:
        return {r["item_key"]: dict(r) for r in self._conn.execute("SELECT * FROM sell_watch WHERE name_key = ?", (name_key(name),))}

    def set_sell(self, name: str, item: str, target: int | None = None, sold_at: str | None = None,
                 update_target: bool = True) -> None:
        cur = self.sell_watch(name).get(item, {})
        target = target if update_target else cur.get("target")
        since = sold_at or cur.get("since")
        with self._lock:
            if target is None and since is None:
                self._conn.execute("DELETE FROM sell_watch WHERE name_key=? AND item_key=?", (name_key(name), item))
            else:
                self._conn.execute("INSERT OR REPLACE INTO sell_watch VALUES (?, ?, ?, ?)", (name_key(name), item, target, since))
            self._conn.commit()

    def delete_solo(self, session_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM solo_sessions WHERE id = ?", (session_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ 👑 rotação de bosses
    def add_boss_session(self, name: str, fingerprint: str, data: dict, mode: str, uploader_key: str) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM boss_sessions WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if existing:
                return dict(existing), False
            cols = ", ".join(SOLO_COLUMNS)
            marks = ", ".join("?" for _ in SOLO_COLUMNS)
            cur = self._conn.execute(
                f"INSERT INTO boss_sessions (fingerprint, name_key, name, mode, uploader_key, created_at, {cols}) "
                f"VALUES (?, ?, ?, ?, ?, ?, {marks})",
                (fingerprint, name_key(name), name, mode, uploader_key, _iso(utcnow()), *(data[c] for c in SOLO_COLUMNS)))
            sid = cur.lastrowid
            self._conn.executemany("INSERT INTO boss_kills VALUES (?, ?, ?)", [(sid, c, n) for c, n in data.get("kills", [])])
            self._conn.executemany("INSERT INTO boss_loot VALUES (?, ?, ?)", [(sid, i, n) for i, n in data.get("loot", [])])
            self._conn.commit()
            return dict(self._conn.execute("SELECT * FROM boss_sessions WHERE id = ?", (sid,)).fetchone()), True

    def boss_session(self, session_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM boss_sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def boss_sessions_for(self, name: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM boss_sessions WHERE name_key = ? ORDER BY started_at DESC, id DESC", (name_key(name),))]

    def boss_sessions_of_hunt(self, hunt_id: int) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT id, name, mode, started_at, duration_seconds FROM boss_sessions WHERE boss_hunt_id = ? ORDER BY name",
            (hunt_id,))]

    def boss_details(self, session_ids: list[int]) -> tuple[dict, dict]:
        """{session_id: [(criatura, n)]}, {session_id: [(item_key, n)]} das sessões de boss."""
        kills: dict[int, list] = {i: [] for i in session_ids}
        loot: dict[int, list] = {i: [] for i in session_ids}
        if session_ids:
            marks = ",".join("?" * len(session_ids))
            for r in self._conn.execute(f"SELECT * FROM boss_kills WHERE session_id IN ({marks}) ORDER BY count DESC", session_ids):
                kills[r["session_id"]].append((r["creature"], r["count"]))
            for r in self._conn.execute(f"SELECT * FROM boss_loot WHERE session_id IN ({marks}) ORDER BY count DESC", session_ids):
                loot[r["session_id"]].append((r["item_key"], r["count"]))
        return kills, loot

    def link_boss_session(self, session_id: int, hunt_id: int | None) -> None:
        with self._lock:
            self._conn.execute("UPDATE boss_sessions SET boss_hunt_id = ? WHERE id = ?", (hunt_id, session_id))
            self._conn.commit()

    def _boss_hunt(self, row: sqlite3.Row) -> dict:
        return self._hunt(row, "boss")

    def add_boss_hunt(self, report: dict, submitted_by: str, uploader_key: str) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM boss_hunts WHERE fingerprint = ?", (report["fingerprint"],)).fetchone()
            if existing:
                return self._boss_hunt(existing), False
            cur = self._conn.execute(
                "INSERT INTO boss_hunts (fingerprint, started_at, ended_at, submitted_by, uploader_key, created_at, report_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (report["fingerprint"], report["started_at"], report["ended_at"], submitted_by, uploader_key,
                 _iso(utcnow()), json.dumps(report)))
            hid = cur.lastrowid
            self._conn.executemany("INSERT INTO boss_hunt_players VALUES (?, ?, ?)",
                                   [(hid, name_key(p["name"]), p["name"]) for p in report["players"]])
            self._conn.commit()
            return self._boss_hunt(self._conn.execute("SELECT * FROM boss_hunts WHERE id = ?", (hid,)).fetchone()), True

    def boss_hunt(self, hunt_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM boss_hunts WHERE id = ?", (hunt_id,)).fetchone()
        return self._boss_hunt(row) if row else None

    def boss_hunts_for(self, name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT h.* FROM boss_hunts h JOIN boss_hunt_players p ON p.hunt_id = h.id "
            "WHERE p.name_key = ? ORDER BY h.started_at DESC, h.id DESC", (name_key(name),)).fetchall()
        return [self._boss_hunt(r) for r in rows]

    def unlinked_boss_sessions(self, names: list[str]) -> list[dict]:
        """Sessões de boss ainda sem lootsplit destes personagens (para vincular a uma party)."""
        keys = [name_key(n) for n in names]
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        return [dict(r) for r in self._conn.execute(
            f"SELECT id, name_key, started_at, ended_at FROM boss_sessions WHERE boss_hunt_id IS NULL AND name_key IN ({marks})", keys)]

    def boss_uploader(self, table: str, row_id: int) -> tuple[bool, str | None]:
        assert table in ("boss_hunts", "boss_sessions")
        row = self._conn.execute(f"SELECT uploader_key FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return (row is not None, row[0] if row else None)

    def delete_boss(self, table: str, row_id: int) -> bool:
        assert table in ("boss_hunts", "boss_sessions")
        with self._lock:
            if table == "boss_hunts":  # as sessões continuam, só perdem o vínculo com a party
                self._conn.execute("UPDATE boss_sessions SET boss_hunt_id = NULL WHERE boss_hunt_id = ?", (row_id,))
                self._forget_split("boss", row_id)
            cur = self._conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
            self._conn.commit()
            return cur.rowcount > 0
