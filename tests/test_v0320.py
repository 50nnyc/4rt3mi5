"""0.32.0: painel único do personagem (solo + party)."""
import unittest

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.core import imbuing
from artemis.core.session import parse_solo_session
from artemis.server import app as server
from tests import test_bosses as tb
from tests.test_core import EXAMPLE
from tests.test_revamp import solo


class PainelUnicoTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _party(self, who, headers):
        hunt = self.client.post("/api/lootsplit", json={"raw_text": EXAMPLE, "nickname": who}, headers=headers).json()["hunt"]
        data = parse_solo_session(solo(7)).to_dict()
        server.store.add_party_session(hunt["id"], who, data, "k")
        return hunt["id"], data

    def test_soma_solo_e_party(self):
        h = self.login("Hilay")
        self.client.post("/api/stacker", json={"raw_text": solo(2), "nickname": "Hilay"}, headers=h)
        hid, data = self._party("Hilay", h)
        todos = self.client.get("/api/stacker/Hilay?source=all", headers=h).json()
        so = self.client.get("/api/stacker/Hilay?source=solo", headers=h).json()
        pt = self.client.get("/api/stacker/Hilay?source=party", headers=h).json()
        self.assertEqual(todos["counts"], {"solo": 1, "party": 1})
        self.assertEqual(len(so["sessions"]), 1)
        self.assertEqual(len(pt["sessions"]), 1)
        self.assertEqual(pt["sessions"][0]["source"], "party")
        self.assertEqual(pt["sessions"][0]["id"], -hid)
        self.assertEqual(todos["lifetime"]["xp"], so["lifetime"]["xp"] + pt["lifetime"]["xp"])
        # na party vale o rateio do lootsplit
        self.assertEqual(pt["sessions"][0]["net_profit"], pt["sessions"][0]["profit_each"])

    def test_mesma_sessao_como_solo_e_party_conta_uma_vez(self):
        h = self.login("Hilay")
        self.client.post("/api/stacker", json={"raw_text": solo(7), "nickname": "Hilay"}, headers=h)
        self._party("Hilay", h)
        todos = self.client.get("/api/stacker/Hilay", headers=h).json()
        self.assertEqual(todos["counts"], {"solo": 1, "party": 0})

    def test_outro_jogador_nao_ve_loot_nem_lucro_da_party(self):
        h, j = self.login("Hilay"), self.login("Jioe")
        self._party("Hilay", h)
        d = self.client.get("/api/stacker/Hilay?source=party", headers=j).json()
        s = d["sessions"][0]
        for k in ("kills", "loot", "net_profit", "profit_each", "hunt_id"):
            self.assertNotIn(k, s)


def an(start, end, session, xp, balance=100_000):
    return f"""Session data: From 2026-11-10, {start} to 2026-11-10, {end}
Session: {session}h
Raw XP Gain: {xp}
XP Gain: {xp}
Loot: {balance + 50_000}
Supplies: 50,000
Balance: {balance:,}
Damage: 1,000,000
Damage/h: 1,000,000
Healing: 200,000
Healing/h: 200,000
Killed Monsters:
  10x rat
Looted Items:
  2x platinum coins
"""


class SessaoAoVivoTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _hardcore(self, name="Hilay"):
        h = self.login(name)
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        return h

    def send(self, h, text, **kw):
        return self.client.post("/api/live", json={"raw_text": text, "nickname": "Hilay", **kw}, headers=h)

    def test_so_hardcore(self):
        h = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "comum"}, headers=h)
        self.assertEqual(self.send(h, an("10:00:00", "10:15:00", "00:15", 100_000)).status_code, 403)

    def test_cada_envio_completa_o_anterior(self):
        h = self._hardcore()
        r1 = self.send(h, an("10:00:00", "10:15:00", "00:15", 100_000)).json()
        self.assertTrue(r1["created"])
        sid = r1["live"]["session"]["id"]
        # pulou o envio das 10:30; o das 10:45 já traz tudo
        r2 = self.send(h, an("10:00:00", "10:45:00", "00:45", 450_000)).json()
        self.assertFalse(r2["created"])
        self.assertEqual(r2["live"]["session"]["id"], sid)
        self.assertEqual(r2["live"]["session"]["xp"], 450_000)
        pts = r2["live"]["points"]
        self.assertEqual([p["xp"] for p in pts], [100_000, 450_000])
        self.assertEqual(pts[1]["interval_seconds"], 30 * 60)
        self.assertEqual(pts[1]["xp_h"], 700_000)  # 350 mil em meia hora
        # um envio atrasado (menor) não faz o total voltar
        r3 = self.send(h, an("10:00:00", "10:30:00", "00:30", 300_000)).json()
        self.assertFalse(r3["advanced"])
        self.assertEqual(r3["live"]["session"]["xp"], 450_000)
        self.assertEqual(len(r3["live"]["points"]), 3)
        # só uma sessão no painel
        d = self.client.get("/api/stacker/Hilay", headers=h).json()
        self.assertEqual(len(d["sessions"]), 1)

    def test_analisador_reiniciado_pergunta_antes(self):
        h = self._hardcore()
        self.send(h, an("10:00:00", "10:15:00", "00:15", 100_000))
        r = self.send(h, an("11:00:00", "11:15:00", "00:15", 80_000))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["reason"], "live_reset")
        r = self.send(h, an("11:00:00", "11:15:00", "00:15", 80_000), confirm=True)
        self.assertEqual(r.status_code, 200, r.text)
        d = self.client.get("/api/stacker/Hilay", headers=h).json()
        self.assertEqual(len(d["sessions"]), 2)  # a anterior ficou como estava

    def test_envio_normal_da_mesma_sessao_continua_a_ao_vivo(self):
        h = self._hardcore()
        self.send(h, an("10:00:00", "10:15:00", "00:15", 100_000))
        r = self.client.post("/api/stacker", json={"raw_text": an("10:00:00", "10:50:00", "00:50", 500_000), "nickname": "Hilay"},
                             headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        d = self.client.get("/api/stacker/Hilay", headers=h).json()
        self.assertEqual(len(d["sessions"]), 1)
        self.assertEqual(d["sessions"][0]["xp"], 500_000)


VAMP = {"Vampire Teeth": 492, "Bloody Pincers": 16787, "Piece of Dead Brain": 29996}
VOID = {"Rope Belt": 3500, "Silencer Claws": 3883, "Some Grimeleech Wings": 2496}


class ImbuingCoreTests(unittest.TestCase):
    def plan(self, key, tier, prices, token=45_700):
        return imbuing.best_plan(key, tier, prices, token)

    def test_vampirism_do_exemplo(self):
        p1, p2, p3 = (self.plan("vampirism", t, VAMP) for t in (1, 2, 3))
        self.assertEqual([o["cost"] for o in p3["options"]], [414_085, 493_185, 332_780, 274_200])
        self.assertEqual(p1["best"]["cost"], 12_300)
        self.assertEqual(p1["best"]["token_levels"], 0)
        self.assertEqual(p2["best"]["token_levels"], 2)
        self.assertEqual(p2["best"]["cost"], 182_800)
        self.assertEqual(p3["best"]["token_levels"], 3)
        self.assertEqual(p3["best"]["cost"], 274_200)
        self.assertEqual(p3["total"], 274_200 + imbuing.SHRINE_FEE[3])

    def test_void_mistura_token_nos_primeiros_niveis(self):
        p3 = self.plan("void", 3, VOID)
        by = {o["token_levels"]: o["cost"] for o in p3["options"]}
        self.assertEqual(by[0], 197_055)
        self.assertEqual(by[2], 195_280)
        self.assertEqual(p3["best"]["token_levels"], 2)
        self.assertEqual(self.plan("void", 1, VOID)["best"]["token_levels"], 0)
        self.assertEqual(self.plan("void", 2, VOID)["best"]["cost"], 182_800)  # token por pouco (184.575 no market)
        self.assertIn("4 gold tokens", p3["advice"])

    def test_sem_token_so_market(self):
        p = imbuing.best_plan("bash", 3, {"Cyclops Toe": 100, "Ogre Nose Ring": 100, "Warmaster's Wristguards": 1000}, 45_700)
        self.assertEqual(p["best"]["token_levels"], 0)
        self.assertFalse(p["token_eligible"])
        self.assertEqual(p["best"]["cost"], 20 * 100 + 15 * 100 + 10 * 1000)

    def test_falta_preco(self):
        p = imbuing.best_plan("bash", 2, {"Cyclops Toe": 100}, 45_700)
        self.assertIsNone(p["total"])
        self.assertEqual(p["missing"], ["Ogre Nose Ring"])

    def test_custo_por_uso(self):
        self.assertEqual(imbuing.use_cost(1_000_000, 2), 100_000)  # 2 h = 10% das 20 h
        self.assertEqual(imbuing.use_cost(1_000_000, 21), 1_050_000)  # 1 inteiro + 5%

    def test_regras_de_quem_aceita(self):
        ok = imbuing.check_imbue
        self.assertIsNone(ok("armor", 3, [], [], "vampirism", 3))
        self.assertIsNone(ok("armor", 3, [], ["vampirism"], "quara_scale", 3))
        self.assertIn("não repete", ok("armor", 3, [], ["quara_scale"], "quara_scale", 3))
        self.assertIn("já traz", ok("armor", 3, ["quara_scale"], [], "quara_scale", 3))
        self.assertIn("slots", ok("armor", 2, [], ["vampirism", "quara_scale"], "snake_skin", 3))
        self.assertIsNotNone(ok("shield", 2, [], [], "vampirism", 3))  # escudo só proteção
        self.assertIsNotNone(ok("helmet_mage", 2, [], [], "slash", 3))  # elmo de mage: só Magic Level (e Void)
        self.assertIsNone(ok("helmet_mage", 2, [], [], "epiphany", 3))
        self.assertIsNotNone(ok("helmet", 2, [], [], "epiphany", 3))  # Magic Level só até o Intricate
        self.assertIsNone(ok("helmet", 2, [], [], "epiphany", 2))
        self.assertIsNone(ok("sword", 3, [], [], "scorch", 3))  # arma aceita dano elemental
        self.assertIsNotNone(ok("sword", 3, ["vampirism"], [], "vampirism", 3))  # arma com life leech

    def test_media_descarta_exagero(self):
        self.assertEqual(imbuing.average_price([100, 110, 90]), 100)
        self.assertEqual(imbuing.average_price([100, 100, 100, 100, 5000]), 100)
        self.assertIsNone(imbuing.average_price([]))

    def test_catalogo_bate_com_as_tabelas(self):
        self.assertEqual([m["qty"] for m in imbuing.CATALOG["vampirism"]["materials"]], [25, 15, 5])
        self.assertEqual([m["item"] for m in imbuing.CATALOG["void"]["materials"]],
                         ["Rope Belt", "Silencer Claws", "Some Grimeleech Wings"])
        self.assertEqual(imbuing.ACCESSORIES["sleep_shawl"]["minutes"], 60)
        self.assertEqual(imbuing.ACCESSORIES["turtle"]["silver_tokens"], 2)


class EquipamentosApiTests(unittest.TestCase):
    setUp = tb.BossServerTests.setUp
    tearDown = tb.BossServerTests.tearDown
    login = tb.BossServerTests.login

    def _hardcore(self, name="Hilay"):
        h = self.login(name)
        self.client.post("/api/prefs/player-type", json={"player_type": "hardcore"}, headers=h)
        return h

    def test_so_hardcore(self):
        h = self.login("Hilay")
        self.client.post("/api/prefs/player-type", json={"player_type": "comum"}, headers=h)
        self.assertEqual(self.client.get("/api/gear/Hilay", headers=h).status_code, 403)

    def test_fluxo_completo(self):
        h = self._hardcore()
        g = lambda path, **kw: self.client.get(f"/api/gear/Hilay{path}", headers=h, **kw)
        post = lambda path, body=None: self.client.post(f"/api/gear/Hilay{path}", json=body or {}, headers=h)
        # preços padrão já vêm preenchidos (média do Celebra de 24/11/2026)
        d = g("").json()
        self.assertEqual(d["prices"]["Vampire Teeth"]["effective"], 492)
        self.assertEqual(d["prices"]["gold token"]["effective"], 45_700)
        post("/price", {"item": "Vampire Teeth", "price": 500})
        self.assertEqual(g("").json()["prices"]["Vampire Teeth"]["effective"], 500)
        # armadura com 3 slots: Vampirism + proteção
        r = post("/item", {"name": "Magic Plate Armor", "kind": "armor", "slots": 3})
        gid = r.json()["items"][0]["id"]
        self.assertEqual(post(f"/item/{gid}/imbue", {"imbuement": "vampirism", "tier": 3}).status_code, 200)
        self.assertEqual(post(f"/item/{gid}/imbue", {"imbuement": "vampirism", "tier": 3}).status_code, 422)  # não repete
        self.assertEqual(post(f"/item/{gid}/imbue", {"imbuement": "slash", "tier": 3}).status_code, 422)  # armadura não aceita
        items = g("").json()["items"]
        c = items[0]["charges"][0]
        self.assertEqual(c["imbuement"], "vampirism")
        self.assertEqual(c["total_cost"], c["plan"]["total"])
        # set + liga a uma sessão solo de 1h (2 h = 10%: aqui a sessão de exemplo)
        sid = self.client.post("/api/stacker", json={"raw_text": solo(5), "nickname": "Hilay"}, headers=h).json()["session"]["id"]
        before = self.client.get("/api/stacker/Hilay", headers=h).json()["sessions"][0]["net_profit"]
        st = post("/set", {"name": "Set Crypts", "gear_ids": [gid]}).json()["sets"][0]
        a = post("/assign", {"kind": "solo", "ref_id": sid, "set_id": st["id"], "pause_minutes": 0}).json()
        self.assertGreater(a["cost"], 0)
        s = self.client.get("/api/stacker/Hilay", headers=h).json()["sessions"][0]
        self.assertEqual(s["gear_cost"], a["cost"])
        self.assertEqual(s["net_profit"], before - a["cost"])
        self.assertEqual(s["gear"]["set_name"], "Set Crypts")
        # pausa desconta do tempo; trocar de set refaz a conta sem acumular
        full = a["hours"]
        a2 = post("/assign", {"kind": "solo", "ref_id": sid, "set_id": st["id"], "pause_minutes": 15}).json()
        self.assertAlmostEqual(a2["hours"], full - 0.25, places=2)
        c = g("").json()["items"][0]["charges"][0]
        self.assertAlmostEqual(c["hours_used"], a2["hours"], places=2)
        # outro jogador não vê nada disso
        j = self._hardcore("Jioe")
        d = self.client.get("/api/stacker/Hilay", headers=j).json()
        self.assertNotIn("gear_cost", d["sessions"][0])
        # relatório semanal
        rep = g("/report").json()
        self.assertEqual(len(rep["pending"]), 1)
        self.assertTrue(rep["weeks"])
        # reiniciar o contador com horas extras entra no custo e zera o ciclo
        cid = c["id"]
        r = post(f"/charge/{cid}/restart", {"hours": 2})
        self.assertEqual(r.status_code, 200, r.text)
        new = r.json()["items"][0]["charges"][0]
        self.assertNotEqual(new["id"], cid)
        self.assertEqual(new["hours_used"], 0)
        manual = [u for w in g("/report").json()["weeks"] for u in w["items"]]
        self.assertTrue(manual)
        # apagar a sessão devolve as horas
        self.client.delete(f"/api/stacker/session/{sid}", headers=h)

    def test_anel_com_silver_token(self):
        h = self._hardcore()
        r = self.client.post("/api/gear/Hilay/item", json={"name": "x", "kind": "ring", "catalog": "spiritthorn"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        gid = r.json()["items"][0]["id"]
        r = self.client.post(f"/api/gear/Hilay/item/{gid}/recharge", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        c = r.json()["items"][0]["charges"][0]
        self.assertEqual(c["total_cost"], 5 * 45_848)
        self.assertEqual(c["hours_total"], 3)
        self.assertEqual(self.client.post(f"/api/gear/Hilay/item/{gid}/recharge", headers=h).status_code, 409)


if __name__ == "__main__":
    unittest.main()
