"""Calendário de eventos do Tibia a partir do HTML que o administrador copia do tibia.com (Event Schedule).

Do HTML só saem dados: dia, nome do evento, cores, se começa/termina no server save (*) e a descrição em texto.
Nada do HTML colado é mostrado ao usuário como HTML.
"""
from __future__ import annotations

import html
import re
from datetime import date
from html.parser import HTMLParser

MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"), start=1)}
_HEADER = re.compile(r"eventscheduleheaderdateblock.*?</span>\s*([A-Za-z]+)\s+(\d{4})", re.S)
_NEXT_LINK = re.compile(r"calendarmonth=(\d{1,2})(?:&amp;|&)calendaryear=(\d{4})")
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_HELPER = re.compile(r"ActivateHelperDiv\(\s*\$\(this\)\s*,\s*'(?:\\.|[^'\\])*'\s*,\s*'((?:\\.|[^'\\])*)'", re.S)
_DESC_PAIR = re.compile(r"<div[^>]*font-size[^>]*>(.*?):?\s*</div>\s*<div[^>]*>(.*?)</div>", re.S | re.I)
_TAGS = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S | re.I)
MAX_TEXT = 600


class CalendarError(ValueError):
    """O texto colado não parece o calendário do tibia.com."""


def _text(s: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", s)).split())


def _month_of(raw: str) -> tuple[int, int]:
    m = _HEADER.search(raw)
    if m and m.group(1).lower() in MONTHS:
        return int(m.group(2)), MONTHS[m.group(1).lower()]
    n = _NEXT_LINK.search(raw)  # o link » aponta para o mês seguinte
    if n:
        mon, year = int(n.group(1)), int(n.group(2))
        return (year, mon - 1) if mon > 1 else (year - 1, 12)
    raise CalendarError("Não achei o mês no texto colado. Copie a caixa inteira do Event Schedule.")


def _descriptions(js: str) -> dict[str, str]:
    m = _HELPER.search(js or "")
    if not m:
        return {}
    body = m.group(1).replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    out = {}
    for title, desc in _DESC_PAIR.findall(body):
        name, text = _text(title).rstrip(":").strip(), _text(desc).lstrip("•").strip()
        if name:
            out[name[:80]] = text[:MAX_TEXT]
    return out


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0          # dentro da tabela #eventscheduletable
        self.cells: list[dict] = []
        self.cell: dict | None = None
        self.in_day = False
        self.label: dict | None = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
            return
        if tag == "table":
            if self.depth or a.get("id") == "eventscheduletable":
                self.depth += 1
            return
        if not self.depth:
            return
        style = (a.get("style") or "").replace(" ", "").lower()
        if tag == "td":
            self.cell = {"day": None, "labels": [], "desc": {}}
        elif self.cell is None:
            return
        elif tag == "span" and "vertical-align:text-bottom" in style:
            self.in_day = True
        elif tag == "span" and "HelperDivIndicator" in (a.get("class") or ""):
            self.cell["desc"].update(_descriptions(a.get("onmouseover") or ""))
        elif tag == "div" and "background:#" in style:
            bg = _COLOR.search(style.split("background:", 1)[1])
            fg = _COLOR.search(style.split("color:", 1)[1]) if "color:" in style else None
            fgw = "white" if "color:white" in style else None
            self.label = {"bg": bg.group(0) if bg else "#555555", "fg": fg.group(0) if fg else (fgw or "#ffffff"), "text": ""}

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if tag == "table" and self.depth:
            self.depth -= 1
            return
        if not self.depth or self.cell is None:
            return
        if tag == "span":
            self.in_day = False
        elif tag == "div" and self.label is not None:
            text = " ".join(self.label["text"].split())
            if text:
                self.cell["labels"].append({**self.label, "text": text})
            self.label = None
        elif tag == "td":
            if self.cell["day"]:
                self.cells.append(self.cell)
            self.cell = None

    def handle_data(self, data):
        if self.skip or self.cell is None:
            return
        if self.in_day and data.strip().isdigit():
            self.cell["day"] = int(data.strip())
        elif self.label is not None:
            self.label["text"] += data


def parse_calendar(raw: str) -> dict:
    """{"month": "AAAA-MM", "days": {"AAAA-MM-DD": [{name, star, bg, fg}]}, "events": {nome: {description, bg, fg}}}"""
    if not raw or "eventscheduletable" not in raw:
        raise CalendarError("Isso não parece o calendário do tibia.com. Copie o HTML da caixa Event Schedule inteira.")
    year, month = _month_of(raw)
    r = _Reader()
    r.feed(raw)
    r.close()
    if len(r.cells) < 28:
        raise CalendarError("O calendário colado está incompleto. Copie a caixa Event Schedule inteira.")
    # dias de antes do dia 1 são do mês anterior; depois do último, do seguinte
    offset = -1 if r.cells[0]["day"] != 1 else 0
    days: dict[str, list] = {}
    events: dict[str, dict] = {}
    for i, c in enumerate(r.cells):
        if i and c["day"] == 1:
            offset += 1
        y, m = year, month + offset
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        try:
            key = date(y, m, c["day"]).isoformat()
        except ValueError:
            continue
        items = []
        for lab in c["labels"][:8]:
            star = lab["text"].startswith("*")
            name = lab["text"].lstrip("*").strip()[:80]
            if not name:
                continue
            items.append({"name": name, "star": star, "bg": lab["bg"], "fg": lab["fg"]})
            ev = events.setdefault(name, {"description": "", "bg": lab["bg"], "fg": lab["fg"]})
            if not ev["description"] and c["desc"].get(name):
                ev["description"] = c["desc"][name]
        days[key] = items
    if not any(days.values()):
        raise CalendarError("Não achei nenhum evento no calendário colado.")
    return {"month": f"{year:04d}-{month:02d}", "days": days, "events": events}
