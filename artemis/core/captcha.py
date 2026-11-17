"""0.21.0: CAPTCHA próprio do 4rt3mi5 (sem script de fora, sem mudar a CSP).

É uma "prova de trabalho": o servidor sorteia um número secreto e manda só o resumo SHA-256 dele junto com um
sal. O navegador testa os números de 0 em diante até achar o que gera o mesmo resumo — leva alguns segundos
para uma pessoa (uma vez) e fica caro para um robô que quer mandar milhares de mensagens. O desafio vem
assinado (HMAC) com um segredo do servidor, então não dá para inventar um desafio fácil, e cada um vale uma vez
e por pouco tempo.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

MAX_NUMBER = 250_000      # o navegador testa, em média, metade disso (~0,5 s num PC, 1 a 4 s num celular)
TTL = 10 * 60             # o desafio vale 10 minutos
MIN_SECONDS = 0.3         # resposta mais rápida que isso não é de navegador (um PC rápido resolve em ~1 s)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sign(secret: bytes, challenge: str) -> str:
    return hmac.new(secret, challenge.encode("utf-8"), hashlib.sha256).hexdigest()


def issue(secret: bytes, now: float | None = None, max_number: int = MAX_NUMBER) -> dict:
    """Desafio novo. O sal carrega quando foi criado; nada disso precisa ficar guardado no servidor."""
    now = time.time() if now is None else now
    salt = f"{secrets.token_hex(12)}.{int(now * 1000)}"
    number = secrets.randbelow(max_number)
    challenge = _sha(salt + str(number))
    return {"algorithm": "SHA-256", "salt": salt, "challenge": challenge, "maxnumber": max_number,
            "signature": _sign(secret, challenge)}


class CaptchaError(ValueError):
    """Resposta inválida, vencida, rápida demais ou já usada."""


def verify(secret: bytes, answer: dict, used: dict, now: float | None = None) -> None:
    """Confere a resposta (salt, number, challenge, signature). `used` guarda os desafios já gastos."""
    now = time.time() if now is None else now
    try:
        salt, challenge, signature = str(answer["salt"]), str(answer["challenge"]), str(answer["signature"])
        number = int(answer["number"])
        issued = int(salt.rsplit(".", 1)[1]) / 1000
    except (KeyError, TypeError, ValueError, IndexError):
        raise CaptchaError("formato") from None
    if not hmac.compare_digest(_sign(secret, challenge), signature):
        raise CaptchaError("assinatura")
    if not 0 <= number < MAX_NUMBER * 4 or _sha(salt + str(number)) != challenge:
        raise CaptchaError("resposta")
    if now - issued > TTL:
        raise CaptchaError("vencido")
    if now - issued < MIN_SECONDS:
        raise CaptchaError("rápido demais")
    for k in [k for k, t in used.items() if now - t > TTL]:  # esquece os vencidos
        used.pop(k, None)
    if challenge in used:
        raise CaptchaError("já usado")
    used[challenge] = now
