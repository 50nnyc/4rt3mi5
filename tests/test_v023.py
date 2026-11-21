"""0.23.0: 🤝 Substituições — personagem certo, sessão duplicada, link de envio, jogador autorizado,
marcações (jogado por outra pessoa / substituto), assumir lootsplit e rankings sem as jogadas de outra pessoa."""
import unittest
from datetime import timedelta
from unittest import mock

from fastapi.testclient import TestClient

from artemis.server import app as server
from artemis.server.db import _iso, utcnow
from tests import limpar_banco
from tests.test_core import EXAMPLE
from tests.test_server import COMMENTS, fake_fetch
from tests.test_session import SOLO

# Hunt Session do mesmo horário do EXAMPLE (Party Hunt Analyser de 2026-11-04 18:50:49 a 20:21:07)
PARTY_SESSION = SOLO


def party_text(day: str) -> str:
    """O EXAMPLE em outro dia (lootsplit diferente, mesma PT)."""
    return EXAMPLE.replace("2026-11-04", day)


class SubsTests(unittest.TestCase):
    def setUp(self):
        limpar_banco(server.store._conn)
        self.client = TestClient(server.app)
        for cache in (server._char_cache, server._last_check, server._exp_cache, server._hits, server._fails,
                      server._captcha_used):
            cache.clear()
        COMMENTS.clear()
        conn = server.store._conn
        for t in ("key_chars", "solo_sessions", "party_sessions", "hunt_players", "hunts", "hunt_tags", "upload_links",
                  "char_claims", "boss_sessions", "boss_hunt_players", "boss_hunts", "ranking_optin", "hunt_rules"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        self.patches = [mock.patch.object(server, "fetch_character", fake_fetch),
                        mock.patch.object(server, "fetch_experience", lambda *a, **k: None),
                        mock.patch.object(server.captcha, "verify", lambda *a, **k: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def login(self, *characters):
        key = server.store.create_key(30, "v023")["key"]
        token = None
        for character in characters:
            hdr = {"X-Access-Key": key, **({"X-Device-Token": token} if token else {})}
            r = self.client.post("/api/verify/start", json={"character": character}, headers=hdr)
            self.assertEqual(r.status_code, 200, r.text)
            COMMENTS[character.lower()] = r.json()["code"]
            server._last_check.clear()
            r = self.client.post("/api/verify/check", json={"code": r.json()["code"]}, headers=hdr)
            self.assertEqual(r.status_code, 200, r.text)
            token = token or r.json()["token"]
        return {"X-Access-Key": key, "X-Device-Token": token}

    # ---------------------------------------------------------------- personagem certo
    def test_lootsplit_needs_a_char_in_the_party(self):
        outsider = self.login("Fulano Fora")
        r = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Fulano Fora"}, headers=outsider)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["message"], server.NOT_IN_PARTY_UPLOAD)
        self.assertEqual(server.store.hunts_for_player("Hilay"), [])  # nada foi salvo

    def test_lootsplit_switches_to_the_char_in_the_party(self):
        h = self.login("Meu Main", "Hilay")
        r = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Meu Main"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["saved_as"], r.json()["switched_from"]), ("Hilay", "Meu Main"))
        self.assertTrue(r.json()["hunt"]["can_delete"])
        # a sessão da PT também troca sozinha
        hid = r.json()["hunt"]["id"]
        r = self.client.post(f"/api/hunt/{hid}/session", json={"raw_text": PARTY_SESSION, "nickname": "Meu Main"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([s["name"] for s in r.json()["hunt"]["member_sessions"]], ["Hilay"])

    def test_stacker_goes_to_the_char_of_the_same_party_hunt(self):
        h = self.login("Meu Main", "Hilay")
        self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=h)
        r = self.client.post("/api/stacker", json={"raw_text": PARTY_SESSION, "nickname": "Meu Main"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["saved_as"], r.json()["switched_from"]), ("Hilay", "Meu Main"))

    def test_same_session_is_not_saved_in_two_chars(self):
        h = self.login("Hilay", "Jioe")
        self.assertEqual(self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Hilay"}, headers=h).status_code, 200)
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Jioe"}, headers=h)
        self.assertEqual(r.status_code, 409)
        self.assertIn("Hilay", r.json()["detail"]["message"])
        other = self.login("Vcte")
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Vcte"}, headers=other)
        self.assertEqual(r.status_code, 409)
        self.assertNotIn("Hilay", r.json()["detail"]["message"])  # não diz de quem é na outra conta
        again = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Hilay"}, headers=h)
        self.assertFalse(again.json()["created"])  # a mesma no mesmo personagem continua "já estava salva"

    # ---------------------------------------------------------------- link de envio
    def make_link(self, h, **kw):
        body = {"character": "Hilay", "scopes": ["solo", "party", "boss"], "hours": 24, "max_uses": 5, **kw}
        r = self.client.post("/api/links", json=body, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def recent(self, text: str) -> str:
        """Texto do analyser com a data de hoje (o link só aceita hunts do período dele)."""
        today = utcnow().date().isoformat()
        return text.replace("2026-11-04", today)

    def test_link_rules(self):
        owner = self.login("Hilay")
        self.assertEqual(self.client.post("/api/links", json={"character": "Jioe", "scopes": ["solo"]}, headers=owner).status_code, 403)
        self.assertEqual(self.client.post("/api/links", json={"character": "Hilay", "scopes": ["solo"], "hours": 5},
                                          headers=owner).status_code, 422)
        self.assertEqual(self.client.post("/api/links", json={"character": "Hilay", "scopes": []}, headers=owner).status_code, 422)
        r = self.client.post("/api/links", json={"character": "Hilay", "scopes": ["solo"], "operator": "Hilay"}, headers=owner)
        self.assertEqual(r.status_code, 422)  # o próprio personagem não é "quem vai jogar por você"
        for _ in range(server.store.MAX_ACTIVE_LINKS):
            self.make_link(owner)
        self.assertEqual(self.client.post("/api/links", json={"character": "Hilay", "scopes": ["solo"]}, headers=owner).status_code, 429)
        first = self.client.get("/api/subs", headers=owner).json()["links"][0]
        self.assertNotIn("token", first)
        self.assertNotIn("token_hash", first)
        self.assertEqual(self.client.delete(f"/api/links/{first['id']}", headers=owner).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/links/{first['id']}", headers=owner).status_code, 404)

    def test_link_page_sends_session_for_the_owner(self):
        owner = self.login("Hilay")
        token = self.make_link(owner, operator="Serviceiro Bom", max_uses=2)["token"]
        info = self.client.post("/api/link/info", json={"token": token})
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json()["character"], "Hilay")
        self.assertNotIn("owner_key", info.text)
        r = self.client.post("/api/link/send", json={"token": token, "raw_text": self.recent(SOLO)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["saved"], r.json()["uses_left"]), ("stacker", 1))
        again = self.client.post("/api/link/send", json={"token": token, "raw_text": self.recent(SOLO)})
        self.assertFalse(again.json()["created"])
        self.assertEqual(again.json()["uses_left"], 1)  # o que já estava salvo não gasta envio
        # no Stacker do dono: dele (pode apagar), marcada como jogada por outra pessoa e fora do recorde
        d = self.client.get("/api/stacker/Hilay", headers=owner).json()
        s = d["sessions"][0]
        self.assertTrue(s["can_delete"])
        self.assertEqual((s["other_player"], s["played_by"], s["via"]), (1, "Serviceiro Bom", "link"))
        self.assertEqual(d["records"], [])
        self.assertEqual(self.client.get("/api/me", headers=owner).json()["link_sends"], 1)
        # hunt antiga não passa pelo link
        old = self.client.post("/api/link/send", json={"token": token, "raw_text": SOLO.replace("2026-11-04", "2020-01-01")})
        self.assertEqual(old.status_code, 422)

    def test_link_page_lootsplit_and_limits(self):
        owner = self.login("Hilay")
        token = self.make_link(owner, max_uses=1, scopes=["party"])["token"]
        r = self.client.post("/api/link/send", json={"token": token, "raw_text": self.recent(EXAMPLE)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["saved"], "lootsplit")
        hunt = self.client.get("/api/hunts/Hilay", headers=owner).json()["hunts"][0]
        self.assertTrue(hunt["can_delete"])  # o lootsplit é do dono
        self.assertTrue(hunt["tags"]["Hilay"]["other"])
        # limite de envios
        r = self.client.post("/api/link/send", json={"token": token, "raw_text": self.recent(SOLO)})
        self.assertEqual(r.status_code, 410)
        # link cancelado / inventado
        token2 = self.make_link(owner, scopes=["solo"])["token"]
        r = self.client.post("/api/link/send", json={"token": token2, "raw_text": self.recent(EXAMPLE)})
        self.assertEqual(r.status_code, 403)  # esse link não aceita lootsplit
        link_id = self.client.get("/api/subs", headers=owner).json()["links"][0]["id"]
        self.client.delete(f"/api/links/{link_id}", headers=owner)
        self.assertEqual(self.client.post("/api/link/info", json={"token": token2}).status_code, 410)
        self.assertEqual(self.client.post("/api/link/info", json={"token": "x" * 32}).status_code, 404)

    def test_link_page_needs_captcha(self):
        owner = self.login("Hilay")
        token = self.make_link(owner)["token"]
        with mock.patch.object(server.captcha, "verify", side_effect=server.captcha.CaptchaError("x")):
            r = self.client.post("/api/link/send", json={"token": token, "raw_text": self.recent(SOLO)})
        self.assertEqual(r.status_code, 400)

    # ---------------------------------------------------------------- jogador autorizado
    def test_authorized_player_uploads_for_the_owner(self):
        owner = self.login("Hilay")
        op = self.login("Serviceiro Bom")
        self.make_link(owner, operator="Serviceiro Bom", max_uses=5)
        grants = self.client.get("/api/subs", headers=op).json()["grants"]
        self.assertEqual([(g["character"], g["as"]) for g in grants], [("Hilay", "Serviceiro Bom")])
        # lootsplit da PT de Hilay enviado pelo serviceiro logado na conta dele
        r = self.client.post("/api/lootsplit", json={"raw_text": self.recent(EXAMPLE), "nickname": "Serviceiro Bom"}, headers=op)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["for_owner"])
        self.assertFalse(r.json()["hunt"]["can_delete"])
        hunt = self.client.get("/api/hunts/Hilay", headers=owner).json()["hunts"][0]
        self.assertTrue(hunt["can_delete"])
        self.assertEqual(hunt["tags"]["Hilay"]["played_by"], "Serviceiro Bom")
        # sessão do Stacker: vai para Hilay, nunca para o serviceiro
        r = self.client.post("/api/stacker", json={"raw_text": self.recent(SOLO).replace("18:50:49", "21:00:00"),
                                                   "nickname": "Serviceiro Bom", "for_char": "Hilay"}, headers=op)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["saved_as"], "Hilay")
        self.assertEqual(self.client.get("/api/stacker/Serviceiro Bom", headers=op).json()["sessions"], [])
        played = self.client.get("/api/subs", headers=op).json()["played"]
        self.assertEqual({p["kind"] for p in played}, {"solo", "hunt"})
        # sem autorização: recusado
        stranger = self.login("Outro Qualquer")
        r = self.client.post("/api/stacker", json={"raw_text": SOLO, "nickname": "Outro Qualquer", "for_char": "Hilay"},
                             headers=stranger)
        self.assertEqual(r.status_code, 403)

    # ---------------------------------------------------------------- marcações e assumir
    def test_tags_and_claim(self):
        hilay = self.login("Hilay")
        jioe = self.login("Jioe")
        r = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=hilay)
        hid = r.json()["hunt"]["id"]
        # Jioe marca que outra pessoa jogou no personagem dele; não pode marcar o de Hilay
        r = self.client.post(f"/api/hunt/{hid}/tags", json={"name": "Jioe", "other": True, "played_by": "Amigo Do Jioe"}, headers=jioe)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["hunt"]["tags"]["Jioe"]["played_by"], "Amigo Do Jioe")
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/tags", json={"name": "Hilay", "other": True}, headers=jioe).status_code, 403)
        # substituto: qualquer um da PT marca; quem não estava na PT, não
        r = self.client.post(f"/api/hunt/{hid}/tags", json={"name": "Vcte", "sub": "yes"}, headers=jioe)
        self.assertEqual(r.json()["hunt"]["tags"]["Vcte"]["sub"], {"auto": False, "for": None})
        fora = self.login("Fulano Fora")
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/tags", json={"name": "Vcte", "sub": "no"}, headers=fora).status_code, 403)
        # lootsplit antigo enviado por quem não estava na PT: um membro assume
        server.store._conn.execute("UPDATE hunts SET uploader_key = ? WHERE id = ?", (fora["X-Access-Key"], hid))
        server.store._conn.commit()
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/rules", json={"excluded": ["Jioe"]}, headers=fora).status_code, 403)
        seen = self.client.get("/api/hunts/Jioe", headers=jioe).json()["hunts"][0]
        self.assertTrue(seen["can_claim"])
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/claim", headers=fora).status_code, 403)
        r = self.client.post(f"/api/hunt/{hid}/claim", headers=jioe)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["hunt"]["can_delete"])
        self.assertEqual(self.client.post(f"/api/hunt/{hid}/claim", headers=hilay).status_code, 409)

    def test_manual_not_substitute_is_kept(self):
        hilay = self.login("Hilay")
        hid = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": "Hilay"}, headers=hilay).json()["hunt"]["id"]
        r = self.client.post(f"/api/hunt/{hid}/tags", json={"name": "Jioe", "sub": "no"}, headers=hilay)
        self.assertEqual(r.json()["hunt"]["tags"]["Jioe"]["sub_manual"], "nosub")
        r = self.client.post(f"/api/hunt/{hid}/tags", json={"name": "Jioe", "sub": "auto"}, headers=hilay)
        self.assertNotIn("Jioe", r.json()["hunt"]["tags"])

    def test_link_session_joins_the_party_lootsplit(self):
        owner = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "comum"}, headers=owner)
        self.client.post("/api/lootsplit", json={"raw_text": self.recent(EXAMPLE), "nickname": "Hilay"}, headers=owner)
        token = self.make_link(owner)["token"]
        r = self.client.post("/api/link/send", json={"token": token, "raw_text": self.recent(PARTY_SESSION)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["saved"], "party_session")
        hunt = self.client.get("/api/hunts/Hilay", headers=owner).json()["hunts"][0]
        self.assertTrue(hunt["member_sessions"][0]["other_player"])

    def test_auto_substitute(self):
        rosters = {1: {"a": "A", "b": "B", "c": "C"}, 2: {"a": "A", "b": "B", "c": "C"}, 3: {"a": "A", "b": "B", "c": "C"}}
        self.assertEqual(server._auto_subs(["A", "B", "S"], 9, rosters), {"S": "C"})
        self.assertEqual(server._auto_subs(["A", "B", "C"], 9, rosters), {})          # a PT de sempre
        self.assertEqual(server._auto_subs(["A", "X", "Y"], 9, rosters), {})          # PT diferente
        self.assertEqual(server._auto_subs(["A", "B", "S"], 9, {1: rosters[1]}), {})  # pouco histórico
        # com lootsplits de verdade: 2 hunts da PT de sempre e 1 com substituto
        hilay = self.login("Hilay")
        for day in ("2026-11-01", "2026-11-02"):
            self.client.post("/api/lootsplit", json={"raw_text": party_text(day), "nickname": "Hilay"}, headers=hilay)
        sub = party_text("2026-11-03").replace("Jioe", "Reserva")
        r = self.client.post("/api/lootsplit", json={"raw_text": sub, "nickname": "Hilay"}, headers=hilay)
        self.assertEqual(r.json()["hunt"]["tags"]["Reserva"]["sub"], {"auto": True, "for": "Jioe"})

    def test_ranking_and_place_stats_skip_other_player(self):
        h = self.login("Hilay")
        self.client.post("/api/ranking/Hilay", json={"join": True}, headers=h)
        r = self.client.post("/api/stacker", json={"raw_text": SOLO.replace("2026-11-04", utcnow().date().isoformat()),
                                                   "nickname": "Hilay"}, headers=h)
        sid = r.json()["session"]["id"]
        rank = lambda q="": self.client.get(f"/api/ranking?period=7{q}", headers=h).json()["rows"][0]["xp"]  # noqa: E731
        self.assertGreater(rank(), 0)
        r = self.client.post(f"/api/stacker/session/{sid}/player", json={"other": True, "played_by": "Amigo"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(rank(), 0)
        self.assertGreater(rank("&others=1"), 0)
        other = self.login("Jioe")
        self.assertEqual(self.client.post(f"/api/stacker/session/{sid}/player", json={"other": False}, headers=other).status_code, 403)

    def test_owner_is_warned_when_someone_tries_to_link_his_char(self):
        h = self.login("Hilay")
        intruder = server.store.create_key(30, "intruso")["key"]
        r = self.client.post("/api/verify/start", json={"character": "Hilay"}, headers={"X-Access-Key": intruder})
        self.assertEqual(r.status_code, 409)
        claims = self.client.get("/api/me", headers=h).json()["char_claims"]
        self.assertEqual([c["name_key"] for c in claims], ["hilay"])

    def test_link_page_is_served_without_token_in_path(self):
        r = self.client.get("/envio")
        self.assertEqual(r.status_code, 200)
        self.assertIn('src="/envio.js"', r.text)
        self.assertEqual(self.client.get("/envio.js").status_code, 200)

    def test_link_page_texts_are_translated(self):
        import json
        from pathlib import Path

        from tests.test_i18n import SAME, _Texts

        class Texts(_Texts):  # o que tem translate="no" não é traduzido (logo, rodapé)
            def handle_starttag(self, tag, attrs):
                if dict(attrs).get("translate") == "no" or self.lang_skip:
                    self.lang_skip += 1
                super().handle_starttag(tag, attrs)

            def handle_endtag(self, tag):
                if self.lang_skip:
                    self.lang_skip -= 1
                super().handle_endtag(tag)

            def handle_data(self, d):
                if not self.lang_skip:
                    super().handle_data(d)

        web = Path(server.WEB_DIR)
        p = Texts()
        p.feed((web / "envio.html").read_text(encoding="utf-8"))
        en = json.loads((web / "i18n-en.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(t for t in p.out if t not in en and t not in SAME), [])

    def test_tokens_are_not_stored(self):
        owner = self.login("Hilay")
        token = self.make_link(owner)["token"]
        rows = server.store._conn.execute("SELECT token_hash FROM upload_links").fetchall()
        self.assertTrue(all(token not in r[0] for r in rows))
        self.assertTrue(rows[0][0].startswith("sha256:"))
        # vencido não vale
        server.store._conn.execute("UPDATE upload_links SET expires_at = ?", (_iso(utcnow() - timedelta(minutes=1)),))
        server.store._conn.commit()
        self.assertEqual(self.client.post("/api/link/info", json={"token": token}).status_code, 410)


if __name__ == "__main__":
    unittest.main()
