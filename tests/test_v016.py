"""0.16.0: contas com senha antes da chave, bloqueio por senha errada, vínculo conta↔chave e pedidos de recuperação."""
import secrets
import unittest

import tests  # noqa: F401  # isola o banco: precisa vir antes de importar o servidor
from artemis.server import app as server
from tests import test_server as ts


class V016Tests(unittest.TestCase):
    setUp = ts.ServerTests.setUp
    h = ts.ServerTests.h
    verify = ts.ServerTests.verify
    admin = property(lambda self: {"X-Admin-Token": server.CONFIG["admin_token"]})

    def tearDown(self):
        ts.ServerTests.tearDown(self)
        server._login_fails.clear()
        server._login_blocked.clear()

    def register(self, name=None, pw="Senha_1!"):
        name = name or "conta" + secrets.token_hex(4)
        r = self.client.post("/api/account/register", json={"username": name, "password": pw, "confirm": pw})
        self.assertEqual(r.status_code, 200, r.text)
        return name, r.json()

    def test_register_rules(self):
        bad_names = ["ab", "com espaço", "joão", "nome_com", "x" * 21]
        for n in bad_names:
            r = self.client.post("/api/account/register", json={"username": n, "password": "senha123"})
            self.assertEqual(r.status_code, 422, n)
        for pw in ["12345", "tem espaço", "sem#cerquilha", "ação123"]:
            r = self.client.post("/api/account/register", json={"username": "valido1", "password": pw})
            self.assertEqual(r.status_code, 422, pw)
        r = self.client.post("/api/account/register", json={"username": "valido1", "password": "a_b!c@d-1", "confirm": "outra"})
        self.assertEqual(r.status_code, 422)
        name, acc = self.register(pw="a_b!c@d-1")
        self.assertIsNone(acc["key"])
        r = self.client.post("/api/account/register", json={"username": name.upper(), "password": "senha123"})
        self.assertEqual(r.status_code, 409)
        row = server.store._conn.execute("SELECT pw_hash FROM accounts WHERE username = ?", (name,)).fetchone()
        self.assertNotIn("a_b!c@d-1", row[0])

    def test_login_wrong_password_and_block(self):
        name, _ = self.register()
        r = self.client.post("/api/account/login", json={"username": name, "password": "errada1"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"]["message"], "Conta/Senha incorreta(s).")
        # conta que não existe: mesma mensagem (não dá para saber qual dos dois errou)
        r = self.client.post("/api/account/login", json={"username": "naoexiste99", "password": "errada1"})
        self.assertEqual(r.json()["detail"]["message"], "Conta/Senha incorreta(s).")
        ok = self.client.post("/api/account/login", json={"username": name.upper(), "password": "Senha_1!"})
        self.assertEqual(ok.status_code, 200)
        for _ in range(server.LOGIN_FAIL_LIMIT - 1):
            self.assertEqual(self.client.post("/api/account/login", json={"username": name, "password": "errada1"}).status_code, 401)
        self.assertEqual(self.client.post("/api/account/login", json={"username": name, "password": "errada1"}).status_code, 429)
        # bloqueado: nem a senha certa entra, do mesmo IP
        r = self.client.post("/api/account/login", json={"username": name, "password": "Senha_1!"})
        self.assertEqual(r.status_code, 429)
        # outro IP continua podendo entrar
        r = self.client.post("/api/account/login", json={"username": name, "password": "Senha_1!"},
                             headers={"X-Forwarded-For": "7.7.7.7"})
        self.assertEqual(r.status_code, 200)

    def test_link_key_then_login_enters_directly(self):
        name, acc = self.register()
        a = {"X-Account-Token": acc["token"]}
        token = self.verify("Hilay")[1].json()["token"]
        self.assertEqual(self.client.post("/api/account/link", headers={**self.h(token)}).status_code, 401)  # sem conta
        r = self.client.post("/api/account/link", headers={**self.h(token), **a})
        self.assertEqual(r.status_code, 200, r.text)
        # aparelho novo: só conta + senha, sem código de verificação
        r = self.client.post("/api/account/login", json={"username": name, "password": "Senha_1!"}).json()
        self.assertEqual(r["key"], self.key)
        self.assertTrue(r["device_token"])
        me = self.client.get("/api/me", headers={"X-Access-Key": r["key"], "X-Device-Token": r["device_token"]})
        self.assertEqual(me.json()["main_char"], "Hilay")
        # reabrir com o mesmo aparelho reaproveita o token
        again = self.client.post("/api/account/resume", json={"device_token": r["device_token"]},
                                 headers={"X-Account-Token": r["token"]}).json()
        self.assertEqual(again["device_token"], r["device_token"])
        # outra conta não pega a mesma chave
        _, other = self.register()
        o = {"X-Account-Token": other["token"]}
        auth = self.client.post("/api/auth", headers={"X-Access-Key": self.key, **o}).json()
        self.assertTrue(auth["other_account"])
        r = self.client.post("/api/account/link", headers={**self.h(token), **o})
        self.assertEqual(r.status_code, 409)
        # sair encerra a sessão da conta
        self.client.post("/api/account/logout", headers=a)
        self.assertEqual(self.client.post("/api/account/resume", json={}, headers=a).status_code, 401)

    def test_recovery_requests_for_admin(self):
        _, acc = self.register()
        a = {"X-Account-Token": acc["token"]}
        self.assertEqual(self.client.post("/api/recovery", json={"whatsapp": "21999998888", "reason": "lost_code"}).status_code, 401)
        self.assertEqual(self.client.post("/api/recovery", json={"whatsapp": "123", "reason": "lost_code"}, headers=a).status_code, 422)
        self.assertEqual(self.client.post("/api/recovery", json={"whatsapp": "21999998888", "reason": "x"}, headers=a).status_code, 422)
        r = self.client.post("/api/recovery", json={"whatsapp": "(21) 99999-8888", "reason": "char_taken", "character": "Hilay"},
                             headers=a)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/api/admin/recovery").status_code, 401)
        items = self.client.get("/api/admin/recovery", headers=self.admin).json()
        mine = [x for x in items if x["account_id"] == acc_id(acc)]
        self.assertEqual(mine[0]["whatsapp"], "21999998888")
        self.assertEqual(mine[0]["reason_label"], "Código de acesso: personagem já tem código")
        self.assertEqual(mine[0]["kind"], "code")
        r = self.client.post(f"/api/admin/recovery/{mine[0]['id']}/done", headers=self.admin)
        self.assertEqual(r.status_code, 200)
        items = self.client.get("/api/admin/recovery", headers=self.admin).json()
        self.assertNotIn(mine[0]["id"], [x["id"] for x in items])


def acc_id(acc):
    return server.store.account_by_token(acc["token"])["id"]


if __name__ == "__main__":
    unittest.main()
