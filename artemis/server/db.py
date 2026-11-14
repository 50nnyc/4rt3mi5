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
        if "raw_text" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(solo_sessions)")}:
            self._conn.execute("ALTER TABLE solo_sessions ADD COLUMN raw_text TEXT")  # 0.6.0: texto original
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
            k["devices"] = self._conn.execute("SELECT COUNT(*) FROM devices WHERE key = ?", (k["key"],)).fetchone()[0]
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
            self._conn.execute("INSERT INTO devices VALUES (?, ?, ?, ?, ?)", (token, key, name, now, now))
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
        report.update(id=row["id"], submitted_by=row["submitted_by"], created_at=row["created_at"],
                      uploader_key=row["uploader_key"])
        return report

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
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ stacker
    def uploader_of(self, table: str, row_id: int) -> tuple[bool, str | None]:
        """(existe?, código de acesso de quem enviou)."""
        assert table in ("hunts", "solo_sessions")
        row = self._conn.execute(f"SELECT uploader_key FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return (row is not None, row[0] if row else None)

    def add_solo(self, name: str, fingerprint: str, data: dict, uploader_key: str | None = None,
                 raw_text: str | None = None) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM solo_sessions WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if existing:
                return dict(existing), False
            cols = ", ".join(SOLO_COLUMNS)
            marks = ", ".join("?" for _ in SOLO_COLUMNS)
            cur = self._conn.execute(
                f"INSERT INTO solo_sessions (fingerprint, name_key, name, created_at, uploader_key, raw_text, {cols}) "
                f"VALUES (?, ?, ?, ?, ?, ?, {marks})",
                (fingerprint, name_key(name), name, _iso(utcnow()), uploader_key, raw_text, *(data[c] for c in SOLO_COLUMNS)),
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

    def delete_solo(self, session_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM solo_sessions WHERE id = ?", (session_id,))
            self._conn.commit()
            return cur.rowcount > 0
