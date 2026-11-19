"""0.24.0: 👥 Parties registradas e 🗃️ cofre da party.

Party = formação fixa (titulares + substitutos) para hunt, bosses ou os dois. Serve para:
  - marcar sozinho quem foi substituto num lootsplit (sem ninguém precisar informar toda vez);
  - dividir as vendas do cofre entre os titulares.

Cofre da party: estoque de itens com a origem de cada um (a "sacolinha"):
  - drop    🟡 sacolinha amarela, limpa  → vale entre 0 e o preço médio praticado (o valor do cofre);
  - service 🟢 sacolinha verde com $     → a runa garantida do serviçado: a party compra dele pela METADE do valor da
                                           runa, e cada titular paga a parte dele (metade ÷ titulares). Ex.: runa de
                                           75kk → 37,5kk ÷ 5 = 7,5kk de cada um para o serviçado. Vale o que foi pago;
  - buy     🔴 sacolinha vermelha com $  → vale o que foi pago (e quem comprou é reembolsado na venda).

Craft (ex.: Crypt Runes → arma Crypt): a faixa de preço do item craftado é a soma das faixas dos itens usados.
Exemplo: Ancient (drop, 12kk) + Icy (compra 12kk) + Fiery (drop, 14kk) + Deathly (compra 40kk) + Necromantic (drop, 75kk)
→ entre 52kk (0+12+0+40+0) e 153kk (12+12+14+40+75).
"""
from __future__ import annotations

from .rotations import market_fee

ORIGINS = ("drop", "service", "buy")
KINDS = ("hunt", "boss", "both")
ROLES = ("main", "sub")
# rotação da party -> conjunto que ela crafta (rotations.SETS)
ROTATION_SETS = {"graveborn": "crypt"}


def unit_range(origin: str, cost_each: int | None, price: int | None) -> tuple[int, int]:
    """Faixa de valor de UMA unidade: (mínimo, máximo)."""
    price = int(price or 0)
    if origin == "buy":
        c = int(cost_each or 0)
        return c, c
    if origin == "service" and cost_each is not None:
        c = int(cost_each)
        return c, c
    return 0, price  # drop (ou service sem valor): entre 0 e o preço médio praticado


def craft_range(used: list[dict]) -> dict:
    """used = [{"origin", "cost_each", "price"}] (uma unidade de cada) -> {"min", "max", "cost"}.
    cost = o que saiu do bolso de alguém (compras), a ser reembolsado quando o item craftado for vendido."""
    lo = hi = cost = 0
    for u in used:
        a, b = unit_range(u["origin"], u.get("cost_each"), u.get("price"))
        lo, hi = lo + a, hi + b
        if u["origin"] == "buy":
            cost += int(u.get("cost_each") or 0)
    return {"min": lo, "max": hi, "cost": cost}


def sale(total: int, with_fee: bool, when: str | None, mains: list[str], seller: str,
         refunds: list[tuple[str, int]] | None = None) -> dict:
    """Venda de um item do cofre: taxa do Market, reembolso de quem comprou itens, lucro e quem paga quem.
    O lucro é dividido igual entre os titulares; quem vendeu (seller) está com o dinheiro e repassa.
    refunds = [(quem comprou, quanto pagou)] — volta para quem comprou antes da divisão."""
    total = int(total or 0)
    fee = market_fee(total, when) if with_fee and total > 0 else 0
    refund_total = sum(c for _, c in (refunds or []))
    net = total - fee - refund_total
    members = mains or [seller]
    each = net // len(members) if net > 0 else 0
    transfers: list[dict] = []
    owed: dict[str, int] = {}
    for who, c in refunds or []:
        if c > 0:
            owed[who] = owed.get(who, 0) + c
    for m in members:
        if each > 0:
            owed[m] = owed.get(m, 0) + each
    for who, amount in owed.items():
        if who.lower() != seller.lower() and amount > 0:
            transfers.append({"payer": seller, "receiver": who, "amount": amount, "command": f"transfer {amount} to {who}"})
    return {"total": total, "fee": fee, "refund": refund_total, "net": net, "each": each, "transfers": transfers}


def service_half(rune_value: int) -> int:
    """Quanto a party paga ao serviçado por UMA runa garantida: metade do valor."""
    return int(rune_value or 0) // 2


def service_shares(half_each: int, qty: int, payers: list[str], client: str) -> dict:
    """Cada titular paga a parte dele ao serviçado: (metade × qtd) ÷ titulares (quem é o serviçado não paga a si mesmo)."""
    total = int(half_each or 0) * int(qty or 1)
    each = total // len(payers) if payers else 0
    transfers = [{"payer": p, "receiver": client, "amount": each, "command": f"transfer {each} to {client}"}
                 for p in payers if each > 0 and p.lower() != client.lower()]
    return {"total": total, "each": each, "transfers": transfers}


def subs_from_parties(players: list[str], parties: list[dict], kind: str) -> dict[str, str | None]:
    """🔁 Substitutos pelas parties registradas.

    Uma party "bate" com o lootsplit quando pelo menos metade dos titulares dela estão nele (e o tipo combina).
    Na party que mais bate: quem está como substituto, ou quem nem é da party, é substituto. Se faltou exatamente
    um titular, o substituto está "no lugar de" ele. parties = [{"kind", "members": [{"name", "role"}]}]."""
    keys = {p.lower(): p for p in players}
    best, best_hits = None, 0
    for party in parties:
        if party["kind"] not in (kind, "both"):
            continue
        mains = [m["name"] for m in party["members"] if m["role"] == "main"]
        hits = sum(1 for m in mains if m.lower() in keys)
        if mains and hits * 2 >= len(mains) and hits > best_hits:
            best, best_hits = party, hits
    if best is None:
        return {}
    roles = {m["name"].lower(): m["role"] for m in best["members"]}
    missing = [m["name"] for m in best["members"] if m["role"] == "main" and m["name"].lower() not in keys]
    in_place = missing[0] if len(missing) == 1 else None
    return {name: in_place for k, name in keys.items() if roles.get(k) != "main"}
