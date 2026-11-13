"""Banco de dados SQLite (abre no DB Browser for SQLite: data/artemis.db)."""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_KEY_DAYS = 30
_KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I para não confundir

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_keys (
    key         TEXT PRIMARY KEY,
    label       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    main_char   TEXT            -- definido na primeira verificação; prende o código ao dono
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
            self._conn.execute("UPDATE access_keys SET main_char = NULL WHERE key = ?", (key,))
            self._conn.commit()

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
                self._conn.execute("INSERT INTO devices VALUES (?, ?, ?, ?, ?)", (device_token, key, name, now, now))
            self._conn.commit()
        return device_token

    def device_valid(self, key: str, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            cur = self._conn.execute("UPDATE devices SET last_seen = ? WHERE token = ? AND key = ?",
                                     (_iso(utcnow()), token, key))
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
    @staticmethod
    def _hunt(row: sqlite3.Row) -> dict:
        report = json.loads(row["report_json"])
        report.update(id=row["id"], submitted_by=row["submitted_by"], created_at=row["created_at"])
        return report

    def add_hunt(self, report: dict, raw_text: str, submitted_by: str) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM hunts WHERE fingerprint = ?", (report["fingerprint"],)).fetchone()
            if existing:
                return self._hunt(existing), False
            cur = self._conn.execute(
                "INSERT INTO hunts (fingerprint, started_at, submitted_by, created_at, raw_text, report_json) VALUES (?, ?, ?, ?, ?, ?)",
                (report["fingerprint"], report["started_at"], submitted_by, _iso(utcnow()), raw_text, json.dumps(report)),
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
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ stacker
    def add_solo(self, name: str, fingerprint: str, data: dict) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM solo_sessions WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if existing:
                return dict(existing), False
            cols = ", ".join(SOLO_COLUMNS)
            marks = ", ".join("?" for _ in SOLO_COLUMNS)
            cur = self._conn.execute(
                f"INSERT INTO solo_sessions (fingerprint, name_key, name, created_at, {cols}) VALUES (?, ?, ?, ?, {marks})",
                (fingerprint, name_key(name), name, _iso(utcnow()), *(data[c] for c in SOLO_COLUMNS)),
            )
            self._conn.commit()
            return dict(self._conn.execute("SELECT * FROM solo_sessions WHERE id = ?", (cur.lastrowid,)).fetchone()), True

    def solo_for_player(self, name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM solo_sessions WHERE name_key = ? ORDER BY started_at DESC, id DESC", (name_key(name),)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_solo(self, session_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM solo_sessions WHERE id = ?", (session_id,))
            self._conn.commit()
            return cur.rowcount > 0
