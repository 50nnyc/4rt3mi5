"""Divisão do loot: todos terminam com o mesmo profit (balance total / nº de jogadores).

Mesma lógica do TibiaPal / TibiaMaps: quem ficou com balance acima da média
transfere a diferença para quem ficou abaixo, com o menor número de transferências
possível (pareando o maior pagador com o maior recebedor).
"""
from __future__ import annotations

from dataclasses import dataclass

from .parser import HuntSession


@dataclass
class Transfer:
    payer: str
    receiver: str
    amount: int

    @property
    def bank_command(self) -> str:
        """Texto para falar com o NPC do banco."""
        return f"transfer {self.amount} to {self.receiver}"


def split_session(session: HuntSession) -> tuple[int, list[Transfer], dict[str, int]]:
    """Retorna (profit_por_jogador, transferências, diff por jogador).

    diff > 0: jogador tem que pagar esse valor; diff < 0: tem que receber.
    """
    players = session.players
    total = sum(p.balance for p in players)
    share = total // len(players)  # arredonda para baixo; o resto (< nº jogadores) fica com quem paga

    diff = {p.name: p.balance - share for p in players}
    payers = sorted(([n, d] for n, d in diff.items() if d > 0), key=lambda x: -x[1])
    receivers = sorted(([n, -d] for n, d in diff.items() if d < 0), key=lambda x: -x[1])

    transfers: list[Transfer] = []
    i = j = 0
    while i < len(payers) and j < len(receivers):
        amount = min(payers[i][1], receivers[j][1])
        if amount > 0:
            transfers.append(Transfer(payers[i][0], receivers[j][0], amount))
        payers[i][1] -= amount
        receivers[j][1] -= amount
        if payers[i][1] == 0:
            i += 1
        if receivers[j][1] == 0:
            j += 1
    return share, transfers, diff
