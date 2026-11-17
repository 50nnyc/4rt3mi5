"""Notícias do Tibia (Latest News e News Archive) pela API pública do TibiaData (v4). Só usa a stdlib.

O HTML das notícias vem de fora: antes de guardar, passa por uma lista fechada de tags e atributos
(nada de script, estilo, eventos ou imagens externas — imagem vira link "Ver imagem").
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

ARCHIVE_URL = "https://api.tibiadata.com/v4/news/archive/{days}"
ITEM_URL = "https://api.tibiadata.com/v4/news/id/{id}"
TIBIA_NEWS_URL = "https://www.tibia.com/news/?subtopic=newsarchive&id={id}"
TYPES = ("news", "ticker", "article")                                      # News, News Ticker, Featured Article
CATEGORIES = ("cipsoft", "community", "development", "support", "technical")


class TibiaNewsError(RuntimeError):
    """Fonte fora do ar ou resposta inesperada."""


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "4rt3mi5", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        raise TibiaNewsError(f"Não foi possível consultar as notícias: {e}") from e


def fetch_archive(days: int, timeout: float = 30) -> list[dict]:
    """Lista (sem o texto) das notícias dos últimos `days` dias: id, date, title, category, type."""
    data = _get_json(ARCHIVE_URL.format(days=int(days)), timeout)
    out = []
    for n in data.get("news") or []:
        try:
            nid = int(n["id"])
        except (KeyError, TypeError, ValueError):
            continue
        typ, cat = str(n.get("type") or "").lower(), str(n.get("category") or "").lower()
        date = str(n.get("date") or "")[:10]
        if typ not in TYPES or cat not in CATEGORIES or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        out.append({"id": nid, "date": date, "title": " ".join(str(n.get("news") or "").split())[:300],
                    "category": cat, "type": typ})
    return out


def fetch_item(news_id: int, timeout: float = 15) -> dict | None:
    """Texto completo de uma notícia (HTML já limpo). None se ela não existe."""
    data = _get_json(ITEM_URL.format(id=int(news_id)), timeout)
    n = data.get("news") or {}
    if not n or not (n.get("content_html") or n.get("content")):
        return None
    raw = n.get("content_html") or html.escape(n.get("content") or "")
    return {"id": int(news_id), "title": " ".join(str(n.get("title") or "").split())[:300],
            "content_html": sanitize(raw), "content_text": " ".join(str(n.get("content") or "").split())}


# ------------------------------------------------------------------ limpeza do HTML
_ALLOWED = {"p", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li", "a", "h1", "h2", "h3", "h4", "h5",
            "blockquote", "table", "thead", "tbody", "tr", "td", "th", "span", "div", "small", "hr", "img"}
_VOID = {"br", "hr"}
_DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math", "form"}
_BIG_IMG = re.compile(r"ImageInNewWindow\(\s*'([^']+)'")


def _safe_url(url: str) -> str | None:
    url = html.unescape(url or "").strip()
    if url.startswith("/"):
        url = urllib.parse.urljoin("https://www.tibia.com/", url)
    p = urllib.parse.urlparse(url)
    return url if p.scheme in ("http", "https") and p.netloc else None


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0          # dentro de <script>, <style>…
        self.stack: list[str] = []
        self.images: list[str] = []  # vão para o fim do texto (no meio da frase atrapalham a leitura)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_WITH_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in _ALLOWED:
            return
        a = dict(attrs)
        if tag == "img":
            # imagens externas ficam fora da página (o CSP só permite as nossas): viram um link
            big = _BIG_IMG.search(a.get("onclick") or "")
            url = _safe_url(big.group(1) if big else (a.get("src") or ""))
            if url and url not in self.images:
                self.images.append(url)
            return
        if tag == "a":
            url = _safe_url(a.get("href") or "")
            self.out.append(f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">' if url else "<a>")
        else:
            self.out.append(f"<{tag}>")
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() in _ALLOWED and tag.lower() not in _VOID and tag.lower() != "img" and not self.skip:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.stack:
            return
        while self.stack:  # fecha o que ficou aberto até chegar nela
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        if self.images:
            links = " · ".join(f'<a class="tn-img" href="{html.escape(u)}" target="_blank" rel="noopener noreferrer">🖼️ Ver imagem</a>'
                               for u in self.images[:12])
            self.out.append(f"<p>{links}</p>")
        return "".join(self.out).strip()


def sanitize(raw: str) -> str:
    c = _Cleaner()
    c.feed(raw or "")
    c.close()
    return c.result()
