"""0.26.0: varredura diária dos highscores de todos os mundos (XP, skills e outras categorias).

Para cada categoria e mundo lê as 20 páginas (1000 jogadores). Guarda só os personagens que interessam
(cadastrados no site e os já citados em party session analyzer), compara com o dia anterior e registra:
- mudanças de valor (subiu = verde, desceu = vermelho);
- trocas de mundo (contador world_changes +1).
Quem não aparece no top 1000 de uma categoria mantém o último valor conhecido.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

PAGES = 20          # 20 páginas x 50 = top 1000
WORKERS = 6         # consultas em paralelo (medido: ~276 ms cada)
TOP = 1000          # tamanho do ranking geral por métrica
PAGE_SIZE = 50      # jogadores por página do highscore
PER_WORLD = 200     # 0.30.0: quantos de cada mundo ficam guardados para o filtro por mundo
_LIMITE_TRIM = 3000 # acima disso o acumulado é aparado para o top (economiza memória)


def _guarda(tops: dict, metrica: str, item: tuple) -> None:
    lista = tops.setdefault(metrica, [])
    lista.append(item)
    if len(lista) > _LIMITE_TRIM:
        lista.sort(key=lambda t: (-(t[0] or 0), t[1].lower()))
        del lista[TOP:]


def run_scan(store, *, day: str, tracked: dict[str, str], fetch_page, fetch_worlds, key_fn,
             categories: tuple[str, ...], workers: int = WORKERS, pages: int = PAGES) -> dict:
    """tracked: {name_key: nome}. Devolve os tempos e totais da execução (também gravados em scan_runs)."""
    t0 = time.monotonic()
    first_load = store.rank_count() == 0
    errors = 0
    requests = 0
    try:
        worlds = fetch_worlds()
    except Exception:
        store.scan_run_add(started_at=day, seconds=time.monotonic() - t0, first_load=first_load, requests=0,
                           errors=1, worlds=0, tracked=len(tracked), matched=0, changes=0, world_changes=0, ok=False,
                           note="falha ao listar os mundos")
        return {"ok": False, "note": "falha ao listar os mundos"}

    tarefas = [(w, c, p) for w in worlds for c in categories for p in range(1, pages + 1)]
    found: dict[str, dict] = {}   # name_key -> {name, world, level, vocation, values}
    tops: dict[str, list] = {}    # métrica -> [(valor, nome, mundo, level, vocação)] (aparado no caminho)

    wtops: dict[tuple[str, str], dict[int, tuple]] = {}  # 0.30.0: (métrica, mundo) -> {posição no mundo: item}

    def trabalho(t):
        w, c, p = t
        return t, fetch_page(w, c, p)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = [pool.submit(trabalho, t) for t in tarefas]
        for f in as_completed(futuros):
            requests += 1
            try:
                (w, c, _p), rows = f.result()
            except Exception:
                errors += 1
                continue
            for i, r in enumerate(rows):
                # 0.30.0: top de cada mundo (só as primeiras páginas: o suficiente para o filtro por mundo)
                pos = (_p - 1) * PAGE_SIZE + i + 1
                if pos <= PER_WORLD:
                    metrica = "level" if c == "experience" else c
                    valor = r.get("level") if c == "experience" else r.get("value")
                    if valor is not None:
                        wtops.setdefault((metrica, w), {})[pos] = (valor, r["name"], r.get("level"), r.get("vocation"))
                # 0.26.1: top global por métrica (todos os jogadores, não só os acompanhados)
                item = (r.get("value"), r["name"], w, r.get("level"), r.get("vocation"))
                if item[0] is not None and c != "experience":  # XP total não é métrica de ranking (ver 0.26.2)
                    _guarda(tops, c, item)
                if c == "experience":
                    _guarda(tops, "level", (r.get("level"), r["name"], w, r.get("level"), r.get("vocation")))
                nk = key_fn(r.get("name", ""))
                if nk not in tracked:
                    continue
                reg = found.setdefault(nk, {"name": r["name"], "world": w, "level": r.get("level"),
                                            "vocation": r.get("vocation"), "values": {}})
                reg["world"] = w  # o mundo em que apareceu por último nesta varredura
                reg["values"][c] = r.get("value")
                if c == "experience" or reg.get("level") is None:
                    reg["level"] = r.get("level", reg.get("level"))

    store.rank_top_replace(day, {m: sorted(v, key=lambda t: (-(t[0] or 0), t[1].lower()))[:TOP]
                                 for m, v in tops.items()})
    store.rank_world_top_replace(day, [(m, w, pos, *item) for (m, w), d in wtops.items() for pos, item in sorted(d.items())])

    updates, changes, world_changes = [], [], 0
    previos = store.rank_load_many(list(found))
    for nk, atual in found.items():
        anterior = previos.get(nk)
        trocas = anterior["world_changes"] if anterior else 0
        valores_antigos = anterior["values"] if anterior else {}
        if anterior and anterior["world"] and anterior["world"] != atual["world"]:
            trocas += 1
            world_changes += 1
            changes.append({"day": day, "name_key": nk, "name": atual["name"], "category": "world",
                            "old_value": None, "new_value": None, "delta": None, "kind": "world",
                            "world_from": anterior["world"], "world_to": atual["world"]})
        for c, novo in atual["values"].items():
            antigo = valores_antigos.get(c)
            if antigo is None or novo is None or antigo == novo:
                continue
            delta = novo - antigo
            changes.append({"day": day, "name_key": nk, "name": atual["name"], "category": c,
                            "old_value": antigo, "new_value": novo, "delta": delta,
                            "kind": "up" if delta > 0 else "down", "world_from": None, "world_to": None})
        merged = dict(valores_antigos)
        merged.update({c: v for c, v in atual["values"].items() if v is not None})
        updates.append({"name_key": nk, "name": atual["name"], "world": atual["world"], "level": atual["level"],
                        "vocation": atual["vocation"], "values": merged, "world_changes": trocas})

    store.rank_apply(day=day, updates=updates, changes=changes)
    xp_hoje = [(u["name"], u["values"]["experience"]) for u in updates if u["values"].get("experience") is not None]
    for nome, xp in xp_hoje:
        store.xp_save(nome, day, xp)  # mantém o XP 30/90 dias funcionando com o mesmo dado

    seconds = time.monotonic() - t0
    store.scan_run_add(started_at=day, seconds=seconds, first_load=first_load, requests=requests, errors=errors,
                       worlds=len(worlds), tracked=len(tracked), matched=len(found), changes=len(changes) - world_changes,
                       world_changes=world_changes, ok=True, note="")
    return {"ok": True, "seconds": round(seconds, 1), "requests": requests, "errors": errors, "worlds": len(worlds),
            "matched": len(found), "changes": len(changes) - world_changes, "world_changes": world_changes,
            "first_load": first_load}
