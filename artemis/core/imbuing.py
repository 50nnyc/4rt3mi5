"""0.32.0: imbuements e gastos invisíveis (Player Hardcore).

Tudo aqui é cálculo puro (sem banco): catálogo dos imbuements, regras de quem aceita o quê,
o melhor jeito de comprar cada imbuement (market x gold token) e o custo por hora de uso.

Regras (tabelas e explicações do dono do projeto):
- Cada imbuement dura 20 horas de uso e custa a taxa do shrine mais os materiais (ou os tokens).
- Os níveis são acumulativos: Intricate leva os itens do Basic e do Intricate; Powerful leva os três.
- Só Strike, Vampirism e Void podem ser trocados por gold token no NPC, por prefixo:
  2 tokens cobrem o item 1, 4 cobrem os itens 1 e 2, 6 cobrem os três. Dá para cobrir os primeiros
  níveis com token e comprar o resto no market.
"""
from __future__ import annotations

HOURS = 20  # duração de um imbuement, em horas de uso
TIERS = ("Basic", "Intricate", "Powerful")
SHRINE_FEE = {1: 7_500, 2: 60_000, 3: 250_000}  # taxa do shrine por nível (vale para qualquer forma de pagar)
TOKEN_ELIGIBLE = {"strike", "vampirism", "void"}  # os únicos com a troca por gold token (2 por nível)
TOKENS_PER_TIER = 2

# preço padrão inicial (média do mundo Celebra em 24/11/2026; depois vira a média dos jogadores)
DEFAULT_TOKEN_PRICES = {"gold token": 45_700, "silver token": 45_848}

# chave -> (nome, categoria, [(qtd, item) do Basic, Intricate, Powerful])
CATALOG: dict[str, dict] = {}


def _add(key: str, name: str, cat: str, mats: list[tuple[int, str]], note: str = "") -> None:
    CATALOG[key] = {"key": key, "name": name, "category": cat, "materials": [{"qty": q, "item": i} for q, i in mats],
                    "token": key in TOKEN_ELIGIBLE, "note": note}


# Skillboost
_add("bash", "Bash (Skillboost de Clava)", "skill", [(20, "Cyclops Toe"), (15, "Ogre Nose Ring"), (10, "Warmaster's Wristguards")])
_add("blockade", "Blockade (Skillboost de Escudo)", "skill", [(20, "Piece of Scarab Shell"), (25, "Brimstone Shell"), (25, "Frazzle Skin")])
_add("chop", "Chop (Skillboost de Machado)", "skill", [(20, "Orc Tooth"), (25, "Battle Stone"), (20, "Moohtant Horn")])
_add("epiphany", "Epiphany (Skillboost de Nível Mágico)", "skill", [(25, "Elvish Talisman"), (15, "Broken Shamanic Staff"), (15, "Strand of Medusa Hair")])
_add("precision", "Precision (Skillboost de Distância)", "skill", [(25, "Elven Scouting Glass"), (20, "Elven Hoof"), (10, "Metal Spike")])
_add("punch", "Punch (Skillboost de Punhos)", "skill", [(25, "Tarantula Egg"), (20, "Mantassin Tail"), (15, "Gold-Brocaded Cloth")])
_add("slash", "Slash (Skillboost de Espada)", "skill", [(25, "Lion's Mane"), (25, "Mooh'tah Shell"), (5, "War Crystal")])
# Dano elemental
_add("electrify", "Electrify (Dano de Energia)", "elemental", [(25, "Rorc Feather"), (5, "Peacock Feather Fan"), (1, "Energy Vein")])
_add("frost", "Frost (Dano de Gelo)", "elemental", [(25, "Frosty Heart"), (10, "Seacrest Hair"), (5, "Polar Bear Paw")])
_add("reap", "Reap (Dano de Morte)", "elemental", [(25, "Pile of Grave Earth"), (20, "Demonic Skeletal Hand"), (5, "Petrified Scream")])
_add("scorch", "Scorch (Dano de Fogo)", "elemental", [(25, "Fiery Heart"), (5, "Green Dragon Scale"), (5, "Demon Horn")])
_add("venom", "Venom (Dano de Terra)", "elemental", [(25, "Swamp Grass"), (20, "Poisonous Slime"), (2, "Slime Heart")])
# Proteção elemental
_add("cloud_fabric", "Cloud Fabric (Proteção de Energia)", "protection", [(20, "Wyvern Talisman"), (15, "Crawler Head Plating"), (10, "Wyrm Scale")])
_add("demon_presence", "Demon Presence (Proteção de Sagrado)", "protection", [(25, "Cultish Robe"), (25, "Cultish Mask"), (20, "Hellspawn Tail")])
_add("dragon_hide", "Dragon Hide (Proteção de Fogo)", "protection", [(20, "Green Dragon Leather"), (10, "Blazing Bone"), (5, "Draken Sulphur")])
_add("lich_shroud", "Lich Shroud (Proteção de Morte)", "protection", [(25, "Flask of Embalming Fluid"), (20, "Gloom Wolf Fur"), (5, "Mystical Hourglass")])
_add("quara_scale", "Quara Scale (Proteção de Gelo)", "protection", [(25, "Winter Wolf Fur"), (15, "Thick Fur"), (10, "Deepling Warts")])
_add("snake_skin", "Snake Skin (Proteção de Terra)", "protection", [(25, "Piece of Swampling Wood"), (20, "Snake Skin"), (10, "Brimstone Fangs")])
# Suporte
_add("featherweight", "Featherweight (Aumento de Capacidade)", "support", [(20, "Fairy Wings"), (10, "Little Bowl of Myrrh"), (5, "Goosebump Leather")])
_add("strike", "Strike (Dano Crítico)", "support", [(20, "Protective Charm"), (25, "Sabretooth"), (5, "Vexclaw Talon")])
_add("swiftness", "Swiftness (Skillboost de Velocidade)", "support", [(15, "Damselfly Wing"), (25, "Compass"), (20, "Waspoid Wing")])
_add("vampirism", "Vampirism (Roubo de Vida)", "support", [(25, "Vampire Teeth"), (15, "Bloody Pincers"), (5, "Piece of Dead Brain")])
_add("vibrancy", "Vibrancy (Remoção de Paralisia)", "support", [(20, "Wereboar Hooves"), (15, "Crystallized Anger"), (5, "Quill")])
_add("void", "Void (Roubo de Mana)", "support", [(25, "Rope Belt"), (25, "Silencer Claws"), (5, "Some Grimeleech Wings")])

PROTECTIONS = [k for k, v in CATALOG.items() if v["category"] == "protection"]
ELEMENTAL = [k for k, v in CATALOG.items() if v["category"] == "elemental"]
SKILLS = [k for k, v in CATALOG.items() if v["category"] == "skill"]

# preços iniciais dos itens (média do Celebra em 24/11/2026). Os que faltam o jogador preenche.
DEFAULT_ITEM_PRICES = {
    "Protective Charm": 3595, "Sabretooth": 7000, "Vexclaw Talon": 1994, "Vampire Teeth": 492, "Bloody Pincers": 16896,
    "Piece of Dead Brain": 29996, "Rope Belt": 3500, "Silencer Claws": 3883, "Some Grimeleech Wings": 2496,
    "Elven Scouting Glass": 380, "Elven Hoof": 18890, "Metal Spike": 435, "Elvish Talisman": 6300,
    "Broken Shamanic Staff": 19799, "Strand of Medusa Hair": 5990, "Fairy Wings": 449, "Little Bowl of Myrrh": 6495,
    "Goosebump Leather": 1180, "Wereboar Hooves": 150, "Crystallized Anger": 400, "Quill": 1050,
    "Wyvern Talisman": 18000, "Crawler Head Plating": 4698, "Wyrm Scale": 379, "Cultish Robe": 250, "Cultish Mask": 25500,
    "Hellspawn Tail": 400, "Green Dragon Leather": 17749, "Blazing Bone": 788, "Draken Sulphur": 1300,
    "Flask of Embalming Fluid": 4975, "Gloom Wolf Fur": 28499, "Mystical Hourglass": 500, "Winter Wolf Fur": 4000,
    "Thick Fur": 800, "Deepling Warts": 199, "Piece of Swampling Wood": 6947, "Snake Skin": 2490, "Brimstone Fangs": 22775,
}

# Anéis e amuletos recarregáveis com silver token: (nome, tipo, minutos de uso por recarga, silver tokens por recarga)
ACCESSORIES: dict[str, dict] = {}
for _k, _n, _t, _m, _s in [
    ("flamingo_valor", "Enchanted Flamingo Amulet of Valor", "amulet", 180, 5),
    ("turtle", "Enchanted Turtle Amulet", "amulet", 120, 2),
    ("flamingo_destruction", "Enchanted Flamingo Amulet of Destruction", "amulet", 180, 5),
    ("flamingo_nature", "Enchanted Flamingo Amulet of Nature", "amulet", 180, 5),
    ("merudri", "Enchanted Merudri Brooch", "amulet", 120, 5),
    ("swan_balance", "Enchanted Swan Amulet of Balance", "amulet", 180, 5),
    ("theurgic", "Enchanted Theurgic Amulet", "amulet", 120, 2),
    ("pendulet", "Enchanted Pendulet", "amulet", 120, 2),
    ("sleep_shawl", "Enchanted Sleep Shawl", "amulet", 60, 2),
    ("flamingo_precision", "Enchanted Flamingo Amulet of Precision", "amulet", 180, 5),
    ("ethereal", "Charged Ethereal Ring", "ring", 180, 5),
    ("arcanomancer", "Charged Arcanomancer Sigil", "ring", 180, 5),
    ("arboreal", "Charged Arboreal Ring", "ring", 180, 5),
    ("alicorn", "Charged Alicorn Ring", "ring", 180, 5),
    ("spiritthorn", "Charged Spiritthorn Ring", "ring", 180, 5),
]:
    ACCESSORIES[_k] = {"key": _k, "name": _n, "kind": _t, "minutes": _m, "silver_tokens": _s}

# ------------------------------------------------------------------ tipos de equipamento e o que aceitam
# tipo -> nome
GEAR_KINDS = {
    "sword": "Espada", "axe": "Machado", "club": "Clava", "distance": "Arco / Besta", "fist": "Arma de monk",
    "rod": "Rod", "wand": "Wand",
    "helmet": "Elmo (knight, paladin, monk)", "helmet_mage": "Elmo de mage (druid, sorcerer)",
    "armor": "Armadura", "shield": "Escudo", "boots": "Bota", "backpack": "Mochila",
    "ring": "Anel", "amulet": "Amuleto",
}
WEAPON_SKILL = {"sword": "slash", "axe": "chop", "club": "bash", "distance": "precision", "fist": "punch",
                "rod": "epiphany", "wand": "epiphany"}
MAX_SLOTS = 3


def allowed_imbuements(kind: str) -> dict[str, int]:
    """imbuement -> nível máximo que o tipo de equipamento aceita (vazio se não aceita nenhum)."""
    if kind in WEAPON_SKILL:
        out = {"strike": 3, "vampirism": 3, "void": 3, WEAPON_SKILL[kind]: 3}
        out.update({k: 3 for k in ELEMENTAL})
        return out
    if kind == "helmet":
        out = {k: 3 for k in SKILLS if k != "epiphany"}
        out.update(epiphany=2, void=3)  # Magic Level só até o Intricate nos elmos que não são de mage
        return out
    if kind == "helmet_mage":
        return {"epiphany": 3, "void": 3}
    if kind == "armor":
        out = {k: 3 for k in PROTECTIONS}
        out["vampirism"] = 3
        return out
    if kind == "shield":
        return {k: 3 for k in PROTECTIONS}
    if kind == "boots":
        return {"swiftness": 3, "vibrancy": 3}
    if kind == "backpack":
        return {"featherweight": 3}
    return {}


def check_imbue(kind: str, slots: int, native: list[str], current: list[str], imbuement: str, tier: int) -> str | None:
    """Mensagem de erro se não dá para pôr `imbuement` nesse item; None se pode.
    `native`: imbuements que o item já traz de fábrica (ex.: "life_leech" não existe aqui; use a chave do
    imbuement que ele bloqueia, como "vampirism" ou "quara_scale"). `current`: os que já estão no item."""
    if imbuement not in CATALOG:
        return "Imbuement desconhecido."
    if tier not in (1, 2, 3):
        return "Nível inválido (1 a 3)."
    allowed = allowed_imbuements(kind)
    if imbuement not in allowed:
        return "Esse tipo de item não aceita esse imbuement."
    if tier > allowed[imbuement]:
        return "Esse tipo de item aceita esse imbuement só em um nível menor."
    if imbuement in native:
        return "Esse item já traz esse efeito e não aceita o imbuement."
    if imbuement in current:
        return "Esse imbuement já está no item (não repete)."
    if len(current) >= max(1, min(slots, MAX_SLOTS)):
        return "O item não tem mais slots livres."
    return None


# ------------------------------------------------------------------ preço: market x gold token
def material_costs(imbuement: str, prices: dict[str, int]) -> list[int | None]:
    """Custo (qtd x preço) dos itens de cada nível. None quando o jogador ainda não informou o preço."""
    out = []
    for m in CATALOG[imbuement]["materials"]:
        p = prices.get(m["item"])
        out.append(m["qty"] * p if p else None)
    return out


def best_plan(imbuement: str, tier: int, prices: dict[str, int], token_price: int | None) -> dict:
    """O jeito mais barato de montar o imbuement até `tier`.

    `prices`: preço de cada item do market. `token_price`: gold token (None se não informado).
    Testa cobrir 0, 1, ... `tier` níveis com token (2 tokens por nível, por prefixo) e comprar o
    resto no market; fica com o menor custo. Devolve também o "tudo no market" e o "tudo token" para mostrar a economia.
    """
    cat = CATALOG[imbuement]
    costs = material_costs(imbuement, prices)[:tier]
    fee = SHRINE_FEE[tier]
    options = []
    can_token = cat["token"] and bool(token_price)
    for k in range(0, tier + 1):
        if k and not can_token:
            break
        rest = costs[k:]
        if any(c is None for c in rest):
            continue  # falta preço de algum item que teria que ser comprado
        options.append({"token_levels": k, "tokens": TOKENS_PER_TIER * k,
                        "cost": TOKENS_PER_TIER * k * (token_price or 0) + sum(rest)})
    out = {"imbuement": imbuement, "tier": tier, "fee": fee, "token_eligible": cat["token"], "options": options,
           "missing": sorted({m["item"] for m, c in zip(cat["materials"][:tier], costs) if c is None})}
    if not options:
        out.update(best=None, total=None, saved=0)
        return out
    best = min(options, key=lambda o: (o["cost"], o["token_levels"]))
    worst = max(options, key=lambda o: o["cost"])
    out.update(best=best, total=best["cost"] + fee, saved=worst["cost"] - best["cost"])
    out["advice"] = advice(imbuement, tier, best)
    return out


def advice(imbuement: str, tier: int, best: dict) -> str:
    name = CATALOG[imbuement]["name"].split(" (")[0]
    k = best["token_levels"]
    if k == 0:
        return f"{name}: compre todos os itens no market."
    if k == tier:
        return f"{name}: troque por {best['tokens']} gold tokens no NPC."
    return (f"{name}: troque {best['tokens']} gold tokens (níveis 1 a {k}) e compre no market só os itens dos "
            f"níveis {k + 1} a {tier}.")


def hourly(total_cost: int, hours_total: float = HOURS) -> float:
    return total_cost / hours_total if hours_total else 0.0


def use_cost(total_cost: int, hours: float, hours_total: float = HOURS) -> int:
    """Quanto custou usar o item por `hours` horas (proporcional às 20 h)."""
    return round(total_cost * max(0.0, hours) / hours_total) if hours_total else 0


def accessory_charge_cost(key: str, silver_price: int) -> int:
    return ACCESSORIES[key]["silver_tokens"] * silver_price


def accessory_hours(key: str) -> float:
    return ACCESSORIES[key]["minutes"] / 60


def average_price(values: list[int], limit: float = 1.5) -> int | None:
    """Média dos preços informados pelos jogadores. Valor acima de 150% da média é descartado
    (proteção contra número falso ou exagerado) e a média é refeita sem ele."""
    vals = [int(v) for v in values if v and v > 0]
    if not vals:
        return None
    mean = sum(vals) / len(vals)
    kept = [v for v in vals if v <= mean * limit] or vals
    return round(sum(kept) / len(kept))
