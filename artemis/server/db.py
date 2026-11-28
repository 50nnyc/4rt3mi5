"""Banco de dados SQLite (abre no DB Browser for SQLite: data/artemis.db)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from artemis.core.report import apply_rules

_PH = PasswordHasher()  # Argon2id com os parâmetros recomendados pela biblioteca (RFC 9106)
# hash de mentira só para gastar o mesmo tempo quando a conta não existe (não corresponde a senha nenhuma)
_DUMMY_HASH = "argon2p$" + _PH.hash(secrets.token_hex(16))

MAX_KEY_DAYS = 30

BASE_PLAYER_TYPES = ("hardcore", "comum", "novato")
_TYPE_RE = re.compile(r"[a-z][a-z_]{2,19}")


def extra_player_types() -> tuple[str, ...]:
    """Tipos de player extras, ligados no .env (ARTEMIS_EXTRA_PLAYER_TYPES)."""
    raw = os.environ.get("ARTEMIS_EXTRA_PLAYER_TYPES", "")
    return tuple(t for t in (x.strip() for x in raw.split(",")) if _TYPE_RE.fullmatch(t) and t not in BASE_PLAYER_TYPES)


def hash_token(token: str) -> str:
    """Hash do token de aparelho: o banco guarda só isto, nunca o token."""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()
_KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I para não confundir

SCHEMA = """
-- 0.16.0: contas com senha (login antes da chave). Uma chave por conta.
CREATE TABLE IF NOT EXISTS accounts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL,
    username_key   TEXT UNIQUE NOT NULL,
    pw_hash        TEXT NOT NULL,          -- pbkdf2_sha256$iterações$sal$hash (a senha nunca é guardada)
    created_at     TEXT NOT NULL,
    access_key     TEXT UNIQUE REFERENCES access_keys(key) ON DELETE SET NULL,
    store_claimed  INTEGER NOT NULL DEFAULT 0,   -- já gerou a chave grátis na loja (só uma vez por conta)
    last_login     TEXT
);
CREATE TABLE IF NOT EXISTS account_sessions (
    token       TEXT PRIMARY KEY,           -- só o hash
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
-- 0.17.0: código de uso único (gerado pelo adm) para a pessoa criar uma nova senha. Só o hash fica guardado.
CREATE TABLE IF NOT EXISTS password_resets (
    code_hash   TEXT PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL
);
-- 0.17.0: períodos em que a chave ficou vencida: a sequência de dias fica congelada (não zera) nesses dias
CREATE TABLE IF NOT EXISTS key_pauses (
    key       TEXT NOT NULL REFERENCES access_keys(key) ON DELETE CASCADE,
    start_at  TEXT NOT NULL,
    end_at    TEXT NOT NULL
);
-- 0.16.0: pedidos de recuperação do código (o adm chama no WhatsApp)
CREATE TABLE IF NOT EXISTS recovery_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    username    TEXT NOT NULL,
    whatsapp    TEXT NOT NULL,
    character   TEXT,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    done_at     TEXT
);
-- 0.13.0: entradas no app/site por código (só o painel do criador vê)
CREATE TABLE IF NOT EXISTS key_logins (
    key     TEXT NOT NULL,
    at      TEXT NOT NULL,
    client  TEXT NOT NULL DEFAULT 'site'
);
CREATE INDEX IF NOT EXISTS idx_key_logins ON key_logins(key, at);
-- 0.13.0: uso das telas, só contadores por dia (sem dizer quem)
CREATE TABLE IF NOT EXISTS screen_stats (
    day      TEXT NOT NULL,
    page     TEXT NOT NULL,
    views    INTEGER NOT NULL DEFAULT 0,
    actions  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, page)
);
-- 0.13.0: chaves grátis geradas na loja (IP só como hash, para limitar 1 por dia)
CREATE TABLE IF NOT EXISTS store_claims (
    ip_hash  TEXT NOT NULL,
    at       TEXT NOT NULL
);
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
CREATE TABLE IF NOT EXISTS boss_sessions (    -- Hunt Analyser enviado na Rotação de bosses
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
-- 0.29.0: link público de um lootsplit (quem tem o endereço vê o resultado, sem conta; expira e pode ser revogado)
CREATE TABLE IF NOT EXISTS split_links (
    token       TEXT PRIMARY KEY,
    hunt_id     INTEGER NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'hunt'   -- 0.33.2: 'hunt' (hunts) ou 'boss' (boss_hunts); cada tabela numera do 1
);
-- 0.12.0: personagens que aceitaram aparecer no 🥇 Ranking entre amigos
CREATE TABLE IF NOT EXISTS ranking_optin (
    name_key  TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    joined_at TEXT NOT NULL
);
-- 0.25.0: personagem já verificado (vale 30 dias) ou verificado à mão (manual = 1, vale sempre)
CREATE TABLE IF NOT EXISTS char_trust (
    name_key    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    manual      INTEGER NOT NULL DEFAULT 0
);
-- 0.25.0: XP total do personagem por dia (o TibiaData não tem histórico; guardamos um ponto por dia)
CREATE TABLE IF NOT EXISTS xp_snapshots (
    name_key TEXT NOT NULL,
    day      TEXT NOT NULL,
    xp       INTEGER NOT NULL,
    PRIMARY KEY (name_key, day)
);
-- 0.26.0: último valor conhecido de cada personagem acompanhado (cadastrados e citados em party session)
CREATE TABLE IF NOT EXISTS rank_players (
    name_key      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    world         TEXT,
    level         INTEGER,
    vocation      TEXT,
    values_json   TEXT NOT NULL,
    world_changes INTEGER NOT NULL DEFAULT 0,
    updated_day   TEXT NOT NULL
);
-- 0.26.0: o que mudou em relação ao dia anterior (subiu/desceu) e trocas de mundo
CREATE TABLE IF NOT EXISTS rank_changes (
    day        TEXT NOT NULL,
    name_key   TEXT NOT NULL,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    old_value  INTEGER,
    new_value  INTEGER,
    delta      INTEGER,
    kind       TEXT NOT NULL,          -- up | down | world
    world_from TEXT,
    world_to   TEXT,
    PRIMARY KEY (day, name_key, category)
);
CREATE INDEX IF NOT EXISTS ix_rank_changes_name ON rank_changes(name_key, day);
-- 0.26.0: tempo de cada varredura (a primeira carga e as atualizações seguintes) para o painel de admin
CREATE TABLE IF NOT EXISTS scan_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    seconds       REAL NOT NULL,
    first_load    INTEGER NOT NULL,
    requests      INTEGER NOT NULL,
    errors        INTEGER NOT NULL,
    worlds        INTEGER NOT NULL,
    tracked       INTEGER NOT NULL,
    matched       INTEGER NOT NULL,
    changes       INTEGER NOT NULL,
    world_changes INTEGER NOT NULL,
    ok            INTEGER NOT NULL,
    note          TEXT NOT NULL DEFAULT ''
);
-- 0.27.0: VIP List. Quem adiciona (dono) escolhe o nick; o que ele PEDE ver fica em requested (csv).
-- O que a outra pessoa ACEITA compartilhar fica em approved: NULL = ainda sem resposta, '' = recusou/revogou.
CREATE TABLE IF NOT EXISTS vip_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_key   TEXT NOT NULL,
    owner_char  TEXT,
    target_nk   TEXT NOT NULL,
    target_name TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    requested   TEXT NOT NULL DEFAULT '',
    approved    TEXT,
    answered_at TEXT,
    UNIQUE (owner_key, target_nk)
);
-- 0.26.1: ranking geral (top 1000 por métrica, de todos os mundos), guardado a cada varredura
CREATE TABLE IF NOT EXISTS rank_top (
    metric     TEXT NOT NULL,
    pos        INTEGER NOT NULL,
    name       TEXT NOT NULL,
    world      TEXT,
    level      INTEGER,
    vocation   TEXT,
    value      INTEGER,
    day        TEXT NOT NULL,
    PRIMARY KEY (metric, pos)
);
-- 0.30.0: top de cada mundo por métrica (filtro por mundo na aba Geral)
CREATE TABLE IF NOT EXISTS rank_world_top (
    metric     TEXT NOT NULL,
    world      TEXT NOT NULL,
    pos        INTEGER NOT NULL,
    value      INTEGER,
    name       TEXT NOT NULL,
    level      INTEGER,
    vocation   TEXT,
    day        TEXT NOT NULL,
    PRIMARY KEY (metric, world, pos)
);
-- 0.25.0: ranking pessoal de cada conta (só ela vê): amigos, metas, rivais
CREATE TABLE IF NOT EXISTS custom_ranking (
    owner_key TEXT NOT NULL,
    name_key  TEXT NOT NULL,
    name      TEXT NOT NULL,
    added_at  TEXT NOT NULL,
    PRIMARY KEY (owner_key, name_key)
);
-- 0.12.0: imagens da TibiaWiki guardadas no banco (o site busca na wiki só na primeira vez)
CREATE TABLE IF NOT EXISTS wiki_images (
    name         TEXT PRIMARY KEY,
    content_type TEXT,
    data         BLOB,                 -- NULL = não existe na wiki
    fetched_at   TEXT NOT NULL
);
-- 0.20.0: tipo de player da conta (hardcore / comum / novato): decide o que o app pergunta e o que ela compartilha
CREATE TABLE IF NOT EXISTS player_prefs (
    key         TEXT PRIMARY KEY,
    player_type TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
-- 0.20.0: Input Analyser (dano recebido). kind = 'solo' (sessão do Stacker) ou 'hunt' (lootsplit).
-- Um por personagem em cada sessão/lootsplit; depois de salvo não muda.
CREATE TABLE IF NOT EXISTS damage_inputs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    ref_id       INTEGER NOT NULL,
    name_key     TEXT NOT NULL,
    name         TEXT NOT NULL,
    data_json    TEXT NOT NULL,
    uploader_key TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (kind, ref_id, name_key)
);
CREATE INDEX IF NOT EXISTS ix_damage_inputs ON damage_inputs(kind, ref_id);
-- 0.20.0: Hunt Analyser que cada membro da PT junta ao lootsplit
CREATE TABLE IF NOT EXISTS party_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hunt_id      INTEGER NOT NULL REFERENCES hunts(id) ON DELETE CASCADE,
    name_key     TEXT NOT NULL,
    name         TEXT NOT NULL,
    data_json    TEXT NOT NULL,
    uploader_key TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (hunt_id, name_key)
);
-- 0.10.0: vocação/level dos personagens (TibiaData), para colorir por vocação sem consultar toda hora
CREATE TABLE IF NOT EXISTS char_info (
    name_key   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    vocation   TEXT,
    level      INTEGER,
    updated_at TEXT NOT NULL
);
-- 0.21.0: mensagens da tela "Contato com o administrador" (também vão por e-mail, se configurado)
CREATE TABLE IF NOT EXISTS contact_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    email       TEXT NOT NULL,
    subject     TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL,
    lang        TEXT NOT NULL DEFAULT 'pt-BR',
    robot       INTEGER NOT NULL DEFAULT 0,   -- preencheu o campo escondido: não é enviado a ninguém
    sent        INTEGER NOT NULL DEFAULT 0,   -- 1 = e-mail entregue ao servidor de e-mail
    read_at     TEXT
);
-- 0.21.0: visitas ao site, só contadores (relatório mensal para a CipSoft). Nada identifica quem visitou.
CREATE TABLE IF NOT EXISTS site_visits (
    day       TEXT PRIMARY KEY,
    views     INTEGER NOT NULL DEFAULT 0,
    visitors  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS site_visitors_month (
    month     TEXT PRIMARY KEY,
    visitors  INTEGER NOT NULL DEFAULT 0
);
-- marcas embaralhadas do período atual (dia e mês) para contar visitante único; apagadas quando o período acaba
CREATE TABLE IF NOT EXISTS visit_seen (
    period  TEXT NOT NULL,
    mark    TEXT NOT NULL,
    PRIMARY KEY (period, mark)
);
-- 0.22.0: notícias do Tibia (Latest News / News Archive). Guardadas para ler e pesquisar mesmo com a fonte fora do ar.
CREATE TABLE IF NOT EXISTS tibia_news (
    id            INTEGER PRIMARY KEY,           -- mesmo id do tibia.com
    date          TEXT NOT NULL,
    title         TEXT NOT NULL,
    category      TEXT NOT NULL,                 -- cipsoft, community, development, support, technical
    type          TEXT NOT NULL,                 -- news, ticker, article
    content_html  TEXT,                          -- já limpo; NULL = ainda não baixado
    content_text  TEXT,
    fetched_at    TEXT,
    listed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tibia_news_date ON tibia_news(date);
-- 0.22.1: calendário de eventos do Tibia colado pelo administrador. Cada colagem fica guardada (histórico nosso);
-- o app mostra só a mais nova de cada mês, já convertida em dados.
CREATE TABLE IF NOT EXISTS tibia_calendar (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    month       TEXT NOT NULL,                 -- AAAA-MM
    data_json   TEXT NOT NULL,
    raw_html    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tibia_calendar_month ON tibia_calendar(month, id);
-- 0.22.2: traduções automáticas (notícias, News Archive e calendário). Chave = hash do texto original + idioma.
CREATE TABLE IF NOT EXISTS translations (
    src_hash    TEXT NOT NULL,
    lang        TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (src_hash, lang)
);
-- 0.23.0: 🤝 Substituições. Link de envio: alguém (sem conta ou com conta) envia os analyzers pelo dono do
-- personagem. O link só ENVIA; não lê nada. O token fica só como hash. "operator" = personagem de quem vai
-- jogar (opcional): com ele, quem joga também envia logado na própria conta (jogador autorizado).
CREATE TABLE IF NOT EXISTS upload_links (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash    TEXT UNIQUE NOT NULL,
    owner_key     TEXT NOT NULL REFERENCES access_keys(key) ON DELETE CASCADE,
    name_key      TEXT NOT NULL,
    name          TEXT NOT NULL,
    operator      TEXT,
    operator_key  TEXT,                -- name_key do operator
    scopes        TEXT NOT NULL,       -- "solo,party,boss"
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    max_uses      INTEGER NOT NULL,
    uses          INTEGER NOT NULL DEFAULT 0,
    revoked_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_upload_links_owner ON upload_links(owner_key);
CREATE INDEX IF NOT EXISTS ix_upload_links_operator ON upload_links(operator_key);
-- 0.23.0: marcações por jogador num lootsplit (kind = 'hunt' ou 'boss').
-- tag 'other' = jogado por outra pessoa (played_by opcional); 'sub' = substituto; 'nosub' = não é substituto.
CREATE TABLE IF NOT EXISTS hunt_tags (
    kind        TEXT NOT NULL,
    hunt_id     INTEGER NOT NULL,
    name_key    TEXT NOT NULL,
    tag         TEXT NOT NULL,
    played_by   TEXT,
    set_by      TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (kind, hunt_id, name_key, tag)
);
-- 0.23.0: alguém tentou vincular um personagem que já está em outra conta (aviso ao dono)
CREATE TABLE IF NOT EXISTS char_claims (
    name_key  TEXT NOT NULL,
    at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_char_claims ON char_claims(name_key, at);
-- 0.23.0: 🗃️ Cofre da rotação de bosses. Drops que ficam para vender/usar depois (inclusive os que caíram para outro
-- membro: o analyser de quem envia não anota). ref = 'hunt' (lootsplit de bosses) ou 'session' (sessão de boss solo).
-- A divisão é sempre entre quem estava no dia do drop, mesmo que a venda seja meses depois.
CREATE TABLE IF NOT EXISTS vault_drops (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_kind     TEXT NOT NULL,
    ref_id       INTEGER NOT NULL,
    item         TEXT NOT NULL,
    qty          INTEGER NOT NULL DEFAULT 1,
    dropped_by   TEXT NOT NULL,              -- quem dropou / guarda o item (personagem da rotação)
    price_each   INTEGER,                    -- preço estimado (só quem registrou muda)
    status       TEXT NOT NULL DEFAULT 'stock',   -- stock | sold | used
    sold_total   INTEGER,
    market_fee   INTEGER NOT NULL DEFAULT 0, -- 1 = vendeu no Market (desconta a taxa)
    sold_at      TEXT,
    craft_id     INTEGER,
    owner_key    TEXT NOT NULL,              -- quem registrou (só ele altera)
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vault_drops ON vault_drops(ref_kind, ref_id);
-- conjunto usado (ex.: 5 Crypt Runes -> 1 arma Crypt). Runas que faltaram e foram compradas entram como custo.
CREATE TABLE IF NOT EXISTS vault_crafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_kind     TEXT NOT NULL,
    ref_id       INTEGER NOT NULL,
    set_key      TEXT NOT NULL,
    bought_json  TEXT NOT NULL,              -- [{"item", "cost"}]
    result       TEXT,
    seller       TEXT NOT NULL,              -- quem ficou com o item e vende
    sold_total   INTEGER,
    market_fee   INTEGER NOT NULL DEFAULT 0,
    sold_at      TEXT,
    owner_key    TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vault_crafts ON vault_crafts(ref_kind, ref_id);
-- 0.24.0: 👥 parties registradas (titulares + substitutos) para hunt, bosses ou os dois
CREATE TABLE IF NOT EXISTS parties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,                 -- hunt | boss | both
    rotation    TEXT,                          -- ex.: 'graveborn' (liga o craft das armas Crypt)
    owner_key   TEXT NOT NULL,                 -- quem criou (só ele muda a formação)
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS party_members (
    party_id  INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    name_key  TEXT NOT NULL,
    name      TEXT NOT NULL,
    role      TEXT NOT NULL,                   -- main | sub
    PRIMARY KEY (party_id, name_key)
);
CREATE INDEX IF NOT EXISTS ix_party_members_name ON party_members(name_key);
-- 🗃️ cofre da party: quanto cada item está valendo (editável a qualquer momento por qualquer membro)
CREATE TABLE IF NOT EXISTS party_prices (
    party_id    INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    item_key    TEXT NOT NULL,
    item        TEXT NOT NULL,
    price       INTEGER NOT NULL,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT,
    PRIMARY KEY (party_id, item_key)
);
CREATE TABLE IF NOT EXISTS party_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    party_id     INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    item         TEXT NOT NULL,
    qty          INTEGER NOT NULL DEFAULT 1,
    origin       TEXT NOT NULL,                -- drop | service | buy (a "sacolinha")
    cost_each    INTEGER,                      -- compra: quanto pagou; service: metade do valor da runa (pago ao serviçado)
    client       TEXT,                         -- service: o serviçado (recebe a metade, dividida entre os titulares)
    holder       TEXT NOT NULL,                -- quem guarda (na compra: quem pagou)
    obtained_on  TEXT NOT NULL,
    note         TEXT,
    status       TEXT NOT NULL DEFAULT 'stock', -- stock | sold | used
    sold_total   INTEGER,
    market_fee   INTEGER NOT NULL DEFAULT 0,
    sold_at      TEXT,
    seller       TEXT,
    craft_id     INTEGER,
    ref_price    INTEGER,                      -- preço do cofre no momento do craft (referência)
    owner_key    TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_party_items ON party_items(party_id);
CREATE TABLE IF NOT EXISTS party_crafts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    party_id    INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    set_key     TEXT NOT NULL,
    result      TEXT,
    holder      TEXT NOT NULL,                 -- quem ficou com o item craftado
    min_value   INTEGER NOT NULL,              -- faixa de preço no momento do craft
    max_value   INTEGER NOT NULL,
    cost        INTEGER NOT NULL DEFAULT 0,    -- compras usadas (reembolsadas na venda)
    sold_total  INTEGER,
    market_fee  INTEGER NOT NULL DEFAULT 0,
    sold_at     TEXT,
    owner_key   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_party_crafts ON party_crafts(party_id);
"""

# 0.23.0: colunas de "quem jogou" nas sessões e lootsplits
#   via          NULL = o próprio dono enviou; 'link' = link de envio; 'operator' = jogador autorizado
#   other_player 1 = jogado por outra pessoa (não entra nos rankings e comparações de desempenho)
#   played_by    personagem de quem jogou (opcional)
#   content_hash a sessão sem o nome do personagem (a mesma sessão não fica salva em dois personagens)
SUB_COLUMNS = {
    "solo_sessions": (("via", "TEXT"), ("other_player", "INTEGER NOT NULL DEFAULT 0"), ("played_by", "TEXT"),
                      ("content_hash", "TEXT")),
    "boss_sessions": (("via", "TEXT"), ("other_player", "INTEGER NOT NULL DEFAULT 0"), ("played_by", "TEXT"),
                      ("content_hash", "TEXT")),
    "party_sessions": (("via", "TEXT"), ("other_player", "INTEGER NOT NULL DEFAULT 0"), ("played_by", "TEXT")),
    "hunts": (("via", "TEXT"),),
    "boss_hunts": (("via", "TEXT"),),
}


def session_content_hash(data: dict) -> str | None:
    """Impressão digital da sessão SEM o nome do personagem. Sessões vazias/curtas não contam (podem coincidir)."""
    if int(data.get("duration_seconds") or 0) < 60 or not any(data.get(k) for k in ("raw_xp", "xp", "balance", "damage")):
        return None
    parts = [str(data.get(k)) for k in ("started_at", "ended_at", "raw_xp", "xp", "supplies", "balance", "damage", "healing")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()

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


class _Result:
    """Resultado já lido de uma consulta (o cursor não fica aberto fora da fila)."""
    __slots__ = ("_rows", "lastrowid", "rowcount")

    def __init__(self, rows: list, lastrowid, rowcount: int):
        self._rows, self.lastrowid, self.rowcount = rows, lastrowid, rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _SerialConn:
    """Conexão SQLite usada por várias requisições ao mesmo tempo: cada comando espera a sua vez.
    Sem isso, duas consultas simultâneas na mesma conexão dão "bad parameter or other API misuse"."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock):
        self._c, self._lock = conn, lock

    def execute(self, sql: str, params=()) -> _Result:
        with self._lock:
            cur = self._c.execute(sql, params)
            return _Result(cur.fetchall(), cur.lastrowid, cur.rowcount)

    def executemany(self, sql: str, seq) -> _Result:
        with self._lock:
            cur = self._c.executemany(sql, seq)
            return _Result([], cur.lastrowid, cur.rowcount)

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._c.executescript(sql)

    def commit(self) -> None:
        with self._lock:
            self._c.commit()

    def __getattr__(self, name):  # backup, close… (quem chama segura o _lock)
        return getattr(self._c, name)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(path, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        # 0.20.0: o mesmo lock (reentrante) serve para os blocos "with self._lock" e para cada comando
        self._lock = threading.RLock()
        self._conn = _SerialConn(raw, self._lock)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(access_keys)")}
        if "main_char" not in cols:  # banco criado pela versão 0.2.0
            self._conn.execute("ALTER TABLE access_keys ADD COLUMN main_char TEXT")
        if "trusted" not in cols:  # banco criado antes da 0.4.0
            self._conn.execute("ALTER TABLE access_keys ADD COLUMN trusted INTEGER NOT NULL DEFAULT 0")
        if "lifetime" not in cols:  # 0.13.0: "amigo do adm" (código que nunca vence)
            self._conn.execute("ALTER TABLE access_keys ADD COLUMN lifetime INTEGER NOT NULL DEFAULT 0")
        if "readonly" not in cols:  # 0.22.3: conta de visitante (vê tudo, não envia nem altera nada)
            self._conn.execute("ALTER TABLE access_keys ADD COLUMN readonly INTEGER NOT NULL DEFAULT 0")
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
        if "place_edits" not in solo_cols:  # 0.20.0: quantas vezes o local já foi trocado (máximo 2)
            self._conn.execute("ALTER TABLE solo_sessions ADD COLUMN place_edits INTEGER NOT NULL DEFAULT 0")
        hunt_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(hunts)")}
        if "place_id" not in hunt_cols:  # 0.20.0: em qual hunt foi o lootsplit
            self._conn.execute("ALTER TABLE hunts ADD COLUMN place_id INTEGER REFERENCES hunt_places(id)")
        if "place_edits" not in hunt_cols:
            self._conn.execute("ALTER TABLE hunts ADD COLUMN place_edits INTEGER NOT NULL DEFAULT 0")
        for table, new_cols in SUB_COLUMNS.items():  # 0.23.0: quem jogou / sessão sem o nome do personagem
            have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            for col, decl in new_cols:
                if col not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        if "client" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(party_items)")}:  # 0.24.0
            self._conn.execute("ALTER TABLE party_items ADD COLUMN client TEXT")
        if "dropped_on" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(vault_drops)")}:
            self._conn.execute("ALTER TABLE vault_drops ADD COLUMN dropped_on TEXT")  # dia do drop (identifica o item)
        if "kind" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(split_links)")}:  # 0.33.2
            self._conn.execute("ALTER TABLE split_links ADD COLUMN kind TEXT NOT NULL DEFAULT 'hunt'")
        if "live" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(solo_sessions)")}:  # 0.32.0: sessão ao vivo
            self._conn.execute("ALTER TABLE solo_sessions ADD COLUMN live INTEGER NOT NULL DEFAULT 0")
            self._conn.execute("ALTER TABLE solo_sessions ADD COLUMN live_touched_at TEXT")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS live_points (
            session_id INTEGER NOT NULL REFERENCES solo_sessions(id) ON DELETE CASCADE,
            ended_at TEXT NOT NULL, sent_at TEXT NOT NULL, duration_seconds INTEGER NOT NULL DEFAULT 0,
            xp INTEGER NOT NULL DEFAULT 0, raw_xp INTEGER NOT NULL DEFAULT 0, balance INTEGER NOT NULL DEFAULT 0,
            supplies INTEGER NOT NULL DEFAULT 0, damage INTEGER NOT NULL DEFAULT 0, healing INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (session_id, ended_at))""")
        # 0.32.2: efeito de fábrica do item (elementos) e valor da Tibia Coin de cada personagem
        self._conn.execute("""CREATE TABLE IF NOT EXISTS char_prefs (
            name_key TEXT PRIMARY KEY, tc_gold INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)""")
        self._conn.executescript("""
        -- 0.32.0: imbuements e gastos invisíveis (Player Hardcore)
        CREATE TABLE IF NOT EXISTS gear_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name_key TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
            slots INTEGER NOT NULL DEFAULT 2, native TEXT NOT NULL DEFAULT '[]', catalog TEXT, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_gear_items_nk ON gear_items(name_key);
        CREATE TABLE IF NOT EXISTS gear_charges (
            id INTEGER PRIMARY KEY AUTOINCREMENT, gear_id INTEGER NOT NULL REFERENCES gear_items(id) ON DELETE CASCADE,
            imbuement TEXT NOT NULL, tier INTEGER NOT NULL DEFAULT 0, plan_json TEXT NOT NULL DEFAULT '{}',
            total_cost INTEGER NOT NULL DEFAULT 0, hours_total REAL NOT NULL DEFAULT 20, hours_used REAL NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL, ended_at TEXT);
        CREATE TABLE IF NOT EXISTS gear_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name_key TEXT NOT NULL, name TEXT NOT NULL,
            place_id INTEGER REFERENCES hunt_places(id) ON DELETE SET NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS gear_set_items (
            set_id INTEGER NOT NULL REFERENCES gear_sets(id) ON DELETE CASCADE,
            gear_id INTEGER NOT NULL REFERENCES gear_items(id) ON DELETE CASCADE, PRIMARY KEY (set_id, gear_id));
        CREATE TABLE IF NOT EXISTS gear_place_pref (
            name_key TEXT NOT NULL, place_id INTEGER NOT NULL REFERENCES hunt_places(id) ON DELETE CASCADE,
            set_id INTEGER NOT NULL REFERENCES gear_sets(id) ON DELETE CASCADE, confirmed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL, PRIMARY KEY (name_key, place_id));
        CREATE TABLE IF NOT EXISTS session_gear (
            kind TEXT NOT NULL, ref_id INTEGER NOT NULL, name_key TEXT NOT NULL,
            set_id INTEGER REFERENCES gear_sets(id) ON DELETE SET NULL, set_name TEXT, pause_minutes INTEGER NOT NULL DEFAULT 0,
            hours REAL NOT NULL DEFAULT 0, cost INTEGER NOT NULL DEFAULT 0, assigned_at TEXT NOT NULL,
            PRIMARY KEY (kind, ref_id, name_key));
        CREATE TABLE IF NOT EXISTS gear_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name_key TEXT NOT NULL, kind TEXT NOT NULL, ref_id INTEGER NOT NULL,
            charge_id INTEGER REFERENCES gear_charges(id) ON DELETE SET NULL, label TEXT NOT NULL,
            hours REAL NOT NULL, cost INTEGER NOT NULL, day TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_gear_usage_ref ON gear_usage(name_key, kind, ref_id);
        CREATE TABLE IF NOT EXISTS imb_prices (
            key TEXT NOT NULL, item TEXT NOT NULL, price INTEGER NOT NULL, world TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY (key, item));
        """)
        # 0.32.2: horas acumuladas de cada equipamento por tipo de imbuement (só cresce; nunca volta a zero)
        fresh = self._conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'gear_lifetime'").fetchone() is None
        self._conn.execute("""CREATE TABLE IF NOT EXISTS gear_lifetime (
            gear_id INTEGER NOT NULL REFERENCES gear_items(id) ON DELETE CASCADE, imbuement TEXT NOT NULL,
            hours REAL NOT NULL DEFAULT 0, PRIMARY KEY (gear_id, imbuement))""")
        if fresh:  # quem já usava: soma o que cada imbuement (inclusive os refeitos) já tinha contado
            self._conn.execute("INSERT INTO gear_lifetime SELECT gear_id, imbuement, SUM(hours_used) FROM gear_charges "
                               "GROUP BY gear_id, imbuement HAVING SUM(hours_used) > 0")
        if "elements" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(gear_items)")}:  # 0.32.2
            self._conn.execute("ALTER TABLE gear_items ADD COLUMN elements TEXT NOT NULL DEFAULT '[]'")
        if "auto" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(session_gear)")}:  # 0.32.2
            self._conn.execute("ALTER TABLE session_gear ADD COLUMN auto INTEGER NOT NULL DEFAULT 0")
        for table in ("solo_sessions", "boss_sessions"):
            self._conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_content ON {table}(content_hash)")
            todo = self._conn.execute(f"SELECT * FROM {table} WHERE content_hash IS NULL").fetchall()
            for r in todo:  # sessões antigas ganham a impressão digital (uma vez só)
                h = session_content_hash(dict(r))
                self._conn.execute(f"UPDATE {table} SET content_hash = ? WHERE id = ?", (h or "", r["id"]))
        # 0.20.0: a chave de acesso não vence mais (todas passam a ser vitalícias)
        self._conn.execute("UPDATE access_keys SET lifetime = 1 WHERE lifetime = 0")
        # 0.8.0: tokens de aparelho ficam só como hash (quem copiar o banco não consegue usá-los)
        for (tok,) in self._conn.execute("SELECT token FROM devices WHERE token NOT LIKE 'sha256:%'").fetchall():
            self._conn.execute("UPDATE devices SET token = ? WHERE token = ?", (hash_token(tok), tok))
        self._conn.commit()

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
                # 0.20.0: toda chave nasce sem vencimento
                "INSERT INTO access_keys (key, label, created_at, expires_at, lifetime) VALUES (:key, :label, :created_at, :expires_at, 1)",
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
        if row["expires_at"] <= _iso(utcnow()) and not row["lifetime"]:
            self.purge_expired()
            return None
        return dict(row)

    def get_key(self, key: str) -> dict | None:
        """A chave como está no banco, mesmo vencida (para renovar)."""
        row = self._conn.execute("SELECT * FROM access_keys WHERE key = ?", (normalize_key(key),)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def is_expired(k: dict) -> bool:
        return not k.get("lifetime") and k["expires_at"] <= _iso(utcnow())

    def _note_pause(self, key: str) -> None:
        """Chave vencida voltando a valer: guarda o período parado (a sequência de dias fica congelada nele).
        Chamar com o lock já pego, ANTES de mudar o vencimento."""
        row = self._conn.execute("SELECT expires_at, lifetime FROM access_keys WHERE key = ?", (key,)).fetchone()
        now = _iso(utcnow())
        if row and row["expires_at"] <= now:
            self._conn.execute("INSERT INTO key_pauses VALUES (?, ?, ?)", (key, row["expires_at"], now))

    def pause_days(self, key: str) -> set:
        """Dias (de Brasília) em que a chave esteve vencida."""
        from artemis.core.achievements import local_day
        out = set()
        for r in self._conn.execute("SELECT start_at, end_at FROM key_pauses WHERE key = ?", (normalize_key(key or ""),)):
            d, end = local_day(r["start_at"]), local_day(r["end_at"])
            while d <= end:
                out.add(d)
                d += timedelta(days=1)
        return out

    def renew_account_key(self, key: str) -> bool:
        """0.17.0: renovação grátis pela conta, também para chave já vencida (volta a valer 7 dias a partir de agora).
        Só quando faltam menos de 3 dias (ou já venceu). Nunca tira dias."""
        key = normalize_key(key)
        now = utcnow()
        with self._lock:
            self._note_pause(key)
            cur = self._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ? AND expires_at < ? AND lifetime = 0",
                                     (_iso(now + timedelta(days=self.FREE_RENEW_DAYS)), key,
                                      _iso(now + timedelta(days=self.RENEW_WINDOW_DAYS))))
            self._conn.commit()
        return cur.rowcount > 0

    def purge_expired(self) -> int:
        """Apaga chaves vencidas (e, em cascata, personagens/aparelhos ligados) e verificações velhas.
        Códigos vitalícios ("amigo do adm") nunca são apagados. 0.17.0: chave ligada a uma conta também não é
        apagada ao vencer: a pessoa só perde o acesso até renovar."""
        now = _iso(utcnow())
        with self._lock:
            cur = self._conn.execute("DELETE FROM access_keys WHERE expires_at <= ? AND lifetime = 0 AND key NOT IN "
                                     "(SELECT access_key FROM accounts WHERE access_key IS NOT NULL)", (now,))
            self._conn.execute("DELETE FROM verifications WHERE expires_at <= ?", (now,))
            self._conn.commit()
            return cur.rowcount

    def renew_key(self, key: str, days: int = MAX_KEY_DAYS) -> dict | None:
        """Nova validade (a partir de agora, máx. 30 dias) mantendo personagens e aparelhos."""
        if not 1 <= days <= MAX_KEY_DAYS:
            raise ValueError(f"A validade deve ser de 1 a {MAX_KEY_DAYS} dias.")
        with self._lock:
            self._note_pause(normalize_key(key))
            self._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?",
                               (_iso(utcnow() + timedelta(days=days)), normalize_key(key)))
            self._conn.commit()
        return self.validate_key(key)

    def renew_all(self, days: int = MAX_KEY_DAYS) -> int:
        """Leva para `days` a partir de agora só as chaves válidas que têm MENOS que isso.
        Quem já tem mais dias (e os vitalícios) não muda. Devolve quantas foram renovadas."""
        if not 1 <= days <= MAX_KEY_DAYS:
            raise ValueError(f"A validade deve ser de 1 a {MAX_KEY_DAYS} dias.")
        now = utcnow()
        new = _iso(now + timedelta(days=days))
        with self._lock:
            cur = self._conn.execute("UPDATE access_keys SET expires_at = ? WHERE expires_at > ? AND expires_at < ? AND lifetime = 0",
                                     (new, _iso(now), new))
            self._conn.commit()
            return cur.rowcount

    FREE_RENEW_DAYS = 7
    RENEW_WINDOW_DAYS = 3   # 0.15.0: a renovação grátis só abre quando faltam menos de 3 dias

    def renew_free(self, key: str) -> tuple[bool, dict | None]:
        """Renovação grátis pelo próprio usuário: volta a valer 7 dias a partir de agora, só quando faltam menos de 3 dias
        e a chave já tem personagem verificado. Nunca tira dias. Devolve (renovou?, chave)."""
        key = normalize_key(key)
        now = utcnow()
        new = _iso(now + timedelta(days=self.FREE_RENEW_DAYS))
        window = _iso(now + timedelta(days=self.RENEW_WINDOW_DAYS))
        with self._lock:
            cur = self._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ? AND expires_at < ? AND lifetime = 0 "
                                     "AND main_char IS NOT NULL", (new, key, window))
            self._conn.commit()
        return cur.rowcount > 0, self.validate_key(key)

    def set_lifetime(self, key: str, on: bool) -> dict | None:
        """Liga/desliga o código vitalício. Ao desligar um código já vencido, ele ganha 7 dias (não some na hora)."""
        key = normalize_key(key)
        on = True  # 0.20.0: nenhuma chave volta a ter vencimento
        with self._lock:
            if on:  # se estava vencida, os dias parados ficam congelados na sequência
                self._note_pause(key)
                self._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ? AND expires_at <= ?",
                                   (_iso(utcnow()), key, _iso(utcnow())))
            self._conn.execute("UPDATE access_keys SET lifetime = ? WHERE key = ?", (int(on), key))
            if not on:
                self._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ? AND expires_at <= ?",
                                   (_iso(utcnow() + timedelta(days=7)), key, _iso(utcnow())))
            self._conn.commit()
        return self.validate_key(key)

    # ------------------------------------------------------------------ 0.13.0: atividade (painel do criador)
    LOGIN_GAP = timedelta(minutes=30)   # aberturas seguidas dentro disso contam como 1 entrada
    KEEP_ACTIVITY = timedelta(days=180)

    def log_login(self, key: str, client: str) -> bool:
        now = utcnow()
        with self._lock:
            last = self._conn.execute("SELECT MAX(at) FROM key_logins WHERE key = ?", (key,)).fetchone()[0]
            if last and datetime.fromisoformat(last) > now - self.LOGIN_GAP:
                return False
            self._conn.execute("INSERT INTO key_logins VALUES (?, ?, ?)", (key, _iso(now), client))
            self._conn.execute("DELETE FROM key_logins WHERE at < ?", (_iso(now - self.KEEP_ACTIVITY),))
            self._conn.commit()
        return True

    def logins(self, key: str, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT at, client FROM key_logins WHERE key = ? ORDER BY at DESC LIMIT ?", (normalize_key(key), limit))]

    def track_screen(self, page: str, action: bool, day: str) -> None:
        col = "actions" if action else "views"
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO screen_stats (day, page) VALUES (?, ?)", (day, page))
            self._conn.execute(f"UPDATE screen_stats SET {col} = {col} + 1 WHERE day = ? AND page = ?", (day, page))
            self._conn.commit()

    # ---------------------------------------------------------------- 0.21.0: visitas ao site
    def visit_salt(self) -> str:
        """Segredo fixo do servidor para embaralhar a marca do visitante (a marca some no fim do dia/mês)."""
        with self._lock:
            salt = self.meta("visit_salt")
            if not salt:
                salt = secrets.token_hex(32)
                self.set_meta("visit_salt", salt)
            return salt

    def count_visit(self, day: str, day_mark: str, month_mark: str) -> None:
        """Uma página aberta. Visitante novo no dia/mês só soma se a marca ainda não apareceu no período."""
        month = day[:7]
        with self._lock:
            c = self._conn
            c.execute("INSERT OR IGNORE INTO site_visits (day) VALUES (?)", (day,))
            new_day = c.execute("INSERT OR IGNORE INTO visit_seen VALUES (?, ?)", ("d:" + day, day_mark)).rowcount == 1
            c.execute("UPDATE site_visits SET views = views + 1, visitors = visitors + ? WHERE day = ?", (int(new_day), day))
            c.execute("INSERT OR IGNORE INTO site_visitors_month (month) VALUES (?)", (month,))
            if c.execute("INSERT OR IGNORE INTO visit_seen VALUES (?, ?)", ("m:" + month, month_mark)).rowcount == 1:
                c.execute("UPDATE site_visitors_month SET visitors = visitors + 1 WHERE month = ?", (month,))
            # período encerrado: as marcas vão embora, só os totais ficam
            c.execute("DELETE FROM visit_seen WHERE period LIKE 'd:%' AND period <> ?", ("d:" + day,))
            c.execute("DELETE FROM visit_seen WHERE period LIKE 'm:%' AND period <> ?", ("m:" + month,))
            c.commit()

    def month_report(self, month: str) -> dict:
        """Números do mês (AAAA-MM) para o relatório de visitas."""
        like = month + "%"
        c = self._conn
        one = lambda sql, *p: (c.execute(sql, p).fetchone() or [0])[0] or 0  # noqa: E731  (mês sem nenhuma linha ainda)
        days = [dict(r) for r in c.execute("SELECT day, views, visitors FROM site_visits WHERE day LIKE ? ORDER BY day", (like,))]
        logins = {r["client"]: r["n"] for r in c.execute(
            "SELECT client, COUNT(DISTINCT key) AS n FROM key_logins WHERE at LIKE ? GROUP BY client", (like,))}
        return {
            "month": month,
            "page_views": sum(d["views"] for d in days),
            "unique_visitors": one("SELECT visitors FROM site_visitors_month WHERE month = ?", month),
            "busiest_day": max(days, key=lambda d: d["views"], default=None),
            "days": days,
            "new_accounts": one("SELECT COUNT(*) FROM accounts WHERE created_at LIKE ?", like),
            "active_users": one("SELECT COUNT(DISTINCT key) FROM key_logins WHERE at LIKE ?", like),
            "active_by_client": logins,
            "screen_views": one("SELECT SUM(views) FROM screen_stats WHERE day LIKE ?", like),
            "lootsplits": one("SELECT COUNT(*) FROM hunts WHERE created_at LIKE ?", like)
                          + one("SELECT COUNT(*) FROM boss_hunts WHERE created_at LIKE ?", like),
            "sessions": one("SELECT COUNT(*) FROM solo_sessions WHERE created_at LIKE ?", like)
                        + one("SELECT COUNT(*) FROM boss_sessions WHERE created_at LIKE ?", like),
            "contacts": one("SELECT COUNT(*) FROM contact_messages WHERE robot = 0 AND created_at LIKE ?", like),
        }

    # ---------------------------------------------------------------- 0.21.0: contato com o administrador
    def add_contact(self, email: str, subject: str, message: str, lang: str, robot: bool) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO contact_messages (created_at, email, subject, message, lang, robot) VALUES (?, ?, ?, ?, ?, ?)",
                (_iso(utcnow()), email, subject, message, lang, int(robot)))
            # robôs: guarda só os 200 mais recentes, para o painel mostrar quantos foram barrados
            self._conn.execute("DELETE FROM contact_messages WHERE robot = 1 AND id NOT IN "
                               "(SELECT id FROM contact_messages WHERE robot = 1 ORDER BY id DESC LIMIT 200)")
            self._conn.commit()
            return cur.lastrowid

    def mark_contact(self, contact_id: int, sent: bool | None = None, read: bool | None = None) -> bool:
        with self._lock:
            n = 0
            if sent is not None:
                n = self._conn.execute("UPDATE contact_messages SET sent = ? WHERE id = ?", (int(sent), contact_id)).rowcount
            if read is not None:
                n = self._conn.execute("UPDATE contact_messages SET read_at = ? WHERE id = ?",
                                       (_iso(utcnow()) if read else None, contact_id)).rowcount
            self._conn.commit()
            return n > 0

    def contacts(self, limit: int = 100) -> dict:
        rows = [dict(r) for r in self._conn.execute(
            "SELECT id, created_at, email, subject, message, lang, sent, read_at FROM contact_messages "
            "WHERE robot = 0 ORDER BY id DESC LIMIT ?", (limit,))]
        robots = self._conn.execute("SELECT COUNT(*) FROM contact_messages WHERE robot = 1").fetchone()[0]
        return {"messages": rows, "robots": robots,
                "unread": self._conn.execute("SELECT COUNT(*) FROM contact_messages WHERE robot = 0 AND read_at IS NULL").fetchone()[0]}

    def contacts_since(self, since: datetime) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM contact_messages WHERE robot = 0 AND created_at >= ?",
                                  (_iso(since),)).fetchone()[0]

    def screen_report(self, since_day: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT page, SUM(views) AS views, SUM(actions) AS actions FROM screen_stats WHERE day >= ? "
            "GROUP BY page ORDER BY views DESC", (since_day,))]

    def store_claims_since(self, since: datetime, ip_hash: str | None = None) -> int:
        if ip_hash:
            return self._conn.execute("SELECT COUNT(*) FROM store_claims WHERE at >= ? AND ip_hash = ?",
                                      (_iso(since), ip_hash)).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM store_claims WHERE at >= ?", (_iso(since),)).fetchone()[0]

    def add_store_claim(self, ip_hash: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO store_claims VALUES (?, ?)", (ip_hash, _iso(utcnow())))
            self._conn.execute("DELETE FROM store_claims WHERE at < ?", (_iso(utcnow() - timedelta(days=30)),))
            self._conn.commit()

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
            k["lifetime"] = bool(k.get("lifetime"))
            k["chars"] = self.key_chars(k["key"])
            acc = self.account_for_key(k["key"])
            k["account"] = acc["username"] if acc else None
            k["logins_7d"], k["last_login"] = self._conn.execute(
                "SELECT COUNT(*), (SELECT MAX(at) FROM key_logins WHERE key = ?) FROM key_logins WHERE key = ? AND at >= ?",
                (k["key"], k["key"], _iso(utcnow() - timedelta(days=7)))).fetchone()
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
        coin = self.coin_map([r["name"] for r in rows])  # 0.32.2: valor da Tibia Coin em gold (0 = não informado)
        return [{"name": r["name"], "verified_at": r["verified_at"], "is_main": name_key(r["name"]) == name_key(main or ""),
                 "tc_gold": coin.get(name_key(r["name"]), 0)} for r in rows]

    # ------------------------------------------------------------------ 0.16.0: contas (login com senha)
    PW_ITERATIONS = 200_000   # só para conferir hashes antigos (0.16.0); os novos são Argon2id
    SESSION_DAYS = 90   # sessão de conta parada por mais que isso pede a senha de novo
    pepper: str | None = None  # 0.17.0: segredo fora do banco (server.json ou ARTEMIS_PW_PEPPER)

    @staticmethod
    def _hash_pw(password: str, salt: str, iterations: int) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()

    def _peppered(self, password: str) -> str:
        """HMAC-SHA256 da senha com o pepper. Sem o pepper (que não está no banco), o hash guardado não serve para nada."""
        if not self.pepper:
            raise RuntimeError("pepper das senhas não configurado")
        return hmac.new(bytes.fromhex(self.pepper), password.encode(), hashlib.sha256).hexdigest()

    def _new_pw_hash(self, password: str) -> str:
        # 0.17.0: Argon2id (resistente a placa de vídeo) sobre o HMAC com pepper. Ninguém, nem o adm, recupera a senha.
        return "argon2p$" + _PH.hash(self._peppered(password))

    def _pw_ok(self, stored: str, password: str) -> bool:
        if stored.startswith("argon2p$"):
            try:
                return _PH.verify(stored[len("argon2p$"):], self._peppered(password))
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False
        _, iterations, salt, digest = stored.split("$")  # pbkdf2 da 0.16.0 (trocado no próximo login certo)
        return secrets.compare_digest(self._hash_pw(password, salt, int(iterations)), digest)

    def set_password(self, account_id: int, password: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE accounts SET pw_hash = ? WHERE id = ?", (self._new_pw_hash(password), account_id))
            self._conn.execute("DELETE FROM account_sessions WHERE account_id = ?", (account_id,))  # sai de todo lugar
            self._conn.commit()

    def create_account(self, username: str, password: str) -> dict | None:
        """Nova conta; None se o nome já existe (sem diferenciar maiúsculas)."""
        pw = self._new_pw_hash(password)
        with self._lock:
            try:
                cur = self._conn.execute("INSERT INTO accounts (username, username_key, pw_hash, created_at) VALUES (?, ?, ?, ?)",
                                         (username, username.lower(), pw, _iso(utcnow())))
            except sqlite3.IntegrityError:
                return None
            self._conn.commit()
        return self.account(cur.lastrowid)

    def account(self, account_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None

    def check_password(self, username: str, password: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE username_key = ?", (username.lower(),)).fetchone()
        if row is None:
            self._pw_ok(_DUMMY_HASH, password)  # mesmo tempo de resposta com ou sem conta
            return None
        if not self._pw_ok(row["pw_hash"], password):
            return None
        if not row["pw_hash"].startswith("argon2p$") or _PH.check_needs_rehash(row["pw_hash"][len("argon2p$"):]):
            with self._lock:  # hash antigo/fraco: troca pelo atual agora que a senha foi conferida
                self._conn.execute("UPDATE accounts SET pw_hash = ? WHERE id = ?", (self._new_pw_hash(password), row["id"]))
                self._conn.commit()
        return dict(row)

    def new_account_session(self, account_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = _iso(utcnow())
        with self._lock:
            self._conn.execute("INSERT INTO account_sessions VALUES (?, ?, ?, ?)", (hash_token(token), account_id, now, now))
            self._conn.execute("UPDATE accounts SET last_login = ? WHERE id = ?", (now, account_id))
            self._conn.execute("DELETE FROM account_sessions WHERE last_seen < ?",
                               (_iso(utcnow() - timedelta(days=self.SESSION_DAYS)),))
            self._conn.commit()
        return token

    def account_by_token(self, token: str) -> dict | None:
        if not token:
            return None
        h = hash_token(token)
        row = self._conn.execute(
            "SELECT a.* FROM account_sessions s JOIN accounts a ON a.id = s.account_id WHERE s.token = ? AND s.last_seen >= ?",
            (h, _iso(utcnow() - timedelta(days=self.SESSION_DAYS)))).fetchone()
        if row is None:
            return None
        with self._lock:
            self._conn.execute("UPDATE account_sessions SET last_seen = ? WHERE token = ?", (_iso(utcnow()), h))
            self._conn.commit()
        return dict(row)

    def end_account_session(self, token: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM account_sessions WHERE token = ?", (hash_token(token or ""),))
            self._conn.commit()

    def account_for_key(self, key: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE access_key = ?", (normalize_key(key),)).fetchone()
        return dict(row) if row else None

    def link_account_key(self, account_id: int, key: str, store_claim: bool = False) -> bool:
        """Liga a chave à conta. False se a conta já tem outra chave válida ou a chave já é de outra conta."""
        key = normalize_key(key)
        acc = self.account(account_id)
        other = self.account_for_key(key)
        if acc is None or (other and other["id"] != account_id):
            return False
        if acc["access_key"] and acc["access_key"] != key and self.validate_key(acc["access_key"]):
            return False
        with self._lock:
            self._conn.execute("UPDATE accounts SET access_key = ?, store_claimed = store_claimed OR ? WHERE id = ?",
                               (key, int(store_claim), account_id))
            self._conn.commit()
        return True

    # ------------------------------------------------------------------ 0.22.3: conta de visitante (só visualização)
    GUEST_LABEL = "Visitante (só visualização)"

    def setup_guest(self, username: str, password: str, main_char: str, player_type: str = "hardcore") -> dict:
        """Cria (ou atualiza a senha de) uma conta de visitante: a chave dela é só de leitura e não vence.
        O personagem serve só para abrir as telas; ele NÃO entra em key_chars, então continua sendo de quem o
        verificou, e o visitante não vê nada que seja só do dono. Recusa conta de outra pessoa com o mesmo nome."""
        acc = self.account_by_name(username)
        if acc is not None:
            k = self.get_key(acc["access_key"]) if acc["access_key"] else None
            if k is not None and not k.get("readonly"):
                raise ValueError(f"A conta {acc['username']} já existe e é de um jogador. Escolha outro nome.")
        else:
            acc = self.create_account(username, password)
        self.set_password(acc["id"], password)  # também encerra as sessões abertas dessa conta
        key = acc["access_key"] if acc["access_key"] and self.get_key(acc["access_key"]) else None
        now = _iso(utcnow())
        with self._lock:
            if key is None:
                key = self.create_key(1, self.GUEST_LABEL)["key"]
                self._conn.execute("UPDATE accounts SET access_key = ?, store_claimed = 1 WHERE id = ?", (key, acc["id"]))
            self._conn.execute("UPDATE access_keys SET readonly = 1, lifetime = 1, trusted = 1, main_char = ?, label = ? "
                               "WHERE key = ?", (main_char, self.GUEST_LABEL, key))
            self._conn.execute("INSERT OR REPLACE INTO player_prefs VALUES (?, ?, ?)", (key, player_type, now))
            self._conn.commit()
        return {"username": acc["username"], "key": key, "main_char": main_char}

    def key_readonly(self, key: str) -> bool:
        row = self._conn.execute("SELECT readonly FROM access_keys WHERE key = ?", (normalize_key(key or ""),)).fetchone()
        return bool(row and row[0])

    def account_token_readonly(self, token: str) -> bool:
        """A sessão de conta é de um visitante (sem atualizar o "visto por último")."""
        if not token:
            return False
        row = self._conn.execute(
            "SELECT k.readonly FROM account_sessions s JOIN accounts a ON a.id = s.account_id "
            "JOIN access_keys k ON k.key = a.access_key WHERE s.token = ?", (hash_token(token),)).fetchone()
        return bool(row and row[0])

    def add_recovery(self, account: dict | None, whatsapp: str, reason: str, character: str | None,
                     username: str = "") -> int:
        """account None = pedido de quem não consegue entrar (esqueceu conta/senha); username é o que a pessoa lembra."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO recovery_requests (account_id, username, whatsapp, character, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (account["id"] if account else None, account["username"] if account else username, whatsapp, character,
                 reason, _iso(utcnow())))
            self._conn.commit()
        return cur.lastrowid

    def count_open_recoveries(self, reason: str) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM recovery_requests WHERE done_at IS NULL AND reason = ?",
                                  (reason,)).fetchone()[0]

    def account_by_name(self, username: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE username_key = ?", ((username or "").lower(),)).fetchone()
        return dict(row) if row else None

    RESET_HOURS = 24

    def new_reset_code(self, account_id: int) -> str:
        """Código de uso único para criar nova senha (o adm manda pelo WhatsApp). Substitui o anterior."""
        raw = "".join(secrets.choice(_KEY_ALPHABET) for _ in range(10))
        code = f"SENHA-{raw[:5]}-{raw[5:]}"
        with self._lock:
            self._conn.execute("DELETE FROM password_resets WHERE account_id = ? OR expires_at < ?", (account_id, _iso(utcnow())))
            self._conn.execute("INSERT INTO password_resets VALUES (?, ?, ?)",
                               (hash_token(code), account_id, _iso(utcnow() + timedelta(hours=self.RESET_HOURS))))
            self._conn.commit()
        return code

    def use_reset_code(self, username: str, code: str, new_password: str) -> dict | None:
        """Confere conta + código; se certo, troca a senha (sai de todos os aparelhos) e apaga o código."""
        acc = self.account_by_name(username)
        code = normalize_key(code)
        if acc is None or not code:
            return None
        row = self._conn.execute("SELECT 1 FROM password_resets WHERE code_hash = ? AND account_id = ? AND expires_at > ?",
                                 (hash_token(code), acc["id"], _iso(utcnow()))).fetchone()
        if row is None:
            return None
        with self._lock:
            self._conn.execute("DELETE FROM password_resets WHERE account_id = ?", (acc["id"],))
            self._conn.commit()
        self.set_password(acc["id"], new_password)
        return self.account(acc["id"])

    def open_recoveries(self, account_id: int | None = None) -> list[dict]:
        if account_id is not None:
            sql, args = "SELECT * FROM recovery_requests WHERE done_at IS NULL AND account_id = ?", (account_id,)
        else:
            sql, args = "SELECT * FROM recovery_requests WHERE done_at IS NULL ORDER BY created_at", ()
        return [dict(r) for r in self._conn.execute(sql, args)]

    def finish_recovery(self, request_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("UPDATE recovery_requests SET done_at = ? WHERE id = ? AND done_at IS NULL",
                                     (_iso(utcnow()), request_id))
            self._conn.commit()
        return cur.rowcount > 0

    # 0.15.0: uma chave por conta. Cada personagem só pode estar em uma chave, e cada chave tem até 50 personagens.
    MAX_CHARS_PER_KEY = 50

    def char_owner(self, name: str) -> str | None:
        """Chave onde o personagem já está cadastrado (ou None)."""
        row = self._conn.execute("SELECT key FROM key_chars WHERE name_key = ?", (name_key(name),)).fetchone()
        return row[0] if row else None

    def char_count(self, key: str) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM key_chars WHERE key = ?", (normalize_key(key),)).fetchone()[0]

    def add_char_manual(self, key: str, name: str) -> None:
        """Validação manual do criador: vincula o personagem sem código de verificação (o 1º vira main)."""
        key = normalize_key(key)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO key_chars VALUES (?, ?, ?, ?)", (key, name_key(name), name, _iso(utcnow())))
            self._conn.execute("UPDATE access_keys SET main_char = ? WHERE key = ? AND main_char IS NULL", (name, key))
            self._conn.commit()

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
                      uploader_key=row["uploader_key"], via=row["via"])
        if kind == "hunt":  # 0.20.0: local do lootsplit e quantas vezes já foi trocado
            report.update(place_id=row["place_id"], place_edits=row["place_edits"])
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

    # ---- 0.29.0: link público
    SPLIT_LINK_DAYS = 30

    def split_link_create(self, kind: str, hunt_id: int, by_key: str) -> dict:
        """Um link por lootsplit: pedir de novo devolve o mesmo (renovando o prazo)."""
        import secrets
        now = utcnow()
        exp = _iso(now + timedelta(days=self.SPLIT_LINK_DAYS))
        with self._lock:
            row = self._conn.execute("SELECT token FROM split_links WHERE kind = ? AND hunt_id = ?", (kind, hunt_id)).fetchone()
            token = row["token"] if row else secrets.token_urlsafe(9)
            if row:
                self._conn.execute("UPDATE split_links SET expires_at = ? WHERE token = ?", (exp, token))
            else:
                self._conn.execute("INSERT INTO split_links (token, hunt_id, created_by, created_at, expires_at, kind) "
                                   "VALUES (?, ?, ?, ?, ?, ?)", (token, hunt_id, by_key, _iso(now), exp, kind))
            self._conn.commit()
        return {"token": token, "expires_at": exp}

    def split_link_target(self, token: str) -> tuple[str, int] | None:
        """(tipo, número do lootsplit) de um link que ainda vale."""
        row = self._conn.execute("SELECT kind, hunt_id, expires_at FROM split_links WHERE token = ?", (token,)).fetchone()
        if row is None or row["expires_at"] < _iso(utcnow()):
            return None
        return row["kind"], row["hunt_id"]

    def split_link_revoke(self, kind: str, hunt_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM split_links WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
            self._conn.commit()

    def _forget_split(self, kind: str, hunt_id: int) -> None:
        """Hunt apagada: some com as regras, os pagamentos e as marcações dela (chamar dentro do _lock)."""
        self._conn.execute("DELETE FROM split_links WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
        self._conn.execute("DELETE FROM hunt_payments WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
        self._conn.execute("DELETE FROM hunt_rules WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
        self._conn.execute("DELETE FROM hunt_tags WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))

    def hunt(self, hunt_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()
        return self._hunt(row) if row else None

    def add_hunt(self, report: dict, raw_text: str, submitted_by: str, uploader_key: str | None = None,
                 via: str | None = None) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM hunts WHERE fingerprint = ?", (report["fingerprint"],)).fetchone()
            if existing:
                return self._hunt(existing), False
            cur = self._conn.execute(
                "INSERT INTO hunts (fingerprint, started_at, submitted_by, created_at, raw_text, report_json, uploader_key, via) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (report["fingerprint"], report["started_at"], submitted_by, _iso(utcnow()), raw_text, json.dumps(report),
                 uploader_key, via),
            )
            hunt_id = cur.lastrowid
            self._conn.executemany(
                "INSERT INTO hunt_players (hunt_id, name_key, name) VALUES (?, ?, ?)",
                [(hunt_id, name_key(p["name"]), p["name"]) for p in report["players"]],
            )
            self._conn.commit()
            return self._hunt(self._conn.execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()), True

    # ---- 0.31.0: a mesma sessão enviada por mais de um membro
    def similar_hunts(self, report: dict, exclude_id: int | None = None) -> list[dict]:
        """Lootsplits já salvos que são a mesma sessão do relatório (mesma PT, mesmo período)."""
        from ..core.samesession import same_session
        try:
            t = datetime.fromisoformat(report["started_at"]).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError):
            return []
        lo, hi = (t - timedelta(hours=12)).isoformat(), (t + timedelta(hours=12)).isoformat()  # horário do jogo, sem fuso
        keys = [name_key(p["name"]) for p in report.get("players", [])]
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        rows = self._conn.execute(
            f"SELECT DISTINCT h.* FROM hunts h JOIN hunt_players p ON p.hunt_id = h.id "
            f"WHERE p.name_key IN ({marks}) AND h.started_at BETWEEN ? AND ? ORDER BY h.id LIMIT 100", (*keys, lo, hi)).fetchall()
        out = []
        for r in rows:
            if exclude_id and r["id"] == exclude_id:
                continue
            if same_session(report, json.loads(r["report_json"])):
                out.append(self._hunt(r))
        return out

    def update_hunt_report(self, hunt_id: int, report: dict, raw_text: str) -> dict | None:
        """Troca o conteúdo de um lootsplit por uma versão mais completa, no mesmo registro (id, local, regras,
        Input Analysers e link público continuam). Pagamentos de valor que mudou deixam de valer sozinhos."""
        with self._lock:
            if self._conn.execute("SELECT 1 FROM hunts WHERE fingerprint = ? AND id != ?", (report["fingerprint"], hunt_id)).fetchone():
                return None
            self._conn.execute("UPDATE hunts SET fingerprint = ?, started_at = ?, raw_text = ?, report_json = ? WHERE id = ?",
                               (report["fingerprint"], report["started_at"], raw_text, json.dumps(report), hunt_id))
            have = {r[0] for r in self._conn.execute("SELECT name_key FROM hunt_players WHERE hunt_id = ?", (hunt_id,))}
            self._conn.executemany("INSERT INTO hunt_players (hunt_id, name_key, name) VALUES (?, ?, ?)",
                                   [(hunt_id, name_key(p["name"]), p["name"]) for p in report["players"] if name_key(p["name"]) not in have])
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()
            return self._hunt(row) if row else None

    def merge_hunts(self, keep_id: int, drop_id: int) -> dict | None:
        """Junta duas cópias do mesmo lootsplit: tudo que a que sai tinha e a que fica não tem passa para a que fica."""
        with self._lock:
            keep = self._conn.execute("SELECT * FROM hunts WHERE id = ?", (keep_id,)).fetchone()
            drop = self._conn.execute("SELECT * FROM hunts WHERE id = ?", (drop_id,)).fetchone()
            if keep is None or drop is None or keep_id == drop_id:
                return None
            c = self._conn
            if keep["place_id"] is None and drop["place_id"] is not None:
                c.execute("UPDATE hunts SET place_id = ?, place_edits = ? WHERE id = ?", (drop["place_id"], drop["place_edits"], keep_id))
            for table, cols, where in (
                ("damage_inputs", "ref_id", "kind = 'hunt' AND ref_id"),
                ("party_sessions", "hunt_id", "hunt_id"),
            ):
                c.execute(f"UPDATE OR IGNORE {table} SET {cols} = ? WHERE {where} = ?", (keep_id, drop_id))
            c.execute("UPDATE OR IGNORE hunt_tags SET hunt_id = ? WHERE kind = 'hunt' AND hunt_id = ?", (keep_id, drop_id))
            c.execute("UPDATE OR IGNORE hunt_payments SET hunt_id = ? WHERE kind = 'hunt' AND hunt_id = ?", (keep_id, drop_id))
            c.execute("UPDATE OR IGNORE hunt_rules SET hunt_id = ? WHERE kind = 'hunt' AND hunt_id = ?", (keep_id, drop_id))
            c.execute("UPDATE split_links SET hunt_id = ? WHERE kind = 'hunt' AND hunt_id = ? "
                      "AND NOT EXISTS (SELECT 1 FROM split_links WHERE kind = 'hunt' AND hunt_id = ?)",
                      (keep_id, drop_id, keep_id))
            have = {r[0] for r in c.execute("SELECT name_key FROM hunt_players WHERE hunt_id = ?", (keep_id,))}
            for r in c.execute("SELECT name_key, name FROM hunt_players WHERE hunt_id = ?", (drop_id,)).fetchall():
                if r[0] not in have:
                    c.execute("INSERT INTO hunt_players (hunt_id, name_key, name) VALUES (?, ?, ?)", (keep_id, r[0], r[1]))
            c.execute("DELETE FROM damage_inputs WHERE kind = 'hunt' AND ref_id = ?", (drop_id,))
            c.execute("DELETE FROM party_sessions WHERE hunt_id = ?", (drop_id,))
            self.release_ref_gear("hunt", drop_id)
            c.execute("DELETE FROM hunts WHERE id = ?", (drop_id,))
            self._forget_split("hunt", drop_id)
            c.commit()
            return self._hunt(c.execute("SELECT * FROM hunts WHERE id = ?", (keep_id,)).fetchone())

    def hunts_for_player(self, name: str, limit: int = 500) -> list[dict]:
        rows = self._conn.execute(
            "SELECT h.* FROM hunts h JOIN hunt_players p ON p.hunt_id = h.id "
            "WHERE p.name_key = ? ORDER BY h.started_at DESC, h.id DESC LIMIT ?",
            (name_key(name), limit),
        ).fetchall()
        return [self._hunt(r) for r in rows]

    def delete_hunt(self, hunt_id: int) -> bool:
        with self._lock:
            self.release_ref_gear("hunt", hunt_id)  # 0.32.2: devolve as horas dos imbuements (só bosses não devolvem)
            cur = self._conn.execute("DELETE FROM hunts WHERE id = ?", (hunt_id,))
            self._forget_split("hunt", hunt_id)
            self._conn.execute("DELETE FROM damage_inputs WHERE kind = 'hunt' AND ref_id = ?", (hunt_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ stacker
    def uploader_of(self, table: str, row_id: int) -> tuple[bool, str | None]:
        """(existe?, código de acesso de quem enviou)."""
        assert table in ("hunts", "solo_sessions")
        row = self._conn.execute(f"SELECT uploader_key FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return (row is not None, row[0] if row else None)

    def add_solo(self, name: str, fingerprint: str, data: dict, uploader_key: str | None = None,
                 raw_text: str | None = None, place_id: int | None = None, level: int | None = None,
                 who: dict | None = None) -> tuple[dict, bool]:
        """who (0.23.0): {"via", "other_player", "played_by"} quando outra pessoa jogou/enviou."""
        who = who or {}
        with self._lock:
            existing = self._conn.execute("SELECT * FROM solo_sessions WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if existing:
                return dict(existing), False
            cols = ", ".join(SOLO_COLUMNS)
            marks = ", ".join("?" for _ in SOLO_COLUMNS)
            cur = self._conn.execute(
                f"INSERT INTO solo_sessions (fingerprint, name_key, name, created_at, uploader_key, raw_text, place_id, level, "
                f"via, other_player, played_by, content_hash, {cols}) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {marks})",
                (fingerprint, name_key(name), name, _iso(utcnow()), uploader_key, raw_text, place_id, level,
                 who.get("via"), 1 if who.get("other_player") else 0, who.get("played_by"),
                 session_content_hash(data) or "", *(data[c] for c in SOLO_COLUMNS)),
            )
            sid = cur.lastrowid
            self._conn.executemany("INSERT INTO solo_kills VALUES (?, ?, ?)", [(sid, c, n) for c, n in data.get("kills", [])])
            self._conn.executemany("INSERT INTO solo_loot VALUES (?, ?, ?)", [(sid, i, n) for i, n in data.get("loot", [])])
            self._conn.commit()
            return dict(self._conn.execute("SELECT * FROM solo_sessions WHERE id = ?", (cur.lastrowid,)).fetchone()), True

    def solo_session(self, session_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM solo_sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

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

    def npc_card(self, name: str) -> dict | None:
        """NPC da TibiaWiki BR e os itens que ele compra (os de maior preço primeiro)."""
        npc = self._conn.execute("SELECT * FROM wiki_npcs WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if npc is None:
            return None
        rows = self._conn.execute(
            "SELECT i.name, b.price FROM wiki_item_buyers b JOIN wiki_items i ON i.item_key = b.item_key "
            "WHERE b.npc = ? ORDER BY b.price DESC, i.name", (npc["name"],)).fetchall()
        return {"name": npc["name"], "city": npc["city"], "location": npc["location"],
                "coords": [npc["x"], npc["y"], npc["z"]] if npc["x"] is not None else None,
                "buys_total": len(rows), "buys": [[r["name"], r["price"]] for r in rows[:12]]}

    def wiki_place(self, name: str) -> dict | None:
        """Hunt importada da TibiaWiki BR, pelo nome."""
        row = self._conn.execute(
            f"SELECT {self._PLACE_COLS} FROM hunt_places WHERE name = ? COLLATE NOCASE AND source = 'wiki'", (name,)).fetchone()
        return dict(row) if row else None

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

    # ------------------------------------------------------------------ 📰 notícias do Tibia (0.22.0)
    _TN_COLS = "id, date, title, category, type"

    def tibia_news_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM tibia_news").fetchone()[0]

    def save_tibia_news_list(self, items: list[dict]) -> int:
        """Guarda/atualiza a lista (sem apagar o texto já baixado). Retorna quantas são novas."""
        now = _iso(utcnow())
        with self._lock:
            before = self._conn.execute("SELECT COUNT(*) FROM tibia_news").fetchone()[0]
            self._conn.executemany(
                "INSERT INTO tibia_news (id, date, title, category, type, listed_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET date = excluded.date, category = excluded.category, type = excluded.type, "
                "title = CASE WHEN tibia_news.content_html IS NULL THEN excluded.title ELSE tibia_news.title END",
                [(n["id"], n["date"], n["title"], n["category"], n["type"], now) for n in items])
            self._conn.commit()
            return self._conn.execute("SELECT COUNT(*) FROM tibia_news").fetchone()[0] - before

    def save_tibia_news_content(self, news_id: int, title: str, content_html: str, content_text: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE tibia_news SET content_html = ?, content_text = ?, fetched_at = ?, "
                               "title = CASE WHEN ? <> '' THEN ? ELSE title END WHERE id = ?",
                               (content_html, content_text, _iso(utcnow()), title, title, news_id))
            self._conn.commit()

    def tibia_news_missing(self, limit: int, since: str | None = None) -> list[int]:
        """Ids sem texto, das mais novas para as mais velhas (notícias e artigos antes dos tickers)."""
        extra, args = ("AND date >= ? ", [since]) if since else ("", [])
        return [r[0] for r in self._conn.execute(
            f"SELECT id FROM tibia_news WHERE content_html IS NULL {extra}"
            "ORDER BY date >= date('now', '-30 day') DESC, type = 'ticker', date DESC, id DESC LIMIT ?", (*args, limit))]

    def tibia_news_item(self, news_id: int) -> dict | None:
        row = self._conn.execute(f"SELECT {self._TN_COLS}, content_html FROM tibia_news WHERE id = ?", (news_id,)).fetchone()
        return dict(row) if row else None

    def tibia_news_latest(self, types: tuple[str, ...], limit: int, since: str | None = None) -> list[dict]:
        marks = ",".join("?" * len(types))
        extra, args = ("AND date >= ? ", [since]) if since else ("", [])
        return [dict(r) for r in self._conn.execute(
            f"SELECT {self._TN_COLS}, content_html FROM tibia_news WHERE type IN ({marks}) {extra}"
            "ORDER BY date DESC, id DESC LIMIT ?", (*types, *args, limit))]

    def tibia_news_search(self, date_from: str, date_to: str, categories: list[str], types: list[str],
                          q: str = "", limit: int = 300) -> tuple[list[dict], int]:
        """Mesmo filtro do News Archive do tibia.com (período, categorias, tipos) + pesquisa no título e no texto."""
        if not categories or not types:
            return [], 0
        where = ["date >= ?", "date <= ?", f"category IN ({','.join('?' * len(categories))})",
                 f"type IN ({','.join('?' * len(types))})"]
        args: list = [date_from, date_to, *categories, *types]
        for word in q.split()[:6]:
            like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(title LIKE ? ESCAPE '\\' OR content_text LIKE ? ESCAPE '\\')")
            args += [like, like]
        cond = " AND ".join(where)
        total = self._conn.execute(f"SELECT COUNT(*) FROM tibia_news WHERE {cond}", args).fetchone()[0]
        rows = self._conn.execute(f"SELECT {self._TN_COLS}, content_html IS NOT NULL AS saved FROM tibia_news "
                                  f"WHERE {cond} ORDER BY date DESC, id DESC LIMIT ?", (*args, limit))
        return [dict(r) for r in rows], total

    # ------------------------------------------------------------------ 🌐 traduções guardadas (0.22.2)
    @staticmethod
    def text_hash(text: str, html: bool = False) -> str:
        return hashlib.sha256(("h:" if html else "t:").encode() + text.encode("utf-8")).hexdigest()

    def translations(self, hashes: list[str], lang: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(hashes), 500):
            part = hashes[i:i + 500]
            marks = ",".join("?" * len(part))
            for h, t in self._conn.execute(f"SELECT src_hash, text FROM translations WHERE lang = ? AND src_hash IN ({marks})",
                                           (lang, *part)):
                out[h] = t
        return out

    def save_translations(self, rows: list[tuple[str, str]], lang: str) -> None:
        now = _iso(utcnow())
        with self._lock:
            self._conn.executemany("INSERT OR REPLACE INTO translations VALUES (?, ?, ?, ?)", [(h, lang, t, now) for h, t in rows])
            self._conn.commit()

    # ------------------------------------------------------------------ 📅 calendário do Tibia (0.22.1)
    def save_calendar(self, month: str, data: dict, raw_html: str) -> int:
        with self._lock:
            cur = self._conn.execute("INSERT INTO tibia_calendar (month, data_json, raw_html, created_at) VALUES (?, ?, ?, ?)",
                                     (month, json.dumps(data, ensure_ascii=False), raw_html, _iso(utcnow())))
            self._conn.commit()
            return cur.lastrowid

    def calendar(self, month: str) -> dict | None:
        """A colagem mais nova daquele mês (é a que o app mostra)."""
        row = self._conn.execute("SELECT data_json, created_at FROM tibia_calendar WHERE month = ? ORDER BY id DESC LIMIT 1",
                                 (month,)).fetchone()
        return {**json.loads(row[0]), "updated_at": row[1]} if row else None

    def calendar_months(self) -> list[dict]:
        return [{"month": r[0], "versions": r[1], "updated_at": r[2]} for r in self._conn.execute(
            "SELECT month, COUNT(*), MAX(created_at) FROM tibia_calendar GROUP BY month ORDER BY month DESC")]

    def delete_calendar_latest(self, month: str) -> bool:
        """Desfaz a última colagem do mês (volta a valer a anterior, se houver)."""
        with self._lock:
            row = self._conn.execute("SELECT MAX(id) FROM tibia_calendar WHERE month = ?", (month,)).fetchone()
            if not row or row[0] is None:
                return False
            self._conn.execute("DELETE FROM tibia_calendar WHERE id = ?", (row[0],))
            self._conn.commit()
            return True

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

    def ranking_rows(self, since: str, include_others: bool = False) -> list[dict]:
        """Totais do Stacker desde `since` de quem aceitou entrar no ranking (inclui quem não caçou: zeros)."""
        rows = self._conn.execute(
            "SELECT r.name, c.vocation, c.level, COUNT(s.id) AS sessions, COALESCE(SUM(s.xp), 0) AS xp, "
            "COALESCE(SUM(s.balance), 0) AS balance, COALESCE(SUM(s.duration_seconds), 0) AS seconds "
            "FROM ranking_optin r LEFT JOIN solo_sessions s ON s.name_key = r.name_key AND s.started_at >= ? "
            "AND (s.other_player = 0 OR ?) "  # 0.23.0: jogadas por outra pessoa só entram se pedir
            "LEFT JOIN char_info c ON c.name_key = r.name_key GROUP BY r.name_key", (since, 1 if include_others else 0))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ 0.25.0: confiança, XP e ranking pessoal
    TRUST_DAYS = 30

    def trust_upsert(self, name: str, manual: bool = False) -> None:
        """Marca o personagem como verificado agora. Verificação manual nunca é desfeita por uma automática."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO char_trust (name_key, name, verified_at, manual) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name_key) DO UPDATE SET name = excluded.name, verified_at = excluded.verified_at, "
                "manual = MAX(char_trust.manual, excluded.manual)",
                (name_key(name), name, _iso(utcnow()), 1 if manual else 0))
            self._conn.commit()

    def trust_valid(self, name: str) -> bool:
        """Verificado à mão (vale sempre) ou verificado há menos de TRUST_DAYS dias."""
        row = self._conn.execute("SELECT verified_at, manual FROM char_trust WHERE name_key = ?",
                                 (name_key(name),)).fetchone()
        if row is None:
            return False
        if row["manual"]:
            return True
        limite = _iso(utcnow() - timedelta(days=self.TRUST_DAYS))
        return row["verified_at"] > limite

    def trust_info(self, name: str) -> dict | None:
        row = self._conn.execute("SELECT name, verified_at, manual FROM char_trust WHERE name_key = ?",
                                 (name_key(name),)).fetchone()
        return dict(row) if row else None

    def xp_save(self, name: str, day: str, xp: int) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO xp_snapshots VALUES (?, ?, ?)", (name_key(name), day, xp))
            self._conn.commit()

    def xp_has(self, name: str, day: str) -> bool:
        return self._conn.execute("SELECT 1 FROM xp_snapshots WHERE name_key = ? AND day = ?",
                                  (name_key(name), day)).fetchone() is not None

    def xp_baseline(self, name: str, day: str) -> dict | None:
        """Ponto mais recente até `day` (inclusive)."""
        row = self._conn.execute("SELECT day, xp FROM xp_snapshots WHERE name_key = ? AND day <= ? "
                                 "ORDER BY day DESC LIMIT 1", (name_key(name), day)).fetchone()
        return dict(row) if row else None

    def xp_first(self, name: str) -> dict | None:
        row = self._conn.execute("SELECT day, xp FROM xp_snapshots WHERE name_key = ? ORDER BY day ASC LIMIT 1",
                                 (name_key(name),)).fetchone()
        return dict(row) if row else None

    def xp_latest(self, name: str) -> dict | None:
        row = self._conn.execute("SELECT day, xp FROM xp_snapshots WHERE name_key = ? ORDER BY day DESC LIMIT 1",
                                 (name_key(name),)).fetchone()
        return dict(row) if row else None

    def xp_first_from(self, name: str, day: str) -> dict | None:
        """Primeiro ponto de XP do personagem a partir de `day` (inclusive)."""
        row = self._conn.execute("SELECT day, xp FROM xp_snapshots WHERE name_key = ? AND day >= ? "
                                 "ORDER BY day ASC LIMIT 1", (name_key(name), day)).fetchone()
        return dict(row) if row else None

    def xp_series(self, name: str, since: str) -> list[dict]:
        """Pontos diários de XP do personagem desde `since` (inclusive), em ordem de dia."""
        return [dict(r) for r in self._conn.execute(
            "SELECT day, xp FROM xp_snapshots WHERE name_key = ? AND day >= ? ORDER BY day",
            (name_key(name), since))]

    def xp_session_gain(self, name: str, since: str) -> dict | None:
        """0.27.1: XP ganha nas sessões solo (Hunt Analyser individual) enviadas para o personagem desde `since`
        (AAAA-MM-DD, inclusive). Usado quando não há highscore/snapshot para ele (fora do top 1000).
        Devolve None se não houver nenhuma sessão no período."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(xp), 0) AS gain, COUNT(*) AS n, MIN(substr(started_at, 1, 10)) AS first_day "
            "FROM solo_sessions WHERE name_key = ? AND substr(started_at, 1, 10) >= ?",
            (name_key(name), since)).fetchone()
        if not row or not row["n"]:
            return None
        return {"gain": row["gain"], "sessions": row["n"], "first_day": row["first_day"]}

    def xp_board_names(self) -> list[str]:
        """Personagens do ranking: os cadastrados no site e os que aparecem nas hunts de party (Party Hunt Analyser)."""
        nomes = {}
        for r in self._conn.execute("SELECT name FROM key_chars UNION SELECT name FROM hunt_players"):
            nomes.setdefault(name_key(r["name"]), r["name"])
        return sorted(nomes.values(), key=str.lower)

    def xp_tracked_names(self) -> list[str]:
        """Personagens que precisam de snapshot: os do ranking e os da lista pessoal de alguma conta."""
        nomes = {}
        for r in self._conn.execute("SELECT name FROM key_chars UNION SELECT name FROM hunt_players "
                                    "UNION SELECT name FROM custom_ranking"):
            nomes.setdefault(name_key(r["name"]), r["name"])
        return list(nomes.values())

    # ------------------------------------------------------------------ 0.26.0: varredura de highscores
    def rank_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM rank_players").fetchone()[0]

    def rank_load_many(self, keys: list[str]) -> dict[str, dict]:
        if not keys:
            return {}
        out = {}
        for i in range(0, len(keys), 500):
            lote = keys[i:i + 500]
            marcas = ",".join("?" * len(lote))
            for r in self._conn.execute(f"SELECT name_key, name, world, values_json, world_changes FROM rank_players "
                                        f"WHERE name_key IN ({marcas})", lote):
                out[r["name_key"]] = {"name": r["name"], "world": r["world"], "world_changes": r["world_changes"],
                                      "values": json.loads(r["values_json"])}
        return out

    def rank_apply(self, *, day: str, updates: list[dict], changes: list[dict]) -> None:
        """Grava o estado atual dos acompanhados e as diferenças do dia, numa só transação."""
        with self._lock:
            self._conn.executemany(
                "INSERT INTO rank_players (name_key, name, world, level, vocation, values_json, world_changes, updated_day) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name_key) DO UPDATE SET name = excluded.name, "
                "world = excluded.world, level = excluded.level, vocation = excluded.vocation, "
                "values_json = excluded.values_json, world_changes = excluded.world_changes, "
                "updated_day = excluded.updated_day",
                [(u["name_key"], u["name"], u["world"], u["level"], u["vocation"], json.dumps(u["values"]),
                  u["world_changes"], day) for u in updates])
            self._conn.executemany(
                "INSERT OR REPLACE INTO rank_changes (day, name_key, name, category, old_value, new_value, delta, kind, "
                "world_from, world_to) VALUES (:day, :name_key, :name, :category, :old_value, :new_value, :delta, :kind, "
                ":world_from, :world_to)", changes)
            self._conn.commit()

    def rank_changes_for(self, name: str, since: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT day, category, old_value, new_value, delta, kind, world_from, world_to FROM rank_changes "
            "WHERE name_key = ? AND day >= ? ORDER BY day DESC, category", (name_key(name), since))]

    def scan_run_add(self, **kw) -> None:
        cols = ["started_at", "seconds", "first_load", "requests", "errors", "worlds", "tracked", "matched",
                "changes", "world_changes", "ok", "note"]
        valores = dict(kw)
        valores["first_load"] = 1 if valores["first_load"] else 0
        valores["ok"] = 1 if valores["ok"] else 0
        with self._lock:
            self._conn.execute(f"INSERT INTO scan_runs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               [valores[c] for c in cols])
            self._conn.commit()

    def rank_top_replace(self, day: str, tops: dict) -> None:
        """Troca o ranking geral inteiro pelo da varredura de hoje (uma transação)."""
        linhas = []
        for metrica, itens in tops.items():
            for pos, (valor, nome, mundo, level, voc) in enumerate(itens, start=1):
                linhas.append((metrica, pos, nome, mundo, level, voc, valor, day))
        with self._lock:
            self._conn.execute("DELETE FROM rank_top")
            self._conn.executemany("INSERT INTO rank_top VALUES (?, ?, ?, ?, ?, ?, ?, ?)", linhas)
            self._conn.commit()

    # ------------------------------------------------------------------ 0.27.0: VIP List
    def vip_add(self, owner_key: str, owner_char: str | None, name: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO vip_links (owner_key, owner_char, target_nk, target_name, added_at) "
                               "VALUES (?, ?, ?, ?, ?)", (owner_key, owner_char, name_key(name), name, _iso(utcnow())))
            self._conn.commit()

    def vip_remove(self, owner_key: str, name: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vip_links WHERE owner_key = ? AND target_nk = ?", (owner_key, name_key(name)))
            self._conn.commit()

    def vip_get(self, owner_key: str, name: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM vip_links WHERE owner_key = ? AND target_nk = ?",
                               (owner_key, name_key(name))).fetchone()
        return dict(r) if r else None

    def vip_by_id(self, link_id: int) -> dict | None:
        r = self._conn.execute("SELECT * FROM vip_links WHERE id = ?", (link_id,)).fetchone()
        return dict(r) if r else None

    def vip_list_owner(self, owner_key: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM vip_links WHERE owner_key = ? ORDER BY added_at", (owner_key,))]

    def vip_set_request(self, link_id: int, scopes_csv: str) -> None:
        """Pedido do dono. Sempre zera a resposta: ligar de novo exige nova autorização da outra pessoa."""
        with self._lock:
            self._conn.execute("UPDATE vip_links SET requested = ?, approved = NULL, answered_at = NULL WHERE id = ?",
                               (scopes_csv, link_id))
            self._conn.commit()

    def vip_answer(self, link_id: int, approved_csv: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE vip_links SET approved = ?, answered_at = ? WHERE id = ?",
                               (approved_csv, _iso(utcnow()), link_id))
            self._conn.commit()

    def vip_invites_for(self, name_keys: list[str]) -> list[dict]:
        """Pedidos que aguardam resposta de quem tem um destes personagens."""
        if not name_keys:
            return []
        marcas = ",".join("?" * len(name_keys))
        return [dict(r) for r in self._conn.execute(
            f"SELECT * FROM vip_links WHERE target_nk IN ({marcas}) AND requested != '' AND approved IS NULL "
            f"ORDER BY added_at", name_keys)]

    def vip_accepted_for(self, name_keys: list[str]) -> list[dict]:
        if not name_keys:
            return []
        marcas = ",".join("?" * len(name_keys))
        return [dict(r) for r in self._conn.execute(
            f"SELECT * FROM vip_links WHERE target_nk IN ({marcas}) AND approved IS NOT NULL ORDER BY added_at", name_keys)]

    def char_has_account(self, name: str) -> bool:
        return self._conn.execute("SELECT 1 FROM key_chars WHERE name_key = ? LIMIT 1", (name_key(name),)).fetchone() is not None

    def party_hunts_since(self, name: str, since: str) -> list[dict]:
        """Hunts de party (Party Hunt Analyser) em que o personagem jogou desde `since`, com a parte dele."""
        rows = self._conn.execute(
            "SELECT h.id, h.started_at, h.report_json, pl.name AS place FROM hunts h "
            "JOIN hunt_players hp ON hp.hunt_id = h.id LEFT JOIN hunt_places pl ON pl.id = h.place_id "
            "WHERE hp.name_key = ? AND h.started_at >= ? ORDER BY h.started_at DESC", (name_key(name), since)).fetchall()
        out = []
        for r in rows:
            rep = json.loads(r["report_json"] or "{}")
            me = next((p for p in rep.get("players", []) if name_key(p.get("name", "")) == name_key(name)), {})
            out.append({"id": r["id"], "started_at": r["started_at"], "place": r["place"],
                        "duration_seconds": rep.get("duration_seconds"), "players_count": rep.get("players_count"),
                        "balance": me.get("balance"), "profit_each": rep.get("profit_each")})
        return out

    def solo_sessions_for(self, name: str, since: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT started_at, xp, balance, duration_seconds, session_label FROM solo_sessions "
            "WHERE name_key = ? AND started_at >= ? AND other_player = 0 ORDER BY started_at DESC",
            (name_key(name), since))]

    def rank_top_page(self, metric: str, offset: int, limit: int) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT pos, name, world, level, vocation, value FROM rank_top WHERE metric = ? "
            "ORDER BY pos LIMIT ? OFFSET ?", (metric, limit, offset))]

    # ---- 0.30.0: top por mundo
    def rank_world_top_replace(self, day: str, rows: list[tuple]) -> None:
        """rows: (métrica, mundo, pos, valor, nome, level, vocação). Varredura sem nada não apaga o que já existe."""
        if not rows:
            return
        with self._lock:
            self._conn.execute("DELETE FROM rank_world_top")
            self._conn.executemany("INSERT INTO rank_world_top VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   [(m, w, p, v, n, lv, voc, day) for m, w, p, v, n, lv, voc in rows])
            self._conn.commit()

    def rank_worlds(self) -> list[str]:
        """Mundos que aparecem no ranking (do guardado por mundo e, na falta dele, do top geral)."""
        rows = self._conn.execute("SELECT DISTINCT world FROM rank_world_top WHERE world IS NOT NULL ORDER BY world").fetchall()
        if not rows:
            rows = self._conn.execute("SELECT DISTINCT world FROM rank_top WHERE world IS NOT NULL ORDER BY world").fetchall()
        return [r[0] for r in rows]

    def rank_world_page(self, metric: str, world: str, offset: int, limit: int) -> tuple[list[dict], int, str]:
        """(linhas, total, origem). Origem 'mundo' = top guardado do mundo; 'geral' = os do mundo dentro do top 1000."""
        total = self._conn.execute("SELECT COUNT(*) FROM rank_world_top WHERE metric = ? AND world = ?",
                                   (metric, world)).fetchone()[0]
        if total:
            rows = [dict(r) for r in self._conn.execute(
                "SELECT pos, name, world, level, vocation, value FROM rank_world_top WHERE metric = ? AND world = ? "
                "ORDER BY pos LIMIT ? OFFSET ?", (metric, world, limit, offset))]
            return rows, total, "mundo"
        total = self._conn.execute("SELECT COUNT(*) FROM rank_top WHERE metric = ? AND world = ?", (metric, world)).fetchone()[0]
        rows = [dict(r) for r in self._conn.execute(
            "SELECT name, world, level, vocation, value FROM rank_top WHERE metric = ? AND world = ? "
            "ORDER BY pos LIMIT ? OFFSET ?", (metric, world, limit, offset))]
        for i, r in enumerate(rows, start=offset + 1):
            r["pos"] = i
        return rows, total, "geral"

    def rank_top_day(self) -> str | None:
        r = self._conn.execute("SELECT MAX(day) FROM rank_top").fetchone()
        return r[0] if r else None

    def rank_player(self, name: str) -> dict | None:
        r = self._conn.execute("SELECT name, world, level, vocation, values_json, updated_day FROM rank_players "
                               "WHERE name_key = ?", (name_key(name),)).fetchone()
        if r is None:
            return None
        return {"name": r["name"], "world": r["world"], "level": r["level"], "vocation": r["vocation"],
                "values": json.loads(r["values_json"]), "updated_day": r["updated_day"]}

    def scan_runs(self, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,))]

    def custom_add(self, owner: str, name: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO custom_ranking VALUES (?, ?, ?, ?)",
                               (owner, name_key(name), name, _iso(utcnow())))
            self._conn.commit()

    def custom_remove(self, owner: str, name: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM custom_ranking WHERE owner_key = ? AND name_key = ?",
                               (owner, name_key(name)))
            self._conn.commit()

    def custom_list(self, owner: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT name FROM custom_ranking WHERE owner_key = ? ORDER BY added_at", (owner,))]

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
                    place_ids: list[int] | None = None, name: str | None = None, min_seconds: int = 600,
                    vocation: str | None = None) -> list[dict]:
        """XP/h, gold/h (balance), level médio e nº de jogadores por hunt. Ignora sessões com menos de 10 min.
        vocation (0.28.0): knight/paladin/druid/sorcerer/monk; só conta quem já tem a vocação conhecida (char_info)."""
        where, args = ["s.duration_seconds >= ?", "s.other_player = 0"], [min_seconds]  # 0.23.0: só quem jogou no próprio
        if vocation:
            where.append("LOWER(COALESCE(c.vocation, '')) LIKE ?"); args.append(f"%{vocation}%")
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
            "LEFT JOIN char_info c ON c.name_key = s.name_key "
            f"WHERE {' AND '.join(where)} GROUP BY p.id", args)
        out = []
        for r in rows:
            d = dict(r)
            hours = d["seconds"] / 3600
            d["xp_per_hour"] = round(d["xp"] / hours) if hours else 0
            d["gold_per_hour"] = round(d["balance"] / hours) if hours else 0
            out.append(d)
        return out

    def place_top(self, place_id: int, limit: int = 5, name: str | None = None) -> tuple[list, list]:
        """Criaturas e loot das sessões solo daquele local (name: só as sessões desse personagem)."""
        extra, args = ("AND s.name_key = ? ", [name_key(name)]) if name else ("", [])
        kills = self._conn.execute(
            "SELECT k.creature, SUM(k.count) AS n FROM solo_kills k JOIN solo_sessions s ON s.id = k.session_id "
            f"WHERE s.place_id = ? {extra}GROUP BY k.creature ORDER BY n DESC LIMIT ?", (place_id, *args, limit)).fetchall()
        loot = self._conn.execute(
            "SELECT l.item_key, SUM(l.count) AS n FROM solo_loot l JOIN solo_sessions s ON s.id = l.session_id "
            f"WHERE s.place_id = ? {extra}GROUP BY l.item_key", (place_id, *args)).fetchall()
        return [(r[0], r[1]) for r in kills], [(r[0], r[1]) for r in loot]

    # 0.22.0: hunts em party (lootsplits com local) são comparadas só com outras hunts em party
    def _party_hunts_at(self, place_ids: list[int] | None = None, name: str | None = None) -> list[sqlite3.Row]:
        where, args = ["h.place_id IS NOT NULL"], []
        if place_ids:
            where.append(f"h.place_id IN ({','.join('?' * len(place_ids))})"); args += place_ids
        if name:
            where.append("h.id IN (SELECT hunt_id FROM hunt_players WHERE name_key = ?)"); args.append(name_key(name))
            # 0.23.0: o lootsplit em que outra pessoa jogou no personagem não entra no "seu" desempenho
            where.append("h.id NOT IN (SELECT hunt_id FROM hunt_tags WHERE kind = 'hunt' AND tag = 'other' AND name_key = ?)")
            args.append(name_key(name))
        return self._conn.execute(f"SELECT h.id, h.place_id, h.report_json FROM hunts h WHERE {' AND '.join(where)}", args).fetchall()

    def party_place_stats(self, min_level: int | None = None, max_level: int | None = None,
                          place_ids: list[int] | None = None, name: str | None = None, min_seconds: int = 600,
                          vocation: str | None = None) -> list[dict]:
        """Mesmo formato do place_stats, só com lootsplits. Gold/h = lucro de cada um por hora;
        XP/h vem dos Hunt Analysers que os membros juntaram ao lootsplit."""
        hunts = self._party_hunts_at(place_ids, name)
        if not hunts:
            return []
        ids = [h["id"] for h in hunts]
        marks = ",".join("?" * len(ids))
        members: dict[int, list[str]] = {}
        for r in self._conn.execute(f"SELECT hunt_id, name_key FROM hunt_players WHERE hunt_id IN ({marks})", ids):
            members.setdefault(r[0], []).append(r[1])
        levels = {r[0]: r[1] for r in self._conn.execute(
            f"SELECT name_key, level FROM char_info WHERE level IS NOT NULL AND name_key IN "
            f"(SELECT name_key FROM hunt_players WHERE hunt_id IN ({marks}))", ids)}
        vocs: dict[str, str] = {}  # 0.28.0: vocação conhecida de cada membro (para o filtro por vocação)
        if vocation:
            vocs = {r[0]: (r[1] or "").lower() for r in self._conn.execute(
                f"SELECT name_key, vocation FROM char_info WHERE name_key IN "
                f"(SELECT name_key FROM hunt_players WHERE hunt_id IN ({marks}))", ids)}
        xp: dict[int, list[int]] = {}  # hunt_id -> [xp, segundos] das sessões juntadas
        for r in self._conn.execute(f"SELECT hunt_id, name_key, data_json FROM party_sessions WHERE hunt_id IN ({marks}) "
                                    "AND other_player = 0", ids):
            if name and r[1] != name_key(name):
                continue
            d = json.loads(r[2])
            a = xp.setdefault(r[0], [0, 0])
            a[0] += int(d.get("xp") or 0); a[1] += int(d.get("duration_seconds") or 0)
        acc: dict[int, dict] = {}
        for h in hunts:
            rep = json.loads(h["report_json"])
            secs = int(rep.get("duration_seconds") or 0)
            if secs < min_seconds:
                continue
            if vocation and not any(vocation in vocs.get(k, "") for k in members.get(h["id"], [])):
                continue  # nenhum membro com essa vocação
            lv = [levels[k] for k in members.get(h["id"], []) if k in levels]
            avg_lv = sum(lv) / len(lv) if lv else None
            if (min_level is not None or max_level is not None) and avg_lv is None:
                continue
            if min_level is not None and avg_lv < min_level or max_level is not None and avg_lv > max_level:
                continue
            a = acc.setdefault(h["place_id"], {"sessions": 0, "seconds": 0, "profit": 0, "team": 0, "names": set(),
                                               "levels": [], "xp": 0, "xp_seconds": 0})
            a["sessions"] += 1
            a["seconds"] += secs
            a["profit"] += int(rep.get("profit_each") or 0)
            a["team"] += int(rep.get("players_count") or 0)
            a["names"].update(members.get(h["id"], []))
            a["levels"] += lv
            if h["id"] in xp:
                a["xp"] += xp[h["id"]][0]; a["xp_seconds"] += xp[h["id"]][1]
        out = []
        for pid, a in acc.items():
            p = self.place(pid)
            if not p:
                continue
            hours = a["seconds"] / 3600
            out.append({"id": pid, "name": p["name"], "city": p.get("city"), "wiki_level": p.get("level"),
                        "sessions": a["sessions"], "players": len(a["names"]), "seconds": a["seconds"],
                        "avg_team": round(a["team"] / a["sessions"], 1),
                        "avg_level": round(sum(a["levels"]) / len(a["levels"])) if a["levels"] else None,
                        "min_level": min(a["levels"]) if a["levels"] else None,
                        "max_level": max(a["levels"]) if a["levels"] else None,
                        "gold_per_hour": round(a["profit"] / hours) if hours else 0,
                        "xp_per_hour": round(a["xp"] * 3600 / a["xp_seconds"]) if a["xp_seconds"] else 0})
        return out

    def party_place_top(self, place_id: int, name: str, limit: int = 5) -> tuple[list, list]:
        """Criaturas e loot do personagem nos lootsplits daquele local (das sessões que ele juntou)."""
        kills: dict[str, int] = {}
        loot: dict[str, int] = {}
        for r in self._conn.execute(
                "SELECT ps.data_json FROM party_sessions ps JOIN hunts h ON h.id = ps.hunt_id "
                "WHERE h.place_id = ? AND ps.name_key = ?", (place_id, name_key(name))):
            d = json.loads(r[0])
            for c, n in d.get("kills", []):
                kills[c] = kills.get(c, 0) + int(n)
            for k, n in d.get("loot", []):
                loot[k] = loot.get(k, 0) + int(n)
        top = sorted(kills.items(), key=lambda x: -x[1])[:limit]
        return top, list(loot.items())

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
            row = self._conn.execute("SELECT expires_at FROM access_keys WHERE key = ? AND lifetime = 0", (key,)).fetchone()
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
            self._conn.execute("DELETE FROM damage_inputs WHERE kind = 'solo' AND ref_id = ?", (session_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ 0.31.2: correção manual do administrador
    def set_input(self, kind: str, ref_id: int, name: str, data: dict) -> dict | None:
        """Troca os valores de um Input Analyser já salvo (só o administrador). None se ele não existe."""
        with self._lock:
            row = self._conn.execute("SELECT id FROM damage_inputs WHERE kind = ? AND ref_id = ? AND name_key = ?",
                                     (kind, ref_id, name_key(name))).fetchone()
            if row is None:
                return None
            self._conn.execute("UPDATE damage_inputs SET data_json = ? WHERE id = ?", (json.dumps(data), row["id"]))
            self._conn.commit()
            return self._input(self._conn.execute("SELECT * FROM damage_inputs WHERE id = ?", (row["id"],)).fetchone())

    def delete_input(self, kind: str, ref_id: int, name: str) -> bool:
        """Apaga o Input Analyser de um personagem para ele poder enviar de novo (só o administrador)."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM damage_inputs WHERE kind = ? AND ref_id = ? AND name_key = ?",
                                     (kind, ref_id, name_key(name)))
            self._conn.commit()
            return cur.rowcount > 0

    def replace_solo(self, session_id: int, fingerprint: str, data: dict, raw_text: str) -> dict | None:
        """Troca o conteúdo de um Hunt Analyser (solo) no mesmo registro: id, local e Input Analyser continuam."""
        with self._lock:
            if self._conn.execute("SELECT id FROM solo_sessions WHERE id = ?", (session_id,)).fetchone() is None:
                return None
            if self._conn.execute("SELECT 1 FROM solo_sessions WHERE fingerprint = ? AND id != ?", (fingerprint, session_id)).fetchone():
                return {}
            sets = ", ".join(f"{c} = ?" for c in SOLO_COLUMNS)
            self._conn.execute(f"UPDATE solo_sessions SET fingerprint = ?, raw_text = ?, content_hash = ?, {sets} WHERE id = ?",
                               (fingerprint, raw_text, session_content_hash(data) or "", *(data[c] for c in SOLO_COLUMNS), session_id))
            self._conn.execute("DELETE FROM solo_kills WHERE session_id = ?", (session_id,))
            self._conn.execute("DELETE FROM solo_loot WHERE session_id = ?", (session_id,))
            self._conn.executemany("INSERT INTO solo_kills VALUES (?, ?, ?)", [(session_id, c, n) for c, n in data.get("kills", [])])
            self._conn.executemany("INSERT INTO solo_loot VALUES (?, ?, ?)", [(session_id, i, n) for i, n in data.get("loot", [])])
            self._conn.commit()
            return dict(self._conn.execute("SELECT * FROM solo_sessions WHERE id = ?", (session_id,)).fetchone())

    # ------------------------------------------------------------------ 0.32.0: imbuements e gastos invisíveis
    def gear_list(self, name: str) -> list[dict]:
        nk = name_key(name)
        items = [dict(r) for r in self._conn.execute("SELECT * FROM gear_items WHERE name_key = ? ORDER BY id", (nk,))]
        for it in items:
            it["native"] = json.loads(it["native"] or "[]")
            it["elements"] = json.loads(it.get("elements") or "[]")
            it["charges"] = [self._charge(r) for r in self._conn.execute(
                "SELECT * FROM gear_charges WHERE gear_id = ? AND ended_at IS NULL ORDER BY id", (it["id"],))]
        return items

    @staticmethod
    def _charge(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["plan"] = json.loads(d.pop("plan_json") or "{}")
        return d

    def gear_item(self, gear_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM gear_items WHERE id = ?", (gear_id,)).fetchone()
        return dict(row) if row else None

    def gear_add(self, name: str, item_name: str, kind: str, slots: int, native: list[str], catalog: str | None,
                 elements: list[str] | None = None) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO gear_items (name_key, name, kind, slots, native, catalog, elements, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name_key(name), item_name, kind, slots, json.dumps(native), catalog, json.dumps(elements or []), _iso(utcnow())))
            self._conn.commit()
        return self.gear_item(cur.lastrowid)

    def gear_update(self, gear_id: int, item_name: str, slots: int, native: list[str], elements: list[str] | None = None) -> None:
        with self._lock:
            self._conn.execute("UPDATE gear_items SET name = ?, slots = ?, native = ?, elements = ? WHERE id = ?",
                               (item_name, slots, json.dumps(native), json.dumps(elements or []), gear_id))
            self._conn.commit()

    # ------------------------------------------------------------------ 0.32.2: valor da Tibia Coin (em gold) por personagem
    def coin_get(self, name: str) -> int:
        row = self._conn.execute("SELECT tc_gold FROM char_prefs WHERE name_key = ?", (name_key(name),)).fetchone()
        return int(row[0]) if row else 0

    def coin_map(self, names: list[str]) -> dict[str, int]:
        keys = [name_key(n) for n in names]
        if not keys:
            return {}
        marks = ",".join("?" * len(keys))
        return {r[0]: int(r[1]) for r in self._conn.execute(
            f"SELECT name_key, tc_gold FROM char_prefs WHERE name_key IN ({marks})", keys)}

    def coin_set(self, name: str, gold: int) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO char_prefs VALUES (?, ?, ?)", (name_key(name), gold, _iso(utcnow())))
            self._conn.commit()

    def gear_delete(self, gear_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM gear_items WHERE id = ?", (gear_id,))
            self._conn.commit()

    def charge_get(self, charge_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM gear_charges WHERE id = ?", (charge_id,)).fetchone()
        return self._charge(row) if row else None

    def charge_add(self, gear_id: int, imbuement: str, tier: int, plan: dict, total_cost: int, hours_total: float) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO gear_charges (gear_id, imbuement, tier, plan_json, total_cost, hours_total, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (gear_id, imbuement, tier, json.dumps(plan), total_cost, hours_total, _iso(utcnow())))
            self._conn.commit()
        return self.charge_get(cur.lastrowid)

    def charge_end(self, charge_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE gear_charges SET ended_at = ? WHERE id = ?", (_iso(utcnow()), charge_id))
            self._conn.commit()

    def _life_add(self, charge_id: int, hours: float) -> None:
        """Soma (ou tira, se negativo) horas do acumulado do equipamento + tipo de imbuement dessa recarga."""
        row = self._conn.execute("SELECT gear_id, imbuement FROM gear_charges WHERE id = ?", (charge_id,)).fetchone()
        if row:
            self._conn.execute("INSERT OR IGNORE INTO gear_lifetime VALUES (?, ?, 0)", (row[0], row[1]))
            self._conn.execute("UPDATE gear_lifetime SET hours = MAX(0, hours + ?) WHERE gear_id = ? AND imbuement = ?",
                               (hours, row[0], row[1]))

    def charge_add_hours(self, charge_id: int, hours: float) -> None:
        with self._lock:
            self._conn.execute("UPDATE gear_charges SET hours_used = MAX(0, hours_used + ?) WHERE id = ?", (hours, charge_id))
            self._life_add(charge_id, hours)
            self._conn.commit()

    def life_add_extra(self, charge_id: int, hours: float) -> None:
        """Horas usadas antes de refazer o imbuement (não entram no contador do ciclo, entram no acumulado)."""
        with self._lock:
            self._life_add(charge_id, hours)
            self._conn.commit()

    def lifetime_for(self, gear_ids: list[int]) -> dict[int, dict[str, float]]:
        out: dict[int, dict[str, float]] = {}
        for i in range(0, len(gear_ids), 500):
            chunk = gear_ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self._conn.execute(f"SELECT gear_id, imbuement, hours FROM gear_lifetime WHERE gear_id IN ({marks})", chunk):
                out.setdefault(r[0], {})[r[1]] = r[2]
        return out

    def usage_add(self, name: str, kind: str, ref_id: int, charge_id: int | None, label: str, hours: float, cost: int,
                  day: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO gear_usage (name_key, kind, ref_id, charge_id, label, hours, cost, day, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (name_key(name), kind, ref_id, charge_id, label, hours, cost, day, _iso(utcnow())))
            self._conn.commit()

    def set_list(self, name: str) -> list[dict]:
        nk = name_key(name)
        out = []
        for s in self._conn.execute("SELECT * FROM gear_sets WHERE name_key = ? ORDER BY id", (nk,)).fetchall():
            d = dict(s)
            d["gear_ids"] = [r[0] for r in self._conn.execute("SELECT gear_id FROM gear_set_items WHERE set_id = ? ORDER BY gear_id", (s["id"],))]
            out.append(d)
        return out

    def set_get(self, set_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM gear_sets WHERE id = ?", (set_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["gear_ids"] = [r[0] for r in self._conn.execute("SELECT gear_id FROM gear_set_items WHERE set_id = ?", (set_id,))]
        return d

    def set_save(self, name: str, set_id: int | None, set_name: str, place_id: int | None, gear_ids: list[int]) -> dict:
        with self._lock:
            if set_id:
                self._conn.execute("UPDATE gear_sets SET name = ?, place_id = ? WHERE id = ?", (set_name, place_id, set_id))
                self._conn.execute("DELETE FROM gear_set_items WHERE set_id = ?", (set_id,))
            else:
                set_id = self._conn.execute("INSERT INTO gear_sets (name_key, name, place_id, created_at) VALUES (?, ?, ?, ?)",
                                            (name_key(name), set_name, place_id, _iso(utcnow()))).lastrowid
            self._conn.executemany("INSERT OR IGNORE INTO gear_set_items VALUES (?, ?)", [(set_id, g) for g in gear_ids])
            self._conn.commit()
        return self.set_get(set_id)

    def set_delete(self, set_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM gear_sets WHERE id = ?", (set_id,))
            self._conn.commit()

    def session_gear_for(self, name: str, refs: list[tuple[str, int]]) -> dict[tuple[str, int], dict]:
        out: dict[tuple[str, int], dict] = {}
        nk = name_key(name)
        for kind in {k for k, _ in refs}:
            ids = [i for k, i in refs if k == kind]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for r in self._conn.execute(f"SELECT * FROM session_gear WHERE name_key = ? AND kind = ? AND ref_id IN ({marks})",
                                            (nk, kind, *chunk)):
                    out[(kind, r["ref_id"])] = dict(r)
        return out

    def charge_meta(self, charge_ids: list[int]) -> dict[int, dict]:
        """0.33.0: de cada recarga/imbuement, a chave e o tipo da peça (para separar imbuement, anel e amuleto nos relatórios)."""
        out: dict[int, dict] = {}
        ids = sorted(set(charge_ids))
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self._conn.execute(
                    f"SELECT c.id, c.imbuement, g.kind, g.name FROM gear_charges c JOIN gear_items g ON g.id = c.gear_id WHERE c.id IN ({marks})", chunk):
                out[r[0]] = {"imbuement": r[1], "item_kind": r[2], "item": r[3]}
        return out

    def usage_for_session(self, name: str, kind: str, ref_id: int) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM gear_usage WHERE name_key = ? AND kind = ? AND ref_id = ? ORDER BY id", (name_key(name), kind, ref_id))]

    def release_session_gear(self, name: str, kind: str, ref_id: int) -> None:
        """Desfaz o que a sessão tinha gasto dos imbuements (as horas voltam para cada contador)."""
        with self._lock:
            for u in self.usage_for_session(name, kind, ref_id):
                if u["charge_id"]:
                    self._conn.execute("UPDATE gear_charges SET hours_used = MAX(0, hours_used - ?) WHERE id = ?",
                                       (u["hours"], u["charge_id"]))
                    self._life_add(u["charge_id"], -u["hours"])
            self._conn.execute("DELETE FROM gear_usage WHERE name_key = ? AND kind = ? AND ref_id = ?", (name_key(name), kind, ref_id))
            self._conn.execute("DELETE FROM session_gear WHERE name_key = ? AND kind = ? AND ref_id = ?", (name_key(name), kind, ref_id))
            self._conn.commit()

    def session_gear_save(self, name: str, kind: str, ref_id: int, set_id: int | None, set_name: str | None,
                          pause: int, hours: float, cost: int, auto: bool = False) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO session_gear (kind, ref_id, name_key, set_id, set_name, pause_minutes, hours, cost, assigned_at, auto) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, ref_id, name_key(name), set_id, set_name, pause, hours, cost, _iso(utcnow()), 1 if auto else 0))
            self._conn.commit()

    def session_gear_one(self, name: str, kind: str, ref_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM session_gear WHERE name_key = ? AND kind = ? AND ref_id = ?",
                                 (name_key(name), kind, ref_id)).fetchone()
        return dict(row) if row else None

    def release_ref_gear(self, kind: str, ref_id: int) -> None:
        """0.32.2: apagou a sessão/hunt: as horas dos imbuements voltam para todos os jogadores que tinham um set nela."""
        with self._lock:
            for u in self._conn.execute("SELECT * FROM gear_usage WHERE kind = ? AND ref_id = ?", (kind, ref_id)).fetchall():
                if u["charge_id"]:
                    self._conn.execute("UPDATE gear_charges SET hours_used = MAX(0, hours_used - ?) WHERE id = ?",
                                       (u["hours"], u["charge_id"]))
                    self._life_add(u["charge_id"], -u["hours"])
            self._conn.execute("DELETE FROM gear_usage WHERE kind = ? AND ref_id = ?", (kind, ref_id))
            self._conn.execute("DELETE FROM session_gear WHERE kind = ? AND ref_id = ?", (kind, ref_id))
            self._conn.commit()

    def usage_since(self, name: str, kind: str, since_day: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM gear_usage WHERE name_key = ? AND kind = ? AND day >= ? ORDER BY day, id",
            (name_key(name), kind, since_day))]

    def usage_report(self, name: str, since_day: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM gear_usage WHERE name_key = ? AND day >= ? ORDER BY day, id", (name_key(name), since_day))]

    # 0.32.6: o set que o jogador usou em cada hunt (local). `confirmed`: ele disse "é esse mesmo", então passa a valer sozinho.
    def pref_get(self, name: str, place_id: int) -> dict | None:
        row = self._conn.execute("SELECT set_id, confirmed FROM gear_place_pref WHERE name_key = ? AND place_id = ?",
                                 (name_key(name), place_id)).fetchone()
        return {"set_id": row[0], "confirmed": bool(row[1])} if row else None

    def pref_set(self, name: str, place_id: int, set_id: int, confirmed: bool) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO gear_place_pref VALUES (?, ?, ?, ?, ?)",
                               (name_key(name), place_id, set_id, 1 if confirmed else 0, _iso(utcnow())))
            self._conn.commit()

    def pref_clear(self, name: str, place_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM gear_place_pref WHERE name_key = ? AND place_id = ?", (name_key(name), place_id))
            self._conn.commit()

    def last_set_for_place(self, name: str, place_id: int) -> dict | None:
        row = self._conn.execute("SELECT id FROM gear_sets WHERE name_key = ? AND place_id = ? ORDER BY id DESC LIMIT 1",
                                 (name_key(name), place_id)).fetchone()
        return self.set_get(row[0]) if row else None

    # preços informados pelos jogadores (média por mundo; ver imbuing.average_price)
    def imb_price_set(self, key: str, item: str, price: int | None, world: str | None) -> None:
        with self._lock:
            if price:
                self._conn.execute("INSERT OR REPLACE INTO imb_prices VALUES (?, ?, ?, ?, ?)", (key, item, price, world, _iso(utcnow())))
            else:
                self._conn.execute("DELETE FROM imb_prices WHERE key = ? AND item = ?", (key, item))
            self._conn.commit()

    def imb_prices_mine(self, key: str) -> dict[str, int]:
        return {r["item"]: r["price"] for r in self._conn.execute("SELECT item, price FROM imb_prices WHERE key = ?", (key,))}

    def imb_prices_all(self, world: str | None = None) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        sql, args = "SELECT item, price FROM imb_prices", ()
        if world:
            sql, args = sql + " WHERE world = ?", (world,)
        for r in self._conn.execute(sql, args):
            out.setdefault(r["item"], []).append(r["price"])
        return out

    # ------------------------------------------------------------------ 0.32.0: hunt session ao vivo
    LIVE_OPEN_HOURS = 6  # sessão ao vivo sem envio há mais que isso é considerada encerrada

    def live_open(self, name: str) -> dict | None:
        """A sessão ao vivo aberta do personagem (a última enviada nas últimas horas)."""
        since = _iso(utcnow() - timedelta(hours=self.LIVE_OPEN_HOURS))
        row = self._conn.execute("SELECT * FROM solo_sessions WHERE name_key = ? AND live = 1 AND live_touched_at >= ? "
                                 "ORDER BY live_touched_at DESC LIMIT 1", (name_key(name), since)).fetchone()
        return dict(row) if row else None

    def live_same_start(self, name: str, started_at: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM solo_sessions WHERE name_key = ? AND started_at = ? ORDER BY id DESC",
                                 (name_key(name), started_at)).fetchone()
        return dict(row) if row else None

    def live_points(self, session_id: int) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM live_points WHERE session_id = ? ORDER BY ended_at", (session_id,))]

    def live_start(self, name: str, fingerprint: str, data: dict, uploader_key: str | None, raw_text: str,
                   place_id: int | None, level: int | None, who: dict | None = None) -> tuple[dict, bool]:
        """Abre uma sessão ao vivo (a sessão em si é uma sessão solo comum, marcada como ao vivo)."""
        row, created = self.add_solo(name, fingerprint, data, uploader_key, raw_text, place_id, level, who)
        if created or not row.get("live"):
            with self._lock:
                self._conn.execute("UPDATE solo_sessions SET live = 1, live_touched_at = ? WHERE id = ?",
                                   (_iso(utcnow()), row["id"]))
                self._conn.commit()
        self._add_point(row["id"], data)
        return self.solo_session(row["id"]), created

    def live_update(self, session_id: int, name: str, data: dict, raw_text: str) -> tuple[dict, bool]:
        """Mais um envio da mesma sessão. O analisador é acumulado: vale o envio mais completo, e o que o envio
        anterior já tinha nunca é perdido (um envio atrasado, menor, só vira ponto do histórico)."""
        cur = self.solo_session(session_id)
        advanced = int(data["duration_seconds"]) >= int(cur["duration_seconds"]) and data["ended_at"] >= cur["ended_at"]
        row = cur
        if advanced:
            fp = hashlib.sha256(f"{name.lower()}|{data['started_at']}|{data['ended_at']}".encode()).hexdigest()
            got = self.replace_solo(session_id, fp, data, raw_text)
            row = got or cur
        with self._lock:
            self._conn.execute("UPDATE solo_sessions SET live = 1, live_touched_at = ? WHERE id = ?",
                               (_iso(utcnow()), session_id))
            self._conn.commit()
        self._add_point(session_id, data)
        return self.solo_session(session_id), advanced

    def _add_point(self, session_id: int, data: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO live_points (session_id, ended_at, sent_at, duration_seconds, xp, raw_xp, balance, "
                "supplies, damage, healing) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, data["ended_at"], _iso(utcnow()), data["duration_seconds"], data["xp"], data["raw_xp"],
                 data["balance"], data["supplies"], data["damage"], data["healing"]))
            self._conn.commit()

    def live_close(self, session_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE solo_sessions SET live = 0 WHERE id = ?", (session_id,))
            self._conn.commit()

    # ------------------------------------------------------------------ 0.20.0: tipo de player
    DEFAULT_PLAYER_TYPE = "comum"

    @staticmethod
    def player_types() -> tuple[str, ...]:
        return BASE_PLAYER_TYPES + extra_player_types()

    def player_type(self, key: str) -> str:
        row = self._conn.execute("SELECT player_type FROM player_prefs WHERE key = ?", (key,)).fetchone()
        return row[0] if row and row[0] in self.player_types() else self.DEFAULT_PLAYER_TYPE

    def player_type_chosen(self, key: str) -> bool:
        """A pessoa já respondeu "Você se considera um:" (na criação da conta ou depois)."""
        return self._conn.execute("SELECT 1 FROM player_prefs WHERE key = ?", (key,)).fetchone() is not None

    def reset_place_edits(self, table: str, row_id: int) -> bool:
        """Painel do administrador: libera de novo as 2 trocas de local."""
        assert table in ("hunts", "solo_sessions")
        with self._lock:
            cur = self._conn.execute(f"UPDATE {table} SET place_edits = 0 WHERE id = ?", (row_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def set_player_type(self, key: str, player_type: str) -> str:
        if player_type not in self.player_types():
            raise ValueError("Tipo de player inválido.")
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO player_prefs VALUES (?, ?, ?)", (key, player_type, _iso(utcnow())))
            self._conn.commit()
        return player_type

    # ------------------------------------------------------------------ 0.20.0: local da sessão / do lootsplit
    def place_state(self, table: str, row_id: int) -> dict | None:
        """{place_id, place_edits, uploader_key} da sessão do Stacker ou do lootsplit."""
        assert table in ("hunts", "solo_sessions")
        row = self._conn.execute(f"SELECT place_id, place_edits, uploader_key FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(row) if row else None

    def update_place(self, table: str, row_id: int, place_id: int | None, count_edit: bool) -> None:
        assert table in ("hunts", "solo_sessions")
        with self._lock:
            self._conn.execute(f"UPDATE {table} SET place_id = ?, place_edits = place_edits + ? WHERE id = ?",
                               (place_id, 1 if count_edit else 0, row_id))
            self._conn.commit()

    # ------------------------------------------------------------------ 0.20.0: Input Analyser e sessões da PT
    def add_input(self, kind: str, ref_id: int, name: str, data: dict, uploader_key: str) -> tuple[dict, bool]:
        """Guarda o Input Analyser. Já existe um desse personagem ali? Devolve o salvo (não dá para editar)."""
        assert kind in ("solo", "hunt")
        with self._lock:
            row = self._conn.execute("SELECT * FROM damage_inputs WHERE kind = ? AND ref_id = ? AND name_key = ?",
                                     (kind, ref_id, name_key(name))).fetchone()
            created = row is None
            if created:
                self._conn.execute(
                    "INSERT INTO damage_inputs (kind, ref_id, name_key, name, data_json, uploader_key, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (kind, ref_id, name_key(name), name, json.dumps(data), uploader_key,
                                                     _iso(utcnow())))
                self._conn.commit()
                row = self._conn.execute("SELECT * FROM damage_inputs WHERE kind = ? AND ref_id = ? AND name_key = ?",
                                         (kind, ref_id, name_key(name))).fetchone()
        return self._input(row), created

    @staticmethod
    def _input(row: sqlite3.Row) -> dict:
        return {"name": row["name"], "created_at": row["created_at"], **json.loads(row["data_json"])}

    def inputs_for(self, kind: str, ref_ids: list[int]) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {i: [] for i in ref_ids}
        if ref_ids:
            marks = ",".join("?" * len(ref_ids))
            for r in self._conn.execute(f"SELECT * FROM damage_inputs WHERE kind = ? AND ref_id IN ({marks}) ORDER BY id",
                                        (kind, *ref_ids)):
                out[r["ref_id"]].append(self._input(r))
        return out

    def inputs_for_place(self, place_id: int, mode: str | None = None, name: str | None = None) -> list[dict]:
        """Input Analysers de sessões (solo) e/ou lootsplits (party) marcados naquele local; name: só desse personagem."""
        solo = "SELECT d.* FROM damage_inputs d JOIN solo_sessions s ON d.kind = 'solo' AND s.id = d.ref_id WHERE s.place_id = ?"
        party = "SELECT d.* FROM damage_inputs d JOIN hunts h ON d.kind = 'hunt' AND h.id = d.ref_id WHERE h.place_id = ?"
        if mode == "solo":
            rows = self._conn.execute(solo, (place_id,))
        elif mode == "party":
            rows = self._conn.execute(party, (place_id,))
        else:
            rows = self._conn.execute(f"{solo} UNION ALL {party}", (place_id, place_id))
        out = [self._input(r) for r in rows]
        return [i for i in out if name_key(i["name"]) == name_key(name)] if name else out

    def add_party_session(self, hunt_id: int, name: str, data: dict, uploader_key: str,
                          who: dict | None = None) -> tuple[dict, bool]:
        who = who or {}
        with self._lock:
            row = self._conn.execute("SELECT * FROM party_sessions WHERE hunt_id = ? AND name_key = ?",
                                     (hunt_id, name_key(name))).fetchone()
            created = row is None
            if created:
                self._conn.execute(
                    "INSERT INTO party_sessions (hunt_id, name_key, name, data_json, uploader_key, created_at, via, "
                    "other_player, played_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (hunt_id, name_key(name), name, json.dumps(data), uploader_key, _iso(utcnow()), who.get("via"),
                     1 if who.get("other_player") else 0, who.get("played_by")))
                self._conn.commit()
                row = self._conn.execute("SELECT * FROM party_sessions WHERE hunt_id = ? AND name_key = ?",
                                         (hunt_id, name_key(name))).fetchone()
        return self._party_session(row), created

    @staticmethod
    def _party_session(r: sqlite3.Row) -> dict:
        return {"name": r["name"], "uploader_key": r["uploader_key"], **json.loads(r["data_json"]),
                "other_player": bool(r["other_player"]), "played_by": r["played_by"]}

    def party_sessions_for(self, hunt_ids: list[int]) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {i: [] for i in hunt_ids}
        if hunt_ids:
            marks = ",".join("?" * len(hunt_ids))
            for r in self._conn.execute(f"SELECT * FROM party_sessions WHERE hunt_id IN ({marks}) ORDER BY id", hunt_ids):
                out[r["hunt_id"]].append(self._party_session(r))
        return out

    # ------------------------------------------------------------------ 👑 rotação de bosses
    def add_boss_session(self, name: str, fingerprint: str, data: dict, mode: str, uploader_key: str,
                         who: dict | None = None) -> tuple[dict, bool]:
        who = who or {}
        with self._lock:
            existing = self._conn.execute("SELECT * FROM boss_sessions WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if existing:
                return dict(existing), False
            cols = ", ".join(SOLO_COLUMNS)
            marks = ", ".join("?" for _ in SOLO_COLUMNS)
            cur = self._conn.execute(
                f"INSERT INTO boss_sessions (fingerprint, name_key, name, mode, uploader_key, created_at, via, other_player, "
                f"played_by, content_hash, {cols}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {marks})",
                (fingerprint, name_key(name), name, mode, uploader_key, _iso(utcnow()), who.get("via"),
                 1 if who.get("other_player") else 0, who.get("played_by"), session_content_hash(data) or "",
                 *(data[c] for c in SOLO_COLUMNS)))
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

    def add_boss_hunt(self, report: dict, submitted_by: str, uploader_key: str, via: str | None = None) -> tuple[dict, bool]:
        with self._lock:
            existing = self._conn.execute("SELECT * FROM boss_hunts WHERE fingerprint = ?", (report["fingerprint"],)).fetchone()
            if existing:
                return self._boss_hunt(existing), False
            cur = self._conn.execute(
                "INSERT INTO boss_hunts (fingerprint, started_at, ended_at, submitted_by, uploader_key, created_at, report_json, via) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (report["fingerprint"], report["started_at"], report["ended_at"], submitted_by, uploader_key,
                 _iso(utcnow()), json.dumps(report), via))
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
            ref = "hunt" if table == "boss_hunts" else "session"  # 0.23.0: o cofre da rotação vai junto
            for (did,) in self._conn.execute("SELECT id FROM vault_drops WHERE ref_kind = ? AND ref_id = ?", (ref, row_id)).fetchall():
                self._conn.execute("DELETE FROM hunt_payments WHERE kind = 'drop' AND hunt_id = ?", (did,))
            for (cid,) in self._conn.execute("SELECT id FROM vault_crafts WHERE ref_kind = ? AND ref_id = ?", (ref, row_id)).fetchall():
                self._conn.execute("DELETE FROM hunt_payments WHERE kind = 'craft' AND hunt_id = ?", (cid,))
            self._conn.execute("DELETE FROM vault_drops WHERE ref_kind = ? AND ref_id = ?", (ref, row_id))
            self._conn.execute("DELETE FROM vault_crafts WHERE ref_kind = ? AND ref_id = ?", (ref, row_id))
            cur = self._conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ 0.23.0: 🤝 substituições
    MAX_ACTIVE_LINKS = 5

    def session_by_content(self, table: str, content_hash: str | None) -> dict | None:
        """Sessão igual (mesmos horários e números) já salva, em qualquer personagem."""
        assert table in ("solo_sessions", "boss_sessions")
        if not content_hash:
            return None
        row = self._conn.execute(f"SELECT id, name, name_key, uploader_key FROM {table} WHERE content_hash = ? LIMIT 1",
                                 (content_hash,)).fetchone()
        return dict(row) if row else None

    def create_link(self, owner_key: str, name: str, operator: str | None, scopes: list[str], hours: int,
                    max_uses: int) -> tuple[dict, str]:
        token = secrets.token_urlsafe(24)
        now = utcnow()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO upload_links (token_hash, owner_key, name_key, name, operator, operator_key, scopes, created_at, "
                "expires_at, max_uses) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (hash_token(token), owner_key, name_key(name), name, operator, name_key(operator) if operator else None,
                 ",".join(scopes), _iso(now), _iso(now + timedelta(hours=hours)), max_uses))
            self._conn.commit()
        return self.link(cur.lastrowid), token

    @staticmethod
    def _link_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["scopes"] = [s for s in d["scopes"].split(",") if s]
        d["active"] = (d["revoked_at"] is None and d["uses"] < d["max_uses"]
                       and datetime.fromisoformat(d["expires_at"]) > utcnow())
        return d

    def link(self, link_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM upload_links WHERE id = ?", (link_id,)).fetchone()
        return self._link_row(row) if row else None

    def link_by_token(self, token: str) -> dict | None:
        if not token or len(token) > 100:
            return None
        row = self._conn.execute("SELECT * FROM upload_links WHERE token_hash = ?", (hash_token(token),)).fetchone()
        return self._link_row(row) if row else None

    def links_of(self, owner_key: str, limit: int = 30) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM upload_links WHERE owner_key = ? ORDER BY id DESC LIMIT ?", (owner_key, limit))
        return [self._link_row(r) for r in rows]

    def active_links_count(self, owner_key: str) -> int:
        return sum(1 for link in self.links_of(owner_key, 100) if link["active"])

    def grants_for(self, names: list[str]) -> list[dict]:
        """Links ativos que autorizam algum destes personagens a enviar pelo dono (jogador autorizado)."""
        keys = [name_key(n) for n in names]
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        rows = self._conn.execute(f"SELECT * FROM upload_links WHERE operator_key IN ({marks}) ORDER BY id DESC", keys)
        return [link for link in (self._link_row(r) for r in rows) if link["active"]]

    def revoke_link(self, link_id: int, owner_key: str) -> bool:
        with self._lock:
            cur = self._conn.execute("UPDATE upload_links SET revoked_at = ? WHERE id = ? AND owner_key = ? AND revoked_at IS NULL",
                                     (_iso(utcnow()), link_id, owner_key))
            self._conn.commit()
        return cur.rowcount > 0

    def use_link(self, link_id: int) -> bool:
        """Gasta um envio do link (só se ainda estiver valendo). Feito de uma vez: dois envios juntos não passam do limite."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE upload_links SET uses = uses + 1 WHERE id = ? AND revoked_at IS NULL AND uses < max_uses AND expires_at > ?",
                (link_id, _iso(utcnow())))
            self._conn.commit()
        return cur.rowcount > 0

    def refund_link(self, link_id: int) -> None:
        """O envio não gravou nada novo (já estava salvo): devolve o envio gasto."""
        with self._lock:
            self._conn.execute("UPDATE upload_links SET uses = uses - 1 WHERE id = ? AND uses > 0", (link_id,))
            self._conn.commit()

    def sends_by_others(self, owner_key: str, since: datetime) -> int:
        """Quantas coisas chegaram pelo link de envio / jogador autorizado para este código desde `since`."""
        s = _iso(since)
        return self._conn.execute(
            "SELECT (SELECT COUNT(*) FROM solo_sessions WHERE uploader_key = ? AND via IS NOT NULL AND created_at >= ?)"
            " + (SELECT COUNT(*) FROM boss_sessions WHERE uploader_key = ? AND via IS NOT NULL AND created_at >= ?)"
            " + (SELECT COUNT(*) FROM party_sessions WHERE uploader_key = ? AND via IS NOT NULL AND created_at >= ?)"
            " + (SELECT COUNT(*) FROM hunts WHERE uploader_key = ? AND via IS NOT NULL AND created_at >= ?)"
            " + (SELECT COUNT(*) FROM boss_hunts WHERE uploader_key = ? AND via IS NOT NULL AND created_at >= ?)",
            (owner_key, s) * 5).fetchone()[0]

    # marcações por jogador num lootsplit
    def tags_for(self, kind: str, hunt_ids: list[int]) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {i: [] for i in hunt_ids}
        if hunt_ids:
            marks = ",".join("?" * len(hunt_ids))
            for r in self._conn.execute(f"SELECT * FROM hunt_tags WHERE kind = ? AND hunt_id IN ({marks})", (kind, *hunt_ids)):
                out[r["hunt_id"]].append(dict(r))
        return out

    def set_tag(self, kind: str, hunt_id: int, name: str, tag: str, on: bool, played_by: str | None = None,
                by_key: str | None = None) -> bool:
        """Liga/desliga uma marcação. 'sub' e 'nosub' se excluem. Devolve True se mudou algo."""
        assert tag in ("other", "sub", "nosub")
        with self._lock:
            k = name_key(name)
            if on and tag in ("sub", "nosub"):
                self._conn.execute("DELETE FROM hunt_tags WHERE kind = ? AND hunt_id = ? AND name_key = ? AND tag = ?",
                                   (kind, hunt_id, k, "nosub" if tag == "sub" else "sub"))
            if on:
                before = self._conn.execute("SELECT played_by FROM hunt_tags WHERE kind = ? AND hunt_id = ? AND name_key = ? "
                                            "AND tag = ?", (kind, hunt_id, k, tag)).fetchone()
                self._conn.execute("INSERT OR REPLACE INTO hunt_tags VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (kind, hunt_id, k, tag, played_by, by_key, _iso(utcnow())))
                changed = before is None or before[0] != played_by
            else:
                changed = self._conn.execute("DELETE FROM hunt_tags WHERE kind = ? AND hunt_id = ? AND name_key = ? AND tag = ?",
                                             (kind, hunt_id, k, tag)).rowcount > 0
            self._conn.commit()
        return changed

    def party_hunts_between(self, names: list[str], lo: str, hi: str, boss: bool = False) -> list[tuple[str, dict]]:
        """Lootsplits destes personagens que começaram entre lo e hi: [(name_key, report)] (para achar o da sessão)."""
        keys = [name_key(n) for n in names]
        if not keys:
            return []
        table, players = ("boss_hunts", "boss_hunt_players") if boss else ("hunts", "hunt_players")
        marks = ",".join("?" * len(keys))
        rows = self._conn.execute(
            f"SELECT p.name_key, h.id, h.report_json FROM {table} h JOIN {players} p ON p.hunt_id = h.id "
            f"WHERE p.name_key IN ({marks}) AND h.started_at BETWEEN ? AND ? LIMIT 200", (*keys, lo, hi))
        return [(r[0], {**json.loads(r[2]), "id": r[1]}) for r in rows]

    def rosters_with(self, keys: list[str], limit: int = 300) -> dict[int, dict[str, str]]:
        """Formação (name_key -> nome) dos lootsplits mais recentes em que algum destes personagens estava."""
        if not keys:
            return {}
        marks = ",".join("?" * len(keys))
        ids = [r[0] for r in self._conn.execute(
            f"SELECT DISTINCT hunt_id FROM hunt_players WHERE name_key IN ({marks}) ORDER BY hunt_id DESC LIMIT ?", (*keys, limit))]
        out: dict[int, dict[str, str]] = {i: {} for i in ids}
        if ids:
            m2 = ",".join("?" * len(ids))
            for r in self._conn.execute(f"SELECT hunt_id, name_key, name FROM hunt_players WHERE hunt_id IN ({m2})", ids):
                out[r[0]][r[1]] = r[2]
        return out

    def claim_hunt(self, kind: str, hunt_id: int, key: str, name: str) -> None:
        """Lootsplit enviado por quem não estava na PT: um membro assume (passa a ser quem enviou)."""
        table = "hunts" if kind == "hunt" else "boss_hunts"
        with self._lock:
            self._conn.execute(f"UPDATE {table} SET uploader_key = ?, submitted_by = ? WHERE id = ?", (key, name, hunt_id))
            self._conn.execute("DELETE FROM hunt_rules WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
            self._conn.execute("DELETE FROM hunt_payments WHERE kind = ? AND hunt_id = ?", (kind, hunt_id))
            self._conn.commit()

    def set_session_player(self, table: str, session_id: int, other: bool, played_by: str | None) -> None:
        assert table in ("solo_sessions", "boss_sessions")
        with self._lock:
            self._conn.execute(f"UPDATE {table} SET other_player = ?, played_by = ? WHERE id = ?",
                               (1 if other else 0, played_by if other else None, session_id))
            self._conn.commit()

    def played_for(self, names: list[str], limit: int = 50) -> list[dict]:
        """🤝 Joguei por outra pessoa: o que os donos marcaram como jogado por um destes personagens."""
        keys = [name_key(n) for n in names]
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        out = []
        for kind, table in (("solo", "solo_sessions"), ("boss", "boss_sessions")):
            for r in self._conn.execute(
                    f"SELECT id, name, started_at, duration_seconds, xp, balance FROM {table} "
                    f"WHERE other_player = 1 AND lower(played_by) IN ({marks}) ORDER BY started_at DESC LIMIT ?", (*keys, limit)):
                out.append({"kind": kind, **dict(r)})
        for r in self._conn.execute(
                f"SELECT t.kind, t.hunt_id, t.name_key, h.started_at, h.report_json FROM hunt_tags t "
                f"JOIN hunts h ON t.kind = 'hunt' AND h.id = t.hunt_id "
                f"WHERE t.tag = 'other' AND lower(t.played_by) IN ({marks}) ORDER BY h.started_at DESC LIMIT ?", (*keys, limit)):
            rep = json.loads(r["report_json"])
            p = next((p for p in rep.get("players", []) if name_key(p["name"]) == r["name_key"]), None)
            out.append({"kind": "hunt", "id": r["hunt_id"], "name": p["name"] if p else r["name_key"],
                        "started_at": r["started_at"], "duration_seconds": rep.get("duration_seconds", 0), "xp": None,
                        "balance": rep.get("profit_each")})
        return sorted(out, key=lambda x: x["started_at"], reverse=True)[:limit]

    # ------------------------------------------------------------------ 0.23.0: 🗃️ cofre da rotação
    def vault(self, ref_kind: str, ref_ids: list[int]) -> dict[int, dict]:
        """{ref_id: {"drops": [...], "crafts": [...]}}"""
        out: dict[int, dict] = {i: {"drops": [], "crafts": []} for i in ref_ids}
        if ref_ids:
            marks = ",".join("?" * len(ref_ids))
            for r in self._conn.execute(f"SELECT * FROM vault_drops WHERE ref_kind = ? AND ref_id IN ({marks}) "
                                        "ORDER BY COALESCE(dropped_on, ''), id",
                                        (ref_kind, *ref_ids)):
                out[r["ref_id"]]["drops"].append(dict(r))
            for r in self._conn.execute(f"SELECT * FROM vault_crafts WHERE ref_kind = ? AND ref_id IN ({marks}) ORDER BY id",
                                        (ref_kind, *ref_ids)):
                c = dict(r)
                c["bought"] = json.loads(c.pop("bought_json"))
                out[r["ref_id"]]["crafts"].append(c)
        return out

    def vault_drop(self, drop_id: int) -> dict | None:
        r = self._conn.execute("SELECT * FROM vault_drops WHERE id = ?", (drop_id,)).fetchone()
        return dict(r) if r else None

    def vault_craft(self, craft_id: int) -> dict | None:
        r = self._conn.execute("SELECT * FROM vault_crafts WHERE id = ?", (craft_id,)).fetchone()
        if not r:
            return None
        c = dict(r)
        c["bought"] = json.loads(c.pop("bought_json"))
        return c

    def add_vault_drop(self, ref_kind: str, ref_id: int, item: str, qty: int, dropped_by: str, price_each: int | None,
                       owner_key: str, dropped_on: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO vault_drops (ref_kind, ref_id, item, qty, dropped_by, price_each, owner_key, created_at, dropped_on) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (ref_kind, ref_id, item, qty, dropped_by, price_each, owner_key,
                                                       _iso(utcnow()), dropped_on))
            self._conn.commit()
        return cur.lastrowid

    def update_vault_drop(self, drop_id: int, **fields) -> None:
        allowed = {"price_each", "status", "sold_total", "market_fee", "sold_at", "craft_id"}
        sets = [k for k in fields if k in allowed]
        if not sets:
            return
        with self._lock:
            self._conn.execute(f"UPDATE vault_drops SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                               (*(fields[k] for k in sets), drop_id))
            if fields.get("status") in ("stock", "used"):  # deixou de ser venda: as marcações de "já paguei" caem
                self._conn.execute("DELETE FROM hunt_payments WHERE kind = 'drop' AND hunt_id = ?", (drop_id,))
            self._conn.commit()

    def delete_vault_drop(self, drop_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vault_drops WHERE id = ?", (drop_id,))
            self._conn.execute("DELETE FROM hunt_payments WHERE kind = 'drop' AND hunt_id = ?", (drop_id,))
            self._conn.commit()

    def take_one_vault_drop(self, drop_id: int) -> int:
        """Separa 1 unidade do drop (se tem 2 ou mais, vira duas linhas) e devolve o id da linha com 1 unidade."""
        with self._lock:
            d = self._conn.execute("SELECT * FROM vault_drops WHERE id = ?", (drop_id,)).fetchone()
            if d["qty"] <= 1:
                return drop_id
            self._conn.execute("UPDATE vault_drops SET qty = qty - 1 WHERE id = ?", (drop_id,))
            cur = self._conn.execute(
                "INSERT INTO vault_drops (ref_kind, ref_id, item, qty, dropped_by, price_each, owner_key, created_at, dropped_on) "
                "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)", (d["ref_kind"], d["ref_id"], d["item"], d["dropped_by"], d["price_each"],
                                                       d["owner_key"], d["created_at"], d["dropped_on"]))
            self._conn.commit()
            return cur.lastrowid

    def add_vault_craft(self, ref_kind: str, ref_id: int, set_key: str, drop_ids: list[int], bought: list[dict],
                        result: str | None, seller: str, owner_key: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO vault_crafts (ref_kind, ref_id, set_key, bought_json, result, seller, owner_key, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (ref_kind, ref_id, set_key, json.dumps(bought), result, seller, owner_key,
                                                    _iso(utcnow())))
            cid = cur.lastrowid
            for d in drop_ids:
                self._conn.execute("UPDATE vault_drops SET status = 'used', craft_id = ?, sold_total = NULL, sold_at = NULL "
                                   "WHERE id = ?", (cid, d))
            self._conn.commit()
        return cid

    def update_vault_craft(self, craft_id: int, **fields) -> None:
        allowed = {"result", "sold_total", "market_fee", "sold_at"}
        sets = [k for k in fields if k in allowed]
        if not sets:
            return
        with self._lock:
            self._conn.execute(f"UPDATE vault_crafts SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                               (*(fields[k] for k in sets), craft_id))
            self._conn.execute("DELETE FROM hunt_payments WHERE kind = 'craft' AND hunt_id = ?", (craft_id,))
            self._conn.commit()

    def delete_vault_craft(self, craft_id: int) -> None:
        """Desfaz o uso: as runas voltam para o estoque."""
        with self._lock:
            self._conn.execute("UPDATE vault_drops SET status = 'stock', craft_id = NULL WHERE craft_id = ?", (craft_id,))
            self._conn.execute("DELETE FROM vault_crafts WHERE id = ?", (craft_id,))
            self._conn.execute("DELETE FROM hunt_payments WHERE kind = 'craft' AND hunt_id = ?", (craft_id,))
            self._conn.commit()

    def payments_of(self, kind: str, ids: list[int]) -> dict[int, dict]:
        """{id: {(payer_key, receiver_key): {amount, paid_at}}} das marcações de "já paguei"."""
        out: dict[int, dict] = {i: {} for i in ids}
        if ids:
            marks = ",".join("?" * len(ids))
            for r in self._conn.execute(f"SELECT * FROM hunt_payments WHERE kind = ? AND hunt_id IN ({marks})", (kind, *ids)):
                out[r["hunt_id"]][(r["payer_key"], r["receiver_key"])] = {"amount": r["amount"], "paid_at": r["paid_at"]}
        return out

    # ------------------------------------------------------------------ 0.24.0: 👥 parties e 🗃️ cofre da party
    def _party_members(self, party_ids: list[int]) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {i: [] for i in party_ids}
        if party_ids:
            marks = ",".join("?" * len(party_ids))
            for r in self._conn.execute(f"SELECT * FROM party_members WHERE party_id IN ({marks}) "
                                        "ORDER BY role, name COLLATE NOCASE", tuple(party_ids)):
                out[r["party_id"]].append({"name": r["name"], "role": r["role"]})
        return out

    def party(self, party_id: int) -> dict | None:
        r = self._conn.execute("SELECT * FROM parties WHERE id = ?", (party_id,)).fetchone()
        if r is None:
            return None
        return {**dict(r), "members": self._party_members([party_id])[party_id]}

    def parties_with(self, names: list[str]) -> list[dict]:
        """Parties em que algum destes personagens está (como titular ou substituto)."""
        keys = sorted({name_key(n) for n in names})
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        ids = [r[0] for r in self._conn.execute(
            f"SELECT DISTINCT party_id FROM party_members WHERE name_key IN ({marks})", tuple(keys))]
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self._conn.execute(f"SELECT * FROM parties WHERE id IN ({marks}) ORDER BY name COLLATE NOCASE", tuple(ids))
        members = self._party_members(ids)
        return [{**dict(r), "members": members[r["id"]]} for r in rows]

    def parties_owned(self, key: str) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM parties WHERE owner_key = ?", (key,)).fetchone()[0]

    def save_party(self, party_id: int | None, name: str, kind: str, rotation: str | None, members: list[dict],
                   owner_key: str) -> int:
        """Cria (party_id=None) ou troca nome/tipo/formação. members = [{"name", "role"}]."""
        with self._lock:
            if party_id is None:
                party_id = self._conn.execute(
                    "INSERT INTO parties (name, kind, rotation, owner_key, created_at) VALUES (?, ?, ?, ?, ?)",
                    (name, kind, rotation, owner_key, _iso(utcnow()))).lastrowid
            else:
                self._conn.execute("UPDATE parties SET name = ?, kind = ?, rotation = ? WHERE id = ?",
                                   (name, kind, rotation, party_id))
                self._conn.execute("DELETE FROM party_members WHERE party_id = ?", (party_id,))
            self._conn.executemany("INSERT INTO party_members VALUES (?, ?, ?, ?)",
                                   [(party_id, name_key(m["name"]), m["name"], m["role"]) for m in members])
            self._conn.commit()
        return party_id

    def delete_party(self, party_id: int) -> None:
        with self._lock:
            for (iid,) in self._conn.execute("SELECT id FROM party_items WHERE party_id = ?", (party_id,)).fetchall():
                self._conn.execute("DELETE FROM hunt_payments WHERE kind IN ('pitem', 'psvc') AND hunt_id = ?", (iid,))
            for (cid,) in self._conn.execute("SELECT id FROM party_crafts WHERE party_id = ?", (party_id,)).fetchall():
                self._conn.execute("DELETE FROM hunt_payments WHERE kind = 'pcraft' AND hunt_id = ?", (cid,))
            for t in ("party_items", "party_crafts", "party_prices", "party_members"):
                self._conn.execute(f"DELETE FROM {t} WHERE party_id = ?", (party_id,))
            self._conn.execute("DELETE FROM parties WHERE id = ?", (party_id,))
            self._conn.commit()

    def party_vault(self, party_id: int) -> dict:
        items = [dict(r) for r in self._conn.execute("SELECT * FROM party_items WHERE party_id = ? ORDER BY id", (party_id,))]
        crafts = [dict(r) for r in self._conn.execute("SELECT * FROM party_crafts WHERE party_id = ? ORDER BY id", (party_id,))]
        prices = {r["item_key"]: dict(r) for r in self._conn.execute("SELECT * FROM party_prices WHERE party_id = ?", (party_id,))}
        return {"items": items, "crafts": crafts, "prices": prices}

    def set_party_price(self, party_id: int, item: str, price: int | None, by_key: str) -> None:
        with self._lock:
            if price is None:
                self._conn.execute("DELETE FROM party_prices WHERE party_id = ? AND item_key = ?", (party_id, name_key(item)))
            else:
                self._conn.execute("INSERT OR REPLACE INTO party_prices VALUES (?, ?, ?, ?, ?, ?)",
                                   (party_id, name_key(item), item, price, _iso(utcnow()), by_key))
            self._conn.commit()

    def party_item(self, item_id: int) -> dict | None:
        r = self._conn.execute("SELECT * FROM party_items WHERE id = ?", (item_id,)).fetchone()
        return dict(r) if r else None

    def party_craft(self, craft_id: int) -> dict | None:
        r = self._conn.execute("SELECT * FROM party_crafts WHERE id = ?", (craft_id,)).fetchone()
        return dict(r) if r else None

    def add_party_item(self, party_id: int, item: str, qty: int, origin: str, cost_each: int | None, holder: str,
                       obtained_on: str, note: str | None, owner_key: str, client: str | None = None) -> int:
        with self._lock:
            iid = self._conn.execute(
                "INSERT INTO party_items (party_id, item, qty, origin, cost_each, holder, obtained_on, note, owner_key, "
                "created_at, client) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (party_id, item, qty, origin, cost_each, holder, obtained_on, note, owner_key, _iso(utcnow()), client)).lastrowid
            self._conn.commit()
        return iid

    _PARTY_ITEM_FIELDS = {"origin", "cost_each", "holder", "status", "sold_total", "market_fee", "sold_at", "seller",
                          "craft_id", "ref_price", "qty", "note", "client"}
    _PARTY_CRAFT_FIELDS = {"result", "holder", "sold_total", "market_fee", "sold_at"}

    def update_party_item(self, item_id: int, **fields) -> None:
        sets = [k for k in fields if k in self._PARTY_ITEM_FIELDS]
        if sets:
            with self._lock:
                self._conn.execute(f"UPDATE party_items SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                                   (*[fields[k] for k in sets], item_id))
                self._conn.commit()

    def forget_payments(self, kind: str, ref_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM hunt_payments WHERE kind = ? AND hunt_id = ?", (kind, ref_id))
            self._conn.commit()

    def delete_party_item(self, item_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM hunt_payments WHERE kind IN ('pitem', 'psvc') AND hunt_id = ?", (item_id,))
            self._conn.execute("DELETE FROM party_items WHERE id = ?", (item_id,))
            self._conn.commit()

    def split_party_item(self, item_id: int) -> int:
        """Separa 1 unidade de um item com várias (para usar num craft) e devolve o id da unidade separada."""
        with self._lock:
            d = self._conn.execute("SELECT * FROM party_items WHERE id = ?", (item_id,)).fetchone()
            if d["qty"] <= 1:
                return item_id
            self._conn.execute("UPDATE party_items SET qty = qty - 1 WHERE id = ?", (item_id,))
            new_id = self._conn.execute(
                "INSERT INTO party_items (party_id, item, qty, origin, cost_each, holder, obtained_on, note, owner_key, "
                "created_at, client) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                (d["party_id"], d["item"], d["origin"], d["cost_each"], d["holder"], d["obtained_on"], d["note"],
                 d["owner_key"], d["created_at"], d["client"])).lastrowid
            self._conn.commit()
        return new_id

    def add_party_craft(self, party_id: int, set_key: str, used: list[tuple[int, int | None]], result: str | None,
                        holder: str, rng: dict, owner_key: str) -> int:
        """used = [(id do item, preço do cofre naquele momento)]."""
        with self._lock:
            cid = self._conn.execute(
                "INSERT INTO party_crafts (party_id, set_key, result, holder, min_value, max_value, cost, owner_key, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (party_id, set_key, result, holder, rng["min"], rng["max"], rng["cost"], owner_key, _iso(utcnow()))).lastrowid
            for iid, ref_price in used:
                self._conn.execute("UPDATE party_items SET status = 'used', craft_id = ?, ref_price = ? WHERE id = ?",
                                   (cid, ref_price, iid))
            self._conn.commit()
        return cid

    def update_party_craft(self, craft_id: int, **fields) -> None:
        sets = [k for k in fields if k in self._PARTY_CRAFT_FIELDS]
        if sets:
            with self._lock:
                self._conn.execute(f"UPDATE party_crafts SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                                   (*[fields[k] for k in sets], craft_id))
                self._conn.commit()

    def delete_party_craft(self, craft_id: int) -> None:
        """Desfaz o craft: os itens usados voltam para o estoque."""
        with self._lock:
            self._conn.execute("UPDATE party_items SET status = 'stock', craft_id = NULL, ref_price = NULL WHERE craft_id = ?",
                               (craft_id,))
            self._conn.execute("DELETE FROM hunt_payments WHERE kind = 'pcraft' AND hunt_id = ?", (craft_id,))
            self._conn.execute("DELETE FROM party_crafts WHERE id = ?", (craft_id,))
            self._conn.commit()

    def note_char_claim(self, name: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO char_claims VALUES (?, ?)", (name_key(name), _iso(utcnow())))
            self._conn.execute("DELETE FROM char_claims WHERE at < ?", (_iso(utcnow() - timedelta(days=60)),))
            self._conn.commit()

    def char_claims_since(self, names: list[str], since: datetime) -> list[dict]:
        keys = [name_key(n) for n in names]
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        rows = self._conn.execute(f"SELECT name_key, MAX(at) AS at, COUNT(*) AS n FROM char_claims WHERE name_key IN ({marks}) "
                                  "AND at >= ? GROUP BY name_key", (*keys, _iso(since)))
        return [dict(r) for r in rows]
