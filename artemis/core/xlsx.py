"""0.32.2: gera uma planilha .xlsx (Excel/LibreOffice/Google Planilhas) só com a biblioteca padrão.

Cada aba é uma tabela: cabeçalho em negrito, linha congelada, filtro e larguras de coluna.
Números ficam como números (dá para somar e fazer gráficos no Excel); o resto vira texto.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

_BAD_SHEET = re.compile(r"[\[\]:*?/\\]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v, style: int = 0) -> str:
    if v is None or v == "":
        return f'<c r="{ref}" s="{style}"/>' if style else ""
    if isinstance(v, bool):
        v = "sim" if v else "não"
    if isinstance(v, (int, float)):
        return f'<c r="{ref}" s="{style or (1 if isinstance(v, int) else 2)}"><v>{v}</v></c>'
    text = _CTRL.sub("", str(v))
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet(headers: list[str], rows: list[list]) -> str:
    widths = [min(60, max(10, len(str(h)) + 2)) for h in headers]
    for r in rows:
        for i, v in enumerate(r[:len(headers)]):
            widths[i] = min(60, max(widths[i], len(str(v)) + 2 if v is not None else 0))
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    body = ['<row r="1">' + "".join(_cell(f"{_col(i)}1", h, 3) for i, h in enumerate(headers)) + "</row>"]
    for n, r in enumerate(rows, start=2):
        body.append(f'<row r="{n}">' + "".join(_cell(f"{_col(i)}{n}", v) for i, v in enumerate(r[:len(headers)])) + "</row>")
    last = f"{_col(max(len(headers) - 1, 0))}{max(len(rows) + 1, 1)}"
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f"<cols>{cols}</cols><sheetData>{''.join(body)}</sheetData>"
            f'<autoFilter ref="A1:{last}"/></worksheet>')


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFE8D9A8"/><bgColor indexed="64"/></patternFill></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
          '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
          '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
          '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def build(sheets: list[tuple[str, list[str], list[list]]]) -> bytes:
    """`sheets`: [(nome da aba, cabeçalhos, linhas)]. Devolve o conteúdo do arquivo .xlsx."""
    names, used = [], set()
    for name, _, _ in sheets or [("Dados", [], [])]:
        base = _BAD_SHEET.sub(" ", name).strip()[:31] or "Aba"
        n, i = base, 2
        while n.lower() in used:
            n = f"{base[:28]} {i}"
            i += 1
        used.add(n.lower())
        names.append(n)
    sheets = sheets or [("Dados", ["Aviso"], [["Nada para exportar."]])]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(sheets))) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                             f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                     'Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", STYLES)
        for i, (_, headers, rows) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet(headers, rows))
    return buf.getvalue()
