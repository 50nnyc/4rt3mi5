"""0.24.2: busca de personagem na v5 do TibiaData, com a v4 de reserva."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from artemis.core import tibiadata
from artemis.core.tibiadata import TibiaDataError, fetch_character


def _ok(name="Goraca"):
    body = {"character": {"character": {"name": name, "level": 3173, "vocation": "Master Sorcerer",
                                        "world": "Bona", "comment": "abc"}}}
    resp = io.BytesIO(json.dumps(body).encode())
    resp.__enter__ = lambda s=resp: s
    resp.__exit__ = lambda *a: None
    return resp


def _http(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


class TibiaDataV5(unittest.TestCase):
    def test_uses_v5_first(self):
        calls = []
        def fake(req, timeout):
            calls.append(req.full_url)
            return _ok()
        with mock.patch.object(tibiadata.urllib.request, "urlopen", fake):
            info = fetch_character("Goraca")
        self.assertEqual(info.name, "Goraca")
        self.assertEqual(info.level, 3173)
        self.assertEqual(len(calls), 1)
        self.assertIn("/v5/character/", calls[0])

    def test_falls_back_to_v4_when_v5_fails(self):
        calls = []
        def fake(req, timeout):
            calls.append(req.full_url)
            if "/v5/" in req.full_url:
                raise _http(502)
            return _ok()
        with mock.patch.object(tibiadata.urllib.request, "urlopen", fake):
            info = fetch_character("Goraca")
        self.assertEqual(info.world, "Bona")
        self.assertIn("/v4/character/", calls[1])

    def test_v5_404_is_not_found_without_asking_v4(self):
        calls = []
        def fake(req, timeout):
            calls.append(req.full_url)
            raise _http(404)
        with mock.patch.object(tibiadata.urllib.request, "urlopen", fake):
            self.assertIsNone(fetch_character("Nao Existe"))
        self.assertEqual(len(calls), 1)

    def test_both_down_raises(self):
        def fake(req, timeout):
            raise _http(502)
        with mock.patch.object(tibiadata.urllib.request, "urlopen", fake):
            with self.assertRaises(TibiaDataError):
                fetch_character("Goraca")


if __name__ == "__main__":
    unittest.main()
