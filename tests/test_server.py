import os
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

os.environ["ARTEMIS_DATA_DIR"] = tempfile.mkdtemp(prefix="artemis_test_")

from fastapi.testclient import TestClient  # noqa: E402

from artemis.core.tibiadata import CharacterInfo  # noqa: E402
from artemis.server import app as server  # noqa: E402
from artemis.server.db import _iso, utcnow  # noqa: E402
from tests.test_core import EXAMPLE  # noqa: E402
from tests.test_session import SOLO  # noqa: E402

COMMENTS: dict[str, str] = {}


def fake_fetch(name, timeout=10):
    if name.lower() == "naoexiste":
        return None
    return CharacterInfo(name=name.title(), level=100, vocation="Knight", world="Celebra",
                         comment=COMMENTS.get(name.lower(), ""))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server._char_cache.clear()
        server._last_check.clear()
        server._exp_cache.clear()
        COMMENTS.clear()
        self.patch = mock.patch.object(server, "fetch_character", fake_fetch)
        self.patch.start()
        self.hs = mock.patch.object(server, "fetch_experience", lambda *a, **k: None)
        self.hs.start()
        self.key = server.store.create_key(30, "teste")["key"]

    def tearDown(self):
        self.patch.stop()
        self.hs.stop()

    def h(self, token=""):
        return {"X-Access-Key": self.key, "X-Device-Token": token}

    def verify(self, character, token="", put_in_comment=True):
        r = self.client.post("/api/verify/start", json={"character": character}, headers=self.h(token))
        self.assertEqual(r.status_code, 200, r.text)
        code = r.json()["code"]
        if put_in_comment:
            COMMENTS[character.lower()] = f"meu char :) {code}"
        server._last_check.clear()
        return code, self.client.post("/api/verify/check", json={"code": code}, headers=self.h(token))

    def test_key_rules(self):
        bad = self.client.post("/api/auth", headers={"X-Access-Key": "ART-NAO-EXISTE"})
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(bad.json()["detail"]["message"], server.INVALID_KEY)
        self.assertEqual(self.client.post("/api/auth", headers={"X-Access-Key": self.key.lower()}).status_code, 200)
        with self.assertRaises(ValueError):
            server.store.create_key(31)
        server.store._conn.execute("UPDATE access_keys SET expires_at = ? WHERE key = ?",
                                   (_iso(utcnow() - timedelta(seconds=1)), self.key))
        self.assertEqual(self.client.post("/api/auth", headers=self.h()).status_code, 401)
        self.assertNotIn(self.key, [k["key"] for k in server.store.list_keys()])

    def test_needs_verification_before_use(self):
        r = self.client.get("/api/hunts/Hilay", headers=self.h())
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"]["reason"], "device")
        self.assertEqual(self.client.post("/api/verify/start", json={"character": "naoexiste"}, headers=self.h()).status_code, 404)
        code, r = self.verify("Hilay", put_in_comment=False)
        self.assertEqual(r.status_code, 409)  # código ainda não está no comentário

    def test_main_char_binding_blocks_copied_key(self):
        _, r = self.verify("Hilay")
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        self.assertEqual(r.json()["me"]["main_char"], "Hilay")
        self.assertEqual(self.client.get("/api/me", headers=self.h(token)).status_code, 200)
        # outra pessoa com o código copiado tenta usar o próprio personagem
        r = self.client.post("/api/verify/start", json={"character": "Intruso"}, headers=self.h())
        self.assertEqual(r.status_code, 403)
        # ...ou o personagem do dono, mas não consegue mexer no comentário dele
        COMMENTS.clear()
        _, r = self.verify("Hilay", put_in_comment=False)
        self.assertEqual(r.status_code, 409)
        # o dono, num segundo aparelho, consegue (verificando de novo)
        _, r = self.verify("Hilay")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["token"], token)

    def test_link_alt_and_change_main(self):
        token = self.verify("Hilay")[1].json()["token"]
        r = self.verify("Jioe", token=token)[1]
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["token"], token)  # mesmo aparelho
        names = {c["name"]: c["is_main"] for c in r.json()["me"]["chars"]}
        self.assertEqual(names, {"Hilay": True, "Jioe": False})
        me = self.client.post("/api/chars/main", json={"character": "jioe"}, headers=self.h(token)).json()
        self.assertEqual(me["main_char"], "Jioe")
        self.assertEqual(self.client.delete("/api/chars/Jioe", headers=self.h(token)).status_code, 400)  # main
        self.assertEqual(self.client.delete("/api/chars/Hilay", headers=self.h(token)).status_code, 200)

    def test_upload_only_for_linked_chars(self):
        token = self.verify("Hilay")[1].json()["token"]
        body = {"raw_text": EXAMPLE, "nickname": "Vcte"}
        r = self.client.post("/api/lootsplit", json=body, headers=self.h(token))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["message"], server.FORBIDDEN_UPLOAD)
        r = self.client.post("/api/lootsplit", json={**body, "nickname": "hilay"}, headers=self.h(token))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["hunt"]["profit_each"], 2_319_540)
        # qualquer aparelho liberado vê as hunts de qualquer jogador
        hunts = self.client.get("/api/hunts/atx buubo", headers=self.h(token)).json()["hunts"]
        self.assertTrue(any(h["profit_each"] == 2_319_540 for h in hunts))

    def test_stacker(self):
        token = self.verify("Jioe")[1].json()["token"]
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "jioe"}, headers=self.h(token))
        self.assertEqual(r.status_code, 200, r.text)
        again = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Jioe"}, headers=self.h(token))
        self.assertFalse(again.json()["created"])
        data = self.client.get("/api/stacker/Jioe", headers=self.h(token)).json()
        self.assertEqual(data["day"], "2026-11-04")
        self.assertEqual(data["lifetime"]["xp_per_hour"], round(7_684_000 / 1.5))
        self.assertEqual(self.client.get("/api/stacker/Ninguem", headers=self.h(token)).json()["lifetime"]["xp"], 0)

    def test_admin_requires_token_and_local_access(self):
        admin = {"X-Admin-Token": server.CONFIG["admin_token"]}
        self.assertEqual(self.client.get("/api/admin/keys").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/keys", headers={"X-Admin-Token": "errada"}).status_code, 401)
        # pela internet (ngrok manda X-Forwarded-For) é recusado mesmo com a senha certa
        via_tunnel = self.client.get("/api/admin/keys", headers={**admin, "X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(via_tunnel.status_code, 403)
        self.assertEqual(self.client.get("/admin", headers={"X-Forwarded-For": "1.2.3.4"}).status_code, 404)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/keys", headers=admin).status_code, 200)

    def test_admin_create_renew_and_trusted_contact(self):
        admin = {"X-Admin-Token": server.CONFIG["admin_token"]}
        k = self.client.post("/api/admin/keys", json={"label": "Amigo", "days": 7}, headers=admin).json()
        self.assertEqual(self.client.post("/api/admin/keys", json={"days": 31}, headers=admin).status_code, 422)
        r = self.client.post(f"/api/admin/keys/{k['key']}/renew", json={"days": 15}, headers=admin)
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()["expires_at"], k["expires_at"])
        # forçar main: o contato entra só com código + nick, sem código de verificação
        r = self.client.post(f"/api/admin/keys/{k['key']}/trust", json={"character": "hilay"}, headers=admin)
        self.assertEqual(r.json(), {"key": k["key"], "main_char": "Hilay", "trusted": True})
        h = {"X-Access-Key": k["key"]}
        start = self.client.post("/api/verify/start", json={"character": "Hilay"}, headers=h).json()
        self.assertIn("token", start)
        self.assertEqual(self.client.get("/api/me", headers={**h, "X-Device-Token": start["token"]}).json()["main_char"], "Hilay")
        # outro personagem continua bloqueado
        self.assertEqual(self.client.post("/api/verify/start", json={"character": "Intruso"}, headers=h).status_code, 403)
        overview = {x["key"]: x for x in self.client.get("/api/admin/keys", headers=admin).json()}[k["key"]]
        self.assertTrue(overview["trusted"])
        self.assertEqual(overview["devices"], 1)
        # sem confiança volta a exigir código de verificação
        self.client.post(f"/api/admin/keys/{k['key']}/untrust", headers=admin)
        self.assertIn("code", self.client.post("/api/verify/start", json={"character": "Hilay"}, headers=h).json())
        self.assertEqual(self.client.delete(f"/api/admin/keys/{k['key']}", headers=admin).status_code, 200)
        self.assertEqual(self.client.post("/api/auth", headers=h).status_code, 401)

    def test_only_uploader_can_delete(self):
        token = self.verify("Hilay")[1].json()["token"]
        r = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=self.h(token)).json()
        hunt = r["hunt"]
        self.assertTrue(hunt["can_delete"])
        self.assertNotIn("uploader_key", hunt)
        self.assertEqual({p["name"]: p["damage"] for p in hunt["players"]}["Jioe"], 16_215_326)  # damage guardado
        # outra pessoa (outro código) vê a hunt, mas não pode apagar
        other_key = server.store.create_key(30, "outro")["key"]
        other_token = server.store.issue_device(other_key, "Jioe")
        other = {"X-Access-Key": other_key, "X-Device-Token": other_token}
        seen = self.client.get("/api/hunts/Jioe", headers=other).json()["hunts"]
        self.assertFalse(next(h for h in seen if h["id"] == hunt["id"])["can_delete"])
        self.assertEqual(self.client.delete(f"/api/hunt/{hunt['id']}", headers=other).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/hunt/{hunt['id']}", headers=self.h(token)).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/hunt/{hunt['id']}", headers=self.h(token)).status_code, 404)
        # stacker igual
        s = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Hilay"}, headers=self.h(token)).json()["session"]
        self.assertTrue(s["can_delete"])
        self.assertEqual(self.client.delete(f"/api/stacker/session/{s['id']}", headers=other).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/stacker/session/{s['id']}", headers=self.h(token)).status_code, 200)

    def test_stacker_loot_prices_and_user_average(self):
        server.store.load_wiki({"imported_at": "teste", "items": [
            ["Dwarven Shield", 100, [["Hardek"], ["H.L.", 55], ["Morpel"]], "Escudos"],
            ["White Mushroom", 2, [["Avriel"]], "Comidas"],
            ["Dragon Scale Mail", 40000, [["Hireling (Trader)"], ["Rashid"]], "Armaduras"],
            ["Strange Relic", 0, [], "Outros"],
        ], "npcs": {"Hardek": ["Thais", "Thais.", [32279, 32354, 7]], "Morpel": ["Yalahar", "Yalahar.", [32700, 31100, 7]],
                    "H.L.": ["Venore", "Outlaw Camp.", [32600, 32100, 7]], "Avriel": ["Ab'Dendriel", "Ab'Dendriel.", None]}})
        token = self.verify("Hilay")[1].json()["token"]
        raw = SOLO.replace("  3x gold coin", "  3x gold coin\n  2x dwarven shields\n  4x a strange relic")
        self.assertEqual(self.client.post("/api/stacker", json={"raw_text": raw, "nickname": "Hilay"}, headers=self.h(token)).status_code, 200)
        d = self.client.get("/api/stacker/Hilay?period=365", headers=self.h(token)).json()
        p = d["prices"]
        # melhor preço: Hardek e Morpel (100) empatados; H.L. (55) não aparece
        self.assertEqual(p["dwarven shield"]["npc_price"], 100)
        self.assertEqual({b["npc"] for b in p["dwarven shield"]["buyers"]}, {"Hardek", "Morpel"})
        self.assertEqual(p["dwarven shield"]["buyers"][0]["coords"], [32279, 32354, 7])
        self.assertEqual(p["gold coin"]["unit_price"], 1)
        loot = {it["key"]: it for it in d["sessions"][0]["loot"]}
        self.assertEqual(loot["dwarven shield"]["value"], 200)  # plural reconhecido
        self.assertEqual(loot["strange relic"]["value"], 0)    # sem NPC e sem preço ainda
        self.assertEqual(d["period"]["unpriced"], 1)
        # preço informado pelos usuários -> média
        r = self.client.post("/api/items/price", json={"item": "strange relic", "price": 1000}, headers=self.h(token)).json()
        self.assertEqual((r["avg_price"], r["my_price"]), (1000, 1000))
        other_key = server.store.create_key(30, "x")["key"]
        other = {"X-Access-Key": other_key, "X-Device-Token": server.store.issue_device(other_key, "Jioe")}
        r = self.client.post("/api/items/price", json={"item": "a strange relic", "price": 3000}, headers=other).json()
        self.assertEqual((r["avg_price"], r["avg_count"], r["my_price"]), (2000, 2, 3000))
        self.assertEqual(self.client.post("/api/items/price", json={"item": "dwarven shield", "price": 5}, headers=other).status_code, 400)
        d = self.client.get("/api/stacker/Hilay?period=365", headers=self.h(token)).json()
        self.assertEqual({it["key"]: it for it in d["period"]["items"]}["strange relic"]["value"], 8000)
        self.assertEqual({k["key"]: k["count"] for k in d["period"]["kills"]}["dragon"], 120)

    def test_hunts_goals_sell_records_forecast(self):
        server.store.load_places({"imported_at": "t", "hunts": [
            ["Darama Dragon Lair", "Darashia", "Norte", 40, [33265, 32276, 7], True],
            ["Mintwallin", "Thais", "Sul", 30, None, True]]})
        places = {p["name"]: p["id"] for p in self.client.get("/api/places", headers=self.h(self.verify("Knightzao")[1].json()["token"])).json()}
        token = self.verify("Knightzao")[1].json()["token"]
        h = self.h(token)
        dragon = places["Darama Dragon Lair"]
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Knightzao", "place_id": dragon}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["session"]["level"], 100)  # level do TibiaData no envio
        # outra pessoa na mesma hunt (para ranking / jogadores / level médio)
        k2 = server.store.create_key(30, "b")["key"]
        server.store.force_main(k2, "Druidinha")
        h2 = {"X-Access-Key": k2, "X-Device-Token": server.store.issue_device(k2, "Druidinha")}
        raw2 = SOLO.replace("18:50:49", "17:50:49").replace("XP Gain: 7,684,000", "XP Gain: 3,000,000")
        self.client.post("/api/stacker", json={"raw_text": raw2, "nickname": "Druidinha", "place_id": dragon}, headers=h2)
        rank = self.client.get("/api/places/ranking?sort=xp", headers=h).json()["rows"]
        self.assertEqual(rank[0]["name"], "Darama Dragon Lair")
        self.assertEqual((rank[0]["sessions"], rank[0]["players"], rank[0]["avg_level"]), (2, 2, 100))
        self.assertEqual(rank[0]["xp_per_hour"], round((7_684_000 + 3_000_000) / 4))  # 1h30 + 2h30
        self.assertEqual(self.client.get("/api/places/ranking?min_level=200", headers=h).json()["rows"], [])
        cmp_ = self.client.get(f"/api/places/compare?ids={dragon},{places['Mintwallin']}&nick=Knightzao", headers=h).json()
        self.assertEqual(cmp_[0]["mine"]["sessions"], 1)
        self.assertIsNone(cmp_[1]["stats"])
        self.assertEqual(cmp_[0]["top_kills"][0], {"key": "dragon", "count": 240})
        # nova hunt criada pelo usuário
        self.assertEqual(self.client.post("/api/places", json={"name": "Minha Hunt Secreta"}, headers=h).json()["source"], "user")
        # metas: só o dono altera
        self.assertEqual(self.client.post("/api/goals/Knightzao", json={"period": "week", "metric": "xp", "target": 1000}, headers=h2).status_code, 403)
        self.client.post("/api/goals/Knightzao", json={"period": "day", "metric": "xp", "target": 1000}, headers=h)
        d = self.client.get("/api/stacker/Knightzao", headers=h).json()
        self.assertTrue(d["is_owner"])
        self.assertEqual(d["goals"][0]["target"], 1000)
        # previsão: level 100 -> 101 precisa de 50*100² - 150*100 + 200 XP
        self.assertEqual(d["forecast"]["xp_next_level"], 485_200)
        self.assertEqual(d["forecast"]["mark"], 150)
        self.assertEqual(d["forecast"]["xp_source"], "level")
        # com XP exata do highscore (100.000 XP dentro do level 100)
        server._exp_cache.clear()
        with mock.patch.object(server, "fetch_experience", lambda *a, **k: (server.xp_at(100) + 100_000, 0)):
            f = self.client.get("/api/stacker/Knightzao", headers=h).json()["forecast"]
        self.assertEqual(f["xp_source"], "highscore")
        self.assertEqual(f["xp_next_level"], 385_200)
        self.assertEqual(f["level_pct"], round(100_000 * 100 / 485_200, 1))
        self.assertEqual([r["level"] for r in f["table"]], [101, 102, 103, 104, 105, 150, 200])
        # recordes e lucro líquido real (loot pelos preços - supplies)
        self.assertEqual({r["label"] for r in d["records"]} >= {"Maior XP/h", "Sessão mais longa"}, True)
        s = d["sessions"][0]
        self.assertEqual(s["net_profit"], s["loot_value"] - s["supplies"])
        self.assertEqual(s["place"]["name"], "Darama Dragon Lair")
        # lista de venda: aviso ao juntar 2 gold... (moeda não entra) -> usa item comum
        server.store.load_wiki({"imported_at": "t2", "items": [["Dragon Ham", 15, [["Billy"]], "Comidas"]], "npcs": {}})
        raw3 = SOLO.replace("18:50:49", "16:50:49").replace("  3x gold coin", "  3x gold coin\n  5x dragon ham")
        self.client.post("/api/stacker", json={"raw_text": raw3, "nickname": "Knightzao", "place_id": dragon}, headers=h)
        self.client.post("/api/sell/Knightzao", json={"item": "dragon ham", "target": 5}, headers=h)
        d = self.client.get("/api/stacker/Knightzao", headers=h).json()
        self.assertEqual([a["key"] for a in d["alerts"]], ["dragon ham"])
        self.assertNotIn("gold coin", [i["key"] for i in d["sell"]])
        self.client.post("/api/sell/Knightzao/sold", json={"item": "dragon ham"}, headers=h)
        d = self.client.get("/api/stacker/Knightzao", headers=h).json()
        self.assertEqual(d["alerts"], [])
        self.assertEqual({i["key"]: i["count"] for i in d["sell"]}["dragon ham"], 0)

    def test_renew_keeps_chars(self):
        self.verify("Hilay")
        k = server.store.renew_key(self.key, 10)
        self.assertEqual(k["main_char"], "Hilay")
        with self.assertRaises(ValueError):
            server.store.renew_key(self.key, 31)


if __name__ == "__main__":
    unittest.main()
