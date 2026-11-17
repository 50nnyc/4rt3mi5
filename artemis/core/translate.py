"""Tradução automática (DeepL) das notícias, do News Archive e do calendário do Tibia. Só usa a stdlib.

O texto original é em inglês. Cada texto é traduzido uma vez por idioma e o servidor guarda o resultado,
então a mesma notícia nunca é traduzida duas vezes. Sem chave configurada, tudo continua em inglês.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

# idioma do app -> idioma do DeepL (inglês é o original: não traduz)
TARGETS = {"pt-BR": "PT-BR", "es": "ES", "ja": "JA", "de": "DE", "pl": "PL", "fr": "FR", "ru": "RU"}
BATCH = 40                 # textos por chamada
BATCH_CHARS = 60_000       # e no máximo isso de caracteres por chamada


class TranslateError(RuntimeError):
    """Serviço fora do ar, chave inválida ou cota do mês acabou."""


def endpoint(key: str) -> str:
    # chave do plano grátis termina em ":fx" e usa outro endereço
    return "https://api-free.deepl.com/v2/translate" if key.endswith(":fx") else "https://api.deepl.com/v2/translate"


def usage(key: str, timeout: float = 10) -> tuple[int, int]:
    """(caracteres usados no mês, limite do plano), direto do DeepL. Não gasta cota."""
    url = endpoint(key).rsplit("/", 1)[0] + "/usage"
    req = urllib.request.Request(url, headers={"Authorization": f"DeepL-Auth-Key {key}", "User-Agent": "4rt3mi5"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        return int(data.get("character_count") or 0), int(data.get("character_limit") or 0)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        raise TranslateError(f"Não consegui consultar o uso da tradução: {e}") from e


def _call(key: str, texts: list[str], target: str, html: bool, timeout: float) -> list[str]:
    body = {"text": texts, "target_lang": target, "source_lang": "EN"}
    if html:
        body["tag_handling"] = "html"
    req = urllib.request.Request(endpoint(key), data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"DeepL-Auth-Key {key}", "Content-Type": "application/json",
                                          "User-Agent": "4rt3mi5"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise TranslateError("Cota de tradução do mês acabou." if e.code == 456 else f"Tradução respondeu HTTP {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        raise TranslateError(f"Tradução indisponível: {e}") from e
    out = [t.get("text", "") for t in data.get("translations") or []]
    if len(out) != len(texts):
        raise TranslateError("Resposta de tradução incompleta.")
    return out


def translate(key: str, texts: list[str], lang: str, html: bool = False, timeout: float = 20) -> list[str]:
    """Traduz em lotes (mesma ordem). `lang` é o código do app (pt-BR, es, ...)."""
    target = TARGETS.get(lang)
    if not target or not key:
        raise TranslateError("Idioma sem tradução ou chave não configurada.")
    out: list[str] = []
    batch: list[str] = []
    size = 0
    for t in texts:
        if batch and (len(batch) >= BATCH or size + len(t) > BATCH_CHARS):
            out += _call(key, batch, target, html, timeout)
            batch, size = [], 0
        batch.append(t)
        size += len(t)
    if batch:
        out += _call(key, batch, target, html, timeout)
    return out
