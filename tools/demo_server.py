"""Servidor de DEMONSTRAÇÃO do 4rt3mi5, com dados de teste (para conferir telas e gravar o vídeo).

- Usa um banco próprio em `demo-data/` (NUNCA o data/artemis.db) e apaga esse banco a cada início.
- Não consulta o TibiaData: personagens e vocações são fictícios.
- Mostra no terminal o código de acesso de teste; entre com ele e o nick "Bobeek" (sem verificação).

Uso: .venv\\Scripts\\python tools/demo_server.py   ->  http://localhost:8765
"""
from __future__ import annotations

import os
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo-data"
shutil.rmtree(DEMO_DIR, ignore_errors=True)
os.environ["ARTEMIS_DATA_DIR"] = str(DEMO_DIR)
sys.path.insert(0, str(ROOT))

from artemis.core.session import parse_solo_session  # noqa: E402
from artemis.core.report import report_from_text  # noqa: E402
from artemis.core.tibiadata import CharacterInfo  # noqa: E402
from artemis.server import app as server  # noqa: E402
from artemis.server.db import _iso  # noqa: E402

random.seed(7)
ME = "Bobeek"
DEMO_USER, DEMO_PASSWORD = "demo", "demo-artemis-2026"  # só no banco de demonstração (apagado a cada início)
PARTY = {"Bobeek": "Elite Knight", "Hilay": "Royal Paladin", "Jioe": "Elder Druid",
         "Vcte": "Master Sorcerer", "Kael Monge": "Exalted Monk"}


def fake_fetch(name, timeout=10):
    voc = PARTY.get(" ".join(name.split()).title(), "Royal Paladin")
    return CharacterInfo(name=" ".join(name.split()).title(), level=random.choice([312, 287, 405, 350]),
                         vocation=voc, world="Celebra", comment="")


server.fetch_character = fake_fetch
server.fetch_experience = lambda *a, **k: None
store = server.store


def num(n: int) -> str:
    return f"{n:,}"


def party_text(start: datetime, minutes: int, players: list[tuple[str, int, int, int, int]], leader: str) -> str:
    end = start + timedelta(minutes=minutes)
    loot = sum(p[1] for p in players)
    sup = sum(p[2] for p in players)
    lines = [f"Session data: From {start:%Y-%m-%d, %H:%M:%S} to {end:%Y-%m-%d, %H:%M:%S}",
             f"Session: {minutes // 60:02d}:{minutes % 60:02d}h", "Loot Type: Leader",
             f"Loot: {num(loot)}", f"Supplies: {num(sup)}", f"Balance: {num(loot - sup)}"]
    for name, lt, sp, dmg, heal in players:
        lines += [name + (" (Leader)" if name == leader else ""), f"\tLoot: {num(lt)}", f"\tSupplies: {num(sp)}",
                  f"\tBalance: {num(lt - sp)}", f"\tDamage: {num(dmg)}", f"\tHealing: {num(heal)}"]
    return "\n".join(lines)


def solo_text(start: datetime, minutes: int, xp: int, sup: int, kills: dict, loot: dict) -> str:
    end = start + timedelta(minutes=minutes)
    lines = [f"Session data: From {start:%Y-%m-%d, %H:%M:%S} to {end:%Y-%m-%d, %H:%M:%S}",
             f"Session: {minutes // 60:02d}:{minutes % 60:02d}h", f"Raw XP Gain: {num(int(xp / 1.5))}", f"XP Gain: {num(xp)}",
             "Loot: 0", f"Supplies: {num(sup)}", f"Balance: {num(random.randint(200_000, 900_000))}",
             f"Damage: {num(random.randint(8, 16) * 1_000_000)}", f"Damage/h: {num(random.randint(5, 9) * 1_000_000)}",
             f"Healing: {num(random.randint(1, 3) * 1_000_000)}", f"Healing/h: {num(random.randint(6, 18) * 100_000)}",
             "Killed Monsters:"] + [f"  {n}x {k}" for k, n in kills.items()] + ["Looted Items:"] + [f"  {n}x {k}" for k, n in loot.items()]
    return "\n".join(lines)


def set_created(table: str, row_id: int, when: datetime) -> None:
    store._conn.execute(f"UPDATE {table} SET created_at = ? WHERE id = ?", (_iso(when.astimezone(timezone.utc)), row_id))


def seed() -> str:
    store.create_key(30, "demo")
    key = "ART-DEMO-TEST"  # fixo, só existe neste banco de demonstração
    store._conn.execute("UPDATE access_keys SET key = ?", (key,))
    store._conn.commit()
    store.force_main(key, ME)
    # 0.16.0+: o app entra por conta; conta de teste ligada à chave (só existe neste banco de demonstração)
    acc = store.create_account(DEMO_USER, DEMO_PASSWORD)
    store.link_account_key(acc["id"], key)
    for alt in ("Hilay",):
        store._conn.execute("INSERT OR REPLACE INTO key_chars VALUES (?, ?, ?, ?)", (key, alt.lower(), alt, _iso(datetime.now(timezone.utc))))
    store._conn.commit()
    for n, v in PARTY.items():
        store.save_char_info(n, v, 300)

    places = {p["name"]: p["id"] for p in store.places()}
    spots = [places[n] for n in ("Darama Dragon Lair", "Asura Palace", "Asura Vaults") if n in places]
    now = datetime.now().replace(microsecond=0)

    # 9 party hunts nos últimos 40 dias
    for i in range(9):
        start = (now - timedelta(days=2 + i * 4)).replace(hour=20, minute=10)
        who = list(PARTY)[:4] if i % 3 else list(PARTY)
        players = [(n, random.randint(1, 7) * 1_000_000, random.randint(150, 600) * 1000,
                    random.randint(9, 18) * 1_000_000 * (2 if n == "Bobeek" else 1),
                    random.randint(1, 9) * 1_000_000 * (3 if n == "Jioe" else 1)) for n in who]
        report = report_from_text(party_text(start, random.choice([75, 90, 120]), players, "Vcte"))
        hunt, _ = store.add_hunt(report, "", ME, key)
        set_created("hunts", hunt["id"], start + timedelta(hours=2))

    # 🤝 0.23.0: a PT de sempre (4) com um substituto no lugar de Jioe + um link de envio valendo
    start = (now - timedelta(days=1)).replace(hour=21, minute=40)
    players = [(n, random.randint(1, 7) * 1_000_000, random.randint(150, 600) * 1000, random.randint(9, 18) * 1_000_000,
                random.randint(1, 9) * 1_000_000) for n in ("Bobeek", "Hilay", "Reserva Vip", "Vcte")]
    hunt, _ = store.add_hunt(report_from_text(party_text(start, 90, players, "Vcte")), "", ME, key)
    set_created("hunts", hunt["id"], start + timedelta(hours=2))
    store.create_link(key, ME, "Kael Monge", ["solo", "party", "boss"], 24, 10)

    # sessões solo em 26 dias seguidos (inclui hoje) + algumas antigas -> 12 semanas de gráfico
    kills_pool = ["dragon", "dragon lord", "asura", "frost dragon", "dawnfire asura"]
    loot_pool = ["gold coin", "platinum coin", "green dragon leather", "green dragon scale", "dragon shield",
                 "royal helmet", "small diamond", "small ruby", "dragon claw", "life crystal", "ham", "dragon lord trophy"]
    days = list(range(26)) + [33, 40, 47, 55, 62, 70, 77]
    for d in days:
        start = (now - timedelta(days=d)).replace(hour=random.choice([14, 18, 21]), minute=5)
        kills = {k: random.randint(20, 160) for k in random.sample(kills_pool, 3)}
        loot = {it: random.randint(1, 40) for it in random.sample(loot_pool, 6)}
        loot["platinum coin"] = random.randint(200, 900)
        s = parse_solo_session(solo_text(start, random.choice([45, 60, 90, 135, 190]), random.randint(25, 60) * 100_000 * (1 + d % 3),
                                         random.randint(150, 500) * 1000, kills, loot))
        row, _ = store.add_solo(ME, s.fingerprint(ME), s.to_dict(), key, None, random.choice(spots) if spots else None, 312)
        set_created("solo_sessions", row["id"], start.replace(hour=23, minute=50))  # enviada no mesmo dia
    store._conn.commit()

    # 👑 rotação de bosses: sessões solo, uma party com lootsplit e um boss no meio de uma hunt comum
    boss_runs = [("solo", {"grand master oberon": 1, "falcon knight": 6}, {"falcon battleaxe": 1, "platinum coin": 40}),
                 ("solo", {"the time guardian": 1}, {"soul stone": 1, "small diamond": 4, "platinum coin": 60}),
                 ("party", {"scarlett etzel": 1}, {"crystal coin": 1, "platinum coin": 90, "small topaz": 3})]
    for i, (mode, kills, loot) in enumerate(boss_runs):
        start = (now - timedelta(days=1 + i)).replace(hour=19, minute=0)
        s = parse_solo_session(solo_text(start, 25, 300_000, 200_000, kills, loot))
        row, _ = store.add_boss_session(ME, "boss|" + s.fingerprint(ME), s.to_dict(), mode, key)
        if mode == "party":
            players = [(n, random.randint(1, 4) * 1_000_000, random.randint(100, 300) * 1000, 5_000_000, 1_000_000)
                       for n in list(PARTY)[:4]]
            hunt, _ = store.add_boss_hunt(report_from_text(party_text(start, 25, players, "Vcte")), ME, key)
            store.link_boss_session(row["id"], hunt["id"])
            # 🗃️ 0.23.0: drops guardados no cofre da rotação (3 das 5 Crypt Runes)
            for item, who, ago in (("Icy Crypt Rune", "Hilay", 3), ("Icy Crypt Rune", "Jioe", 1), ("Fiery Crypt Rune", ME, 2),
                                   ("Deathly Crypt Rune", "Jioe", 1)):
                store.add_vault_drop("hunt", hunt["id"], item, 1, who, 8_000_000, key,
                                     (now - timedelta(days=ago)).date().isoformat())
    start = (now - timedelta(days=4)).replace(hour=15, minute=0)
    s = parse_solo_session(solo_text(start, 60, 2_000_000, 150_000, {"dragon": 90, "demodras": 1},
                                     {"dragon scale mail": 1, "golden mug": 1, "dragon ham": 7, "platinum coin": 80}))
    store.add_solo(ME, s.fingerprint(ME), s.to_dict(), key, None, spots[0] if spots else None, 312)
    store._conn.commit()

    # 🛡️ 0.24.0: party registrada da Graveborn com o cofre (as três sacolinhas) e um craft com a faixa de preço
    pid = store.save_party(None, "Graveborn da semana", "both", "graveborn",
                           [{"name": n, "role": "main"} for n in ("Bobeek", "Hilay", "Jioe", "Vcte")]
                           + [{"name": "Kael Monge", "role": "sub"}], key)
    for item, price in (("Ancient Crypt Rune", 12), ("Icy Crypt Rune", 12), ("Fiery Crypt Rune", 14),
                        ("Deathly Crypt Rune", 40), ("Necromantic Crypt Rune", 75)):
        store.set_party_price(pid, item, price * 1_000_000, key)
    today = datetime.now().date().isoformat()
    for item, origin, cost, who in (("Ancient Crypt Rune", "drop", None, "Bobeek"), ("Icy Crypt Rune", "buy", 12_000_000, "Hilay"),
                                    ("Fiery Crypt Rune", "drop", None, "Jioe"), ("Deathly Crypt Rune", "buy", 40_000_000, "Vcte"),
                                    ("Necromantic Crypt Rune", "drop", None, "Bobeek"), ("Fiery Crypt Rune", "service", 7_000_000, "Hilay"),
                                    ("Ancient Crypt Rune", "drop", None, "Jioe")):
        # service: runa garantida de 14kk -> a party paga a metade (7kk) ao serviçado, dividida entre os titulares
        store.add_party_item(pid, item, 1, origin, cost, who, today, None, key, "Cliente Serv" if origin == "service" else None)

    store.set_user_price("falcon battleaxe", "demo-outro", 650_000)  # item sem NPC com preço -> drop raro na demo
    for n in (ME, "Hilay", "Jioe"):  # 🥇 ranking entre amigos
        store.ranking_join(n, True)
    store.set_goal(ME, "day", "xp", 4_000_000)
    store.set_goal(ME, "week", "loot", 30_000_000)
    store.set_sell(ME, "green dragon leather", 20)
    store.set_sell(ME, "small diamond", 5000)
    store.set_sell(ME, "ham", None, sold_at=_iso(datetime.now(timezone.utc) - timedelta(days=60)), update_target=False)
    return key


if __name__ == "__main__":
    import uvicorn

    access = seed()
    print("\n  4rt3mi5 DEMO  ->  http://localhost:8765")
    print(f"  Código de acesso de teste: {access}   |   nick: {ME}   |   conta: {DEMO_USER} / {DEMO_PASSWORD}\n")
    uvicorn.run(server.app, host="127.0.0.1", port=8765, server_header=False, log_level="warning")
