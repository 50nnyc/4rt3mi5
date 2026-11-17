"""Servidor e administração do 4rt3mi5.

    python -m artemis.server                         inicia o servidor
    python -m artemis.server keys create --days 30 --label "Atx Buubo"
    python -m artemis.server keys list
    python -m artemis.server keys revoke ART-XXXX-XXXX
    python -m artemis.server guest CONTA SENHA --char "Nome"   conta de visitante (só visualização)
    python -m artemis.server hunts delete 12
    python -m artemis.server stacker delete 7
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="artemis.server")
    sub = p.add_subparsers(dest="cmd")
    keys = sub.add_parser("keys", help="chaves de acesso").add_subparsers(dest="action", required=True)
    c = keys.add_parser("create", help="criar chave (máx. 30 dias)")
    c.add_argument("--days", type=int, default=30)
    c.add_argument("--label", default="", help="para quem é a chave")
    keys.add_parser("list", help="listar chaves válidas")
    r = keys.add_parser("revoke", help="apagar uma chave")
    r.add_argument("key")
    rn = keys.add_parser("renew", help="renovar validade (a partir de hoje) mantendo personagens")
    rn.add_argument("key")
    rn.add_argument("--days", type=int, default=30)
    rs = keys.add_parser("reset", help="desvincular dono (personagens e aparelhos)")
    rs.add_argument("key")
    sub.add_parser("admin-token", help="mostrar a senha do painel de administração")
    g = sub.add_parser("guest", help="criar/atualizar a conta de visitante (só visualização)")
    g.add_argument("username")
    g.add_argument("password")
    g.add_argument("--char", required=True, help="personagem que abre as telas (não passa a ser do visitante)")
    for name in ("hunts", "stacker"):
        d = sub.add_parser(name).add_subparsers(dest="action", required=True).add_parser("delete")
        d.add_argument("id", type=int)
    args = p.parse_args(argv)

    from .app import CONFIG, CONFIG_PATH, app, store

    if args.cmd == "keys":
        store.purge_expired()
        if args.action == "create":
            try:
                k = store.create_key(args.days, args.label)
            except ValueError as e:
                sys.exit(str(e))
            print(f"Chave criada: {k['key']}   (vale até {_local(k['expires_at'])})  {k['label']}")
        elif args.action == "list":
            rows = store.list_keys()
            if not rows:
                print("Nenhuma chave válida.")
            for k in rows:
                chars = ", ".join(c["name"] for c in store.key_chars(k["key"])) or "não verificada"
                print(f"{k['key']}   vence {_local(k['expires_at'])}   {k['label']}   main: {k['main_char'] or '-'}   chars: {chars}")
        elif args.action == "renew":
            try:
                k = store.renew_key(args.key, args.days)
            except ValueError as e:
                sys.exit(str(e))
            print(f"Renovada até {_local(k['expires_at'])}." if k else "Chave não encontrada (ou já vencida e apagada).")
        elif args.action == "reset":
            store.reset_key(args.key)
            print("Dono desvinculado: a pessoa vai verificar o main character de novo.")
        else:
            print("Chave apagada." if store.revoke_key(args.key) else "Chave não encontrada.")
        return
    if args.cmd == "admin-token":
        print(f"Painel: http://localhost:{CONFIG['port']}/admin")
        print(f"Senha:  {CONFIG['admin_token']}")
        return
    if args.cmd == "guest":
        from .app import PASSWORD_RE, USERNAME_RE
        if not USERNAME_RE.fullmatch(args.username) or not PASSWORD_RE.fullmatch(args.password):
            sys.exit("Conta: 3 a 20 letras/números. Senha: 6 a 64 caracteres (letras, números e _ ! @ -).")
        try:
            g = store.setup_guest(args.username, args.password, args.char)
        except ValueError as e:
            sys.exit(str(e))
        print(f"Conta de visitante pronta: {g['username']} (só visualização; personagem das telas: {g['main_char']}).")
        return
    if args.cmd == "hunts":
        print("Hunt apagada." if store.delete_hunt(args.id) else "Hunt não encontrada.")
        return
    if args.cmd == "stacker":
        print("Sessão apagada." if store.delete_solo(args.id) else "Sessão não encontrada.")
        return

    import uvicorn

    store.purge_expired()
    print("=" * 60)
    print(" 4rt3mi5 - servidor")
    print(f" Site:   http://localhost:{CONFIG['port']}/")
    print(f" Painel: http://localhost:{CONFIG['port']}/admin   (senha: {CONFIG['admin_token']})")
    print(f" Config: {CONFIG_PATH}")
    print(f" Chaves válidas: {len(store.list_keys())}  (crie com: admin.bat create \"Nome\")")
    print("=" * 60)
    # server_header=False: não revela qual servidor/versão está rodando
    uvicorn.run(app, host=CONFIG["host"], port=int(CONFIG["port"]), server_header=False,
                limit_concurrency=200, timeout_keep_alive=10)


if __name__ == "__main__":
    main()
