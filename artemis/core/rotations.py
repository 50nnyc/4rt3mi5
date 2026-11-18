"""0.23.0: 👑 Rotações de bosses, taxa do Market e conjuntos de itens (Crypt Runes).

Rotação = grupo de bosses de uma mesma quest/lore. O nome sai dos bosses mortos:
  - só mini-bosses de um grupo .............. "GT"
  - só o boss da última sala ................ "Last room GT"
  - os dois ................................. "GT + Last room GT"
  - grupos com partes (Bastions) ............ "Bastions: Cobra + Falcon Bastion"
  - vários grupos ........................... "Rotação GT + GD"
Os nomes de criatura são comparados sem maiúsculas/artigo (item_key).
"""
from __future__ import annotations

from datetime import datetime

from .session import item_key

# label = como aparece no nome; final = boss(es) da última sala; final_label = nome quando só a última sala
GROUPS: list[dict] = [
    {"key": "graveborn", "label": "Graveborn", "quest": "The Roost of the Graveborn Quest",
     "bosses": ["Fatal Bug", "Eldritch Dragon Lord", "Ice Horror", "The Gravedigger"],
     "final": ["Bone Overlord", "Bonelords's Phylactery"], "final_label": "Last room Graveborn", "cooldown": "20h",
     "note": "Ordem: Adventurer Group (Fatal Bug) → Eldritch Dragon Lord → Ice Horror → The Gravedigger → Bone Overlord."},
    {"key": "hod", "label": "GT", "quest": "Heart of Destruction Quest",
     "bosses": ["Anomaly", "Charged Anomaly", "Outburst", "Charging Outburst", "Eradicator", "Realityquake", "Rupture"],
     "final": ["World Devourer"], "final_label": "Last room GT", "cooldown": "20h / last room 14 dias"},
    {"key": "fa", "label": "FA", "quest": "Ferumbras' Ascension Quest",
     "bosses": ["The Lord of the Lice", "Plagirath", "Zamulosh", "Mazoran", "The Shatterer", "Razzagorn", "Ragiaz",
                "Tarbaz", "Shulgrax"],
     "final": ["Ferumbras Mortal Shell"], "final_label": "Ferumbras", "cooldown": "last room 14 dias"},
    {"key": "gd", "label": "GD", "quest": "Grave Danger Quest",
     "bosses": ["Count Vlarkorth", "Lord Azaram", "Earl Osam", "Channeling Earl Osam", "Sir Baeloc", "Sir Nictros",
                "Duke Krule"],
     "final": ["King Zelos"], "final_label": "Last room GD", "cooldown": "20h"},
    {"key": "soulwar", "label": "Soul War", "quest": "Soul War Quest",
     "bosses": ["Goshnar's Malice", "Goshnar's Hatred", "Goshnar's Spite", "Goshnar's Greed", "Goshnar's Cruelty"],
     "final": ["Goshnar's Megalomania"], "final_label": "Last room Soul War", "cooldown": "20h / last room 3 dias"},
    {"key": "rottenblood", "label": "Rotten Blood", "quest": "Rotten Blood Quest",
     "bosses": ["Murcion", "Chagorz", "Ichgahal", "Vemiath"],
     "final": ["Bakragore"], "final_label": "Last room Rotten Blood", "cooldown": "20h / last room 3 dias"},
    {"key": "library", "label": "Secret Library", "quest": "The Secret Library Quest",
     "bosses": ["Ghulosh", "Gorzindel", "Lokathmor", "Mazzinor", "Supercharged Mazzinor"],
     "final": ["The Scourge of Oblivion"], "final_label": "Last room Secret Library", "cooldown": "20h"},
    {"key": "dreamcourts", "label": "Dream Courts", "quest": "The Dream Courts Quest",
     "bosses": ["Izcandar the Banished", "Maxxenius", "Alptramun", "Plagueroot", "Malofur Mangrinder"],
     "final": ["The Nightmare Beast"], "final_label": "Last room Dream Courts", "cooldown": "20h"},
    {"key": "feaster", "label": "Feaster of Souls", "quest": "Feaster of Souls Quest",
     "bosses": ["Irgix the Flimsy", "Unaz the Mean", "Vok the Freakish", "Brain Head", "Thaian", "The Unwelcome",
                "The Dread Maiden", "The Fear Feaster", "The Pale Worm"],
     "final": [], "final_label": "", "cooldown": "20h"},
    {"key": "fk", "label": "Forgotten Knowledge", "quest": "Forgotten Knowledge Quest",
     "bosses": ["Lloyd", "Lady Tenebris", "The Enraged Thorn Knight", "Soul of Dragonking Zyrtarch", "Melting Frozen Horror",
                "The Time Guardian", "The Blazing Time Guardian", "The Freezing Time Guardian"],
     "final": ["The Last Lore Keeper"], "final_label": "Last room Forgotten Knowledge", "cooldown": "20h"},
    # Lore dos Bastions: cada boss é uma "parte" (Cobra, Falcon, Lion, Stag) + Yselda (Bounac)
    {"key": "bastions", "label": "Bastions", "quest": "Bastions (Kesar / Etzel)",
     "parts": {"Scarlett Etzel": "Cobra Bastion", "Grand Master Oberon": "Falcon Bastion", "Drume": "Lion Bastion",
               "Court Warlock": "Stag Bastion", "Megasylvan Yselda": "Yselda"},
     "bosses": ["Scarlett Etzel", "Grand Master Oberon", "Drume", "Court Warlock", "Megasylvan Yselda"],
     "final": [], "final_label": "", "cooldown": "20h"},
    {"key": "werelion", "label": "Werelion", "quest": "Grimvale – An Ancient Feud (Lion Sanctum)",
     "bosses": ["Katex Blood Tongue", "Srezz Yellow Eyes", "Utua Stone Sting", "Yirkas Blue Scales"],
     "final": [], "final_label": "", "cooldown": "20h",
     "note": "Os 4 bosses do Lion Sanctum, embaixo de Lion's Rock (a feud dos werelions)."},
    {"key": "were", "label": "Were", "quest": "Grimvale (were)",
     "bosses": ["Black Vixen", "Bloodback", "Darkfang", "Sharpclaw", "Shadowpelt", "Tamru the Black",
                "Ayana the Crimson Curse", "Owin", "Rakesh Moonfang"],
     "final": [], "final_label": "", "cooldown": "20h"},
]
_BY_CREATURE: dict[str, tuple[dict, bool]] = {}
for _g in GROUPS:
    for _b in _g["bosses"]:
        _BY_CREATURE[item_key(_b)] = (_g, False)
    for _b in _g["final"]:
        _BY_CREATURE[item_key(_b)] = (_g, True)
_ORDER = {g["key"]: i for i, g in enumerate(GROUPS)}


def _bastion_name(parts: list[str]) -> str:
    """["Cobra Bastion", "Falcon Bastion", "Yselda"] -> "Cobra + Falcon Bastion + Yselda"."""
    bastions = [p[: -len(" Bastion")] for p in parts if p.endswith(" Bastion")]
    others = [p for p in parts if not p.endswith(" Bastion")]
    out = [" + ".join(bastions) + " Bastion"] if bastions else []
    return " + ".join(out + others)


def identify(kills: list[tuple[str, int]]) -> dict | None:
    """Rotação dos bosses mortos: {"name", "groups": [{key, label, quest, segment, bosses, final}]} ou None."""
    found: dict[str, dict] = {}
    for creature, n in kills:
        hit = _BY_CREATURE.get(item_key(creature))
        if not hit or n <= 0:
            continue
        g, is_final = hit
        f = found.setdefault(g["key"], {"group": g, "minis": [], "finals": []})
        name = next(b for b in g["bosses"] + g["final"] if item_key(b) == item_key(creature))
        (f["finals"] if is_final else f["minis"]).append(name)
    if not found:
        return None
    groups = []
    for key in sorted(found, key=_ORDER.get):
        f = found[key]
        g = f["group"]
        if g.get("parts"):
            parts = [g["parts"][b] for b in g["bosses"] if b in f["minis"]]
            segment = f"{g['label']}: {_bastion_name(parts)}"
        elif f["minis"] and f["finals"]:
            segment = f"{g['label']} + {g['final_label']}"
        elif f["finals"]:
            segment = g["final_label"]
        else:
            segment = g["label"]
        groups.append({"key": key, "label": g["label"], "quest": g["quest"], "segment": segment, "cooldown": g["cooldown"],
                       "note": g.get("note"), "bosses": f["minis"], "final": f["finals"]})
    if len(groups) == 1:
        name = "Rotação " + groups[0]["segment"]
    else:  # vários grupos: os de partes vão entre parênteses
        segs = [f"{x['label']} ({x['segment'].split(': ', 1)[1]})" if ": " in x["segment"] else x["segment"] for x in groups]
        name = "Rotação " + " + ".join(segs)
    return {"name": name, "groups": groups}


def catalog() -> list[dict]:
    return [{"key": g["key"], "label": g["label"], "quest": g["quest"], "bosses": g["bosses"], "final": g["final"],
             "cooldown": g["cooldown"], "note": g.get("note"), "parts": g.get("parts")} for g in GROUPS]


# ------------------------------------------------------------------ taxa do Market
# Notícia "Adjustment of Market Fee and Exercise Weapons" (tibia.com, 01/10/2026): a partir do server save de
# 06/10/2026 a taxa sobe de 2% para 2,5% e o teto de 1.000.000 para 2.500.000 gp. Mínimo de 20 gp (regra antiga).
FEE_RULES = [  # (vale a partir de, %, teto)
    ("2026-10-06T10:00:00", 2.5, 2_500_000),
    ("0000-01-01T00:00:00", 2.0, 1_000_000),
]
FEE_MIN = 20


def fee_rule(when: str | None = None) -> dict:
    when = when or datetime.now().isoformat(timespec="seconds")
    since, pct, cap = next(r for r in FEE_RULES if when >= r[0])
    return {"pct": pct, "cap": cap, "min": FEE_MIN, "since": since[:10]}


def market_fee(total: int, when: str | None = None) -> int:
    """Taxa do Market sobre o valor total da venda (pela regra que valia na data da venda)."""
    if total <= 0:
        return 0
    r = fee_rule(when)
    return min(r["cap"], max(FEE_MIN, int(total * r["pct"] / 100)))


# ------------------------------------------------------------------ conjuntos que viram outro item
SETS = {
    "crypt": {
        "label": "Crypt Runes",
        "items": ["Ancient Crypt Rune", "Deathly Crypt Rune", "Fiery Crypt Rune", "Icy Crypt Rune", "Necromantic Crypt Rune"],
        "drops": {"Ancient Crypt Rune": "Fatal Bug", "Deathly Crypt Rune": "The Gravedigger",
                  "Fiery Crypt Rune": "Eldritch Dragon Lord", "Icy Crypt Rune": "Ice Horror",
                  "Necromantic Crypt Rune": "Bone Overlord"},
        "results": ["Crypt Bile", "Crypt Breaker", "Crypt Jaw", "Crypt Slicer", "Crypt Spine", "Crypt Splitter", "Crypt Strike"],
        "npc": "Dragon Ancestor Spirit (Draconia)",
    },
}


def set_of(item: str) -> str | None:
    k = item_key(item)
    return next((key for key, s in SETS.items() if any(item_key(i) == k for i in s["items"])), None)


def canonical_item(item: str) -> str:
    """Nome do item como no jogo, se for de um conjunto conhecido; senão o que foi digitado (espaços normalizados)."""
    k = item_key(item)
    for s in SETS.values():
        for i in s["items"] + s["results"]:
            if item_key(i) == k:
                return i
    return " ".join(item.split())


def shares(net: int, members: list[str], holder: str) -> list[dict]:
    """Divide `net` igual entre os membros; o que sobra da divisão inteira fica com quem guarda o dinheiro (holder).
    Devolve as transferências: holder -> cada outro membro."""
    if not members or net <= 0:
        return []
    each = net // len(members)
    return [{"payer": holder, "receiver": m, "amount": each, "command": f"transfer {each} to {m}"}
            for m in members if m.lower() != holder.lower() and each > 0]
