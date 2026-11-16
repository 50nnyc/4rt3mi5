"""0.19.0: ⚙️ Configurações com idioma (português, inglês, espanhol e japonês)."""
import json
import re
import tempfile
import unittest
import zipfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "artemis" / "web"
LANGS = ("en", "es", "ja")
PH = re.compile(r"\{\d+\}")
# textos do index.html que ficam iguais em todo idioma (nomes do Tibia, marca, exemplos de formato)
SAME = {"4rt3mi5", "Lootsplit", "Hunt Session Stacker", "Hunts", "Solo", "Party", "XP", "XP/h", "☰", "←",
        "⚙️", "🔉", "hunt companion", "SENHA-XXXXX-XXXXX", "ART-XXXX-XXXX", "Gold/h", "Bosses"}


def load(lang):
    pairs = json.loads((WEB / f"i18n-{lang}.json").read_text(encoding="utf-8"), object_pairs_hook=lambda p: p)
    keys = [k for k, _ in pairs]
    return dict(pairs), keys


class _Texts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip, self.lang_skip = set(), 0, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "textarea"):
            self.skip += 1
        for k in ("placeholder", "title", "aria-label"):
            v = a.get(k)
            if v and re.search(r"[A-Za-zÀ-ú]{2}", v) and not v.startswith("Session data"):
                self.out.add(" ".join(v.split()))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "textarea"):
            self.skip -= 1

    def handle_data(self, d):
        s = " ".join(d.split())
        if not self.skip and re.search(r"[A-Za-zÀ-ú]{2}", s):
            self.out.add(s)


class DictionaryTests(unittest.TestCase):
    def test_same_keys_no_duplicates_and_placeholders(self):
        base, base_keys = load("en")
        self.assertEqual(len(base_keys), len(set(base_keys)), "chave repetida no inglês")
        ref = {k for k in base if not k.startswith("//")}
        for lang in LANGS:
            d, keys = load(lang)
            self.assertEqual(len(keys), len(set(keys)), f"chave repetida em {lang}")
            self.assertEqual({k for k in d if not k.startswith("//")}, ref, f"{lang} com chaves diferentes do inglês")
            for k, v in d.items():
                if k.startswith("//"):
                    continue
                self.assertTrue(v.strip(), f"{lang}: tradução vazia para {k!r}")
                self.assertEqual(sorted(PH.findall(k)), sorted(PH.findall(v)), f"{lang}: {{n}} diferente em {k!r}")

    def test_every_html_text_is_translated(self):
        p = _Texts()
        p.feed((WEB / "index.html").read_text(encoding="utf-8"))
        d, _ = load("en")
        missing = sorted(t for t in p.out if t not in d and t not in SAME)
        self.assertEqual(missing, [], "textos do index.html sem tradução")


class WiringTests(unittest.TestCase):
    def test_index_loads_engine_before_app(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('<script src="i18n.js">'), html.index('<script src="app.js">'))
        for el in ('id="pageSettings"', 'id="settingsLang"', 'id="loginLang"', 'id="gearBtn"', 'data-page="settings"'):
            self.assertIn(el, html)

    def test_engine_knows_the_four_languages(self):
        js = (WEB / "i18n.js").read_text(encoding="utf-8")
        for code in ("pt-BR", "en", "es", "ja"):
            self.assertIn(f'code: "{code}"', js)

    def test_server_serves_dictionaries(self):
        from fastapi.testclient import TestClient

        from artemis.server import app as server
        c = TestClient(server.app)
        for f in ("i18n.js", "i18n-en.json", "i18n-es.json", "i18n-ja.json"):
            r = c.get("/" + f)
            self.assertEqual(r.status_code, 200, f)
            self.assertEqual(r.headers["Cache-Control"], "no-cache")
        self.assertEqual(c.get("/i18n-xx.json").status_code, 404)
        self.assertIn("settings", server.TRACK_PAGES)

    def test_desktop_pack_carries_languages(self):
        from artemis.desktop import uipack
        z = Path(tempfile.mkdtemp()) / "web.zip"
        uipack.build(WEB, z)
        names = set(zipfile.ZipFile(z).namelist())
        self.assertTrue({"i18n.js", "i18n-en.json", "i18n-es.json", "i18n-ja.json"} <= names)


if __name__ == "__main__":
    unittest.main()
