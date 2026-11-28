"""Confere na TibiaWiki em inglês (tibia.fandom.com) quais nomes do app têm página e grava artemis/web/fandom-pages.js.

Usa só a API pública, em lotes de 50 títulos e com pausa entre os pedidos. Como na lista da TibiaWiki BR,
confere a existência da página, não o conteúdo. Redirecionamento só vale quando muda apenas maiúsculas.

    .venv\\Scripts\\python tools\\check_fandom_titles.py
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "artemis" / "data"
WEB = ROOT / "artemis" / "web"
API = "https://tibia.fandom.com/api.php"
UA = {"User-Agent": "4rt3mi5-importer/1.0"}
SMALL = {"of", "the", "de", "da", "do"}


def wiki_title(name: str) -> str:
    """A mesma regra do wikiTitle() do site."""
    words = name.split(" ")
    return " ".join(w.lower() if i and w.lower() in SMALL else w[:1].upper() + w[1:] for i, w in enumerate(words))


def candidates() -> list[str]:
    """Todos os nomes que o app conhece: lista da wiki BR, bosses, criaturas, itens, NPCs e hunts."""
    load = lambda n: json.loads((DATA / n).read_text(encoding="utf-8"))  # noqa: E731
    br = (WEB / "wiki-pages.js").read_text(encoding="utf-8")
    names = json.loads("[" + re.search(r"const WIKI_TITLES = \[(.*?)\n\];", br, re.S).group(1) + "]")
    bosses, wiki = load("bosses.json"), load("tibiawiki.json")
    names += [b["name"] for b in bosses["bosses"].values()]
    names += [wiki_title(k) for k in bosses["creature_loot"]]
    names += [i[0] for i in wiki["items"]] + list(wiki["npcs"])
    names += [h[0] for h in load("hunts.json")["hunts"]]
    seen: dict[str, str] = {}
    for n in names:
        n = " ".join(n.split())
        if n and not re.search(r"[\[\]{}|#<>]", n):
            seen.setdefault(n, n)
    return sorted(seen)


def query(titles: list[str]) -> dict:
    url = API + "?" + urllib.parse.urlencode({"action": "query", "format": "json", "redirects": 1, "titles": "|".join(titles)})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as resp:
        return json.load(resp)["query"]


def existing(titles: list[str]) -> set[str]:
    q = query(titles)
    redirects = {r["from"]: r["to"] for r in q.get("redirects", [])}
    normalized = {r["from"]: r["to"] for r in q.get("normalized", [])}
    pages = {p["title"] for p in q.get("pages", {}).values() if "missing" not in p and "invalid" not in p and p.get("ns") == 0}
    out = set()
    for t in titles:
        asked = normalized.get(t, t)
        final = redirects.get(asked, asked)
        if final in pages and final.lower() == asked.lower():
            out.add(final)
    return out


def main() -> None:
    names = candidates()
    found: dict[str, str] = {}
    for i in range(0, len(names), 50):
        for title in sorted(existing(names[i:i + 50])):
            found.setdefault(title.lower(), title)
        time.sleep(1)
    titles = sorted(found.values())
    body = ",\n".join(json.dumps(t, ensure_ascii=False) for t in titles)
    (WEB / "fandom-pages.js").write_text(
        f"// 0.34.0: títulos de página confirmados no tibia.fandom.com em {date.today():%d/%m/%Y} (existência, não o conteúdo).\n"
        "// Só vira link o nome que está aqui. Gerado por tools/check_fandom_titles.py.\n"
        f"const FANDOM_TITLES = [\n{body}\n];\n", encoding="utf-8", newline="\n")
    print(f"nomes consultados: {len(names)}  com página: {len(titles)}")


if __name__ == "__main__":
    main()
