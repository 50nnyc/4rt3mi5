"""Importa a lista de bosses do Tibia (nome, classe do Bosstiary e loot) da TibiaWiki (tibia.fandom.com).

Gera artemis/data/bosses.json, usado pela 👑 Rotação de bosses para:
  - reconhecer um boss nas criaturas mortas de uma sessão (inclusive no Hunt Session Stacker);
  - estimar o loot que veio do boss numa hunt comum (itens da tabela do boss que as outras
    criaturas mortas não dropam).

Também guarda, para as criaturas comuns, só os itens que aparecem em loot de algum boss
(é o que basta para separar o loot do boss do loot da hunt).

Uso: .venv\\Scripts\\python tools/import_bosses.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://tibia.fandom.com/api.php"
OUT = Path(__file__).resolve().parent.parent / "artemis" / "data" / "bosses.json"
UA = {"User-Agent": "4rt3mi5-importer/1.0"}

_FIELD = re.compile(r"^\|\s*(\w+)\s*=\s*(.*)$")
_LOOT_ITEM = re.compile(r"\{\{Loot Item\|([^}]*)\}\}")
_AMOUNT = re.compile(r"[\d?+\-–]+")
_RARITY = {"always", "common", "uncommon", "semi-rare", "rare", "very rare", "extremely rare", "never", "?"}


def _get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    for tries in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except OSError:
            time.sleep(2 + tries * 3)
    raise SystemExit(f"Falha ao consultar {url}")


def category(cat: str) -> list[str]:
    out, cont = [], {}
    while True:
        d = _get({"action": "query", "list": "categorymembers", "cmtitle": cat, "cmlimit": 500,
                  "cmnamespace": 0, **cont})
        out += [m["title"] for m in d["query"]["categorymembers"]]
        if "continue" not in d:
            return out
        cont = {"cmcontinue": d["continue"]["cmcontinue"]}


def wikitexts(titles: list[str]):
    for i in range(0, len(titles), 50):
        d = _get({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                  "titles": "|".join(titles[i:i + 50])})
        for p in d["query"]["pages"]:
            revs = p.get("revisions")
            if revs:
                yield p["title"], revs[0]["slots"]["main"]["content"]
        print(f"  {min(i + 50, len(titles))}/{len(titles)}", file=sys.stderr)


def infobox(text: str) -> dict | None:
    if "{{Infobox Creature" not in text:
        return None
    fields: dict[str, str] = {}
    for line in text.split("\n"):
        if m := _FIELD.match(line.strip()):
            fields[m.group(1).lower()] = m.group(2).strip()
    loot_part = text.split("| loot", 1)[1] if "| loot" in text else ""
    loot_part = loot_part.split("\n| ", 1)[0]
    loot = set()
    for m in _LOOT_ITEM.finditer(loot_part):  # {{Loot Item|[quantidade|]Nome[|raridade]}}
        parts = [p.strip() for p in m.group(1).split("|")]
        name = parts[1] if len(parts) > 1 and _AMOUNT.fullmatch(parts[0]) else parts[0]
        if name and name.lower() not in _RARITY:
            loot.add(" ".join(name.split()).lower())
    loot = sorted(loot)
    fields["_loot"] = loot
    return fields


def _int(v: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", (v or "").split("<")[0])
    return int(digits) if digits else None


def main() -> None:
    print("Lendo categorias…", file=sys.stderr)
    boss_titles = category("Category:Bosses")
    creature_titles = sorted(set(category("Category:Creatures")) - set(boss_titles))
    bosses: dict[str, dict] = {}
    for title, text in wikitexts(boss_titles):
        f = infobox(text)
        if not f or f.get("isboss", "").lower() != "yes":
            continue
        name = (f.get("actualname") or f.get("name") or title).strip()
        bosses[name.lower()] = {"name": name, "class": (f.get("bosstiaryclass") or "").strip().title() or None,
                                "hp": _int(f.get("hp")), "exp": _int(f.get("exp")), "loot": f["_loot"]}
    boss_items = {it for b in bosses.values() for it in b["loot"]}
    creatures: dict[str, list[str]] = {}
    for title, text in wikitexts(creature_titles):
        f = infobox(text)
        if not f or f.get("isboss", "").lower() == "yes":
            continue
        shared = [it for it in f["_loot"] if it in boss_items]
        if shared:
            creatures[(f.get("actualname") or f.get("name") or title).strip().lower()] = shared
    OUT.write_text(json.dumps({"source": "https://tibia.fandom.com (CC BY-SA)",
                               "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "bosses": dict(sorted(bosses.items())), "creature_loot": dict(sorted(creatures.items()))},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(bosses)} bosses, {len(creatures)} criaturas comuns -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
