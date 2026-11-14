"""Barreira contra vazamento de dados sensíveis no repositório.

Roda sozinho antes de cada commit (gancho em .githooks/pre-commit) e no GitHub
Actions antes de gerar a versão. Se achar algo, o commit/versão é bloqueado.

    python tools/check_secrets.py            # verifica os arquivos que vão no commit
    python tools/check_secrets.py --all      # verifica todos os arquivos do repositório

Procura: códigos de acesso reais, tokens (ngrok, GitHub, admin), chaves privadas,
e-mails pessoais e arquivos que nunca devem ir para o GitHub (.env, banco, config).
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys

# Arquivos que nunca podem ser versionados
FORBIDDEN_FILES = [
    ".env", "*/.env", ".env.*", "*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3",
    "server.json", "*/server.json", "data/*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa*", "*.log",
]
ALLOWED_FILES = [".env.example"]

_KEY = "[A-HJ-NP-Z2-9]"
PATTERNS = [
    ("código de acesso", re.compile(rf"\bART-{_KEY}{{4}}-{_KEY}{{4}}\b")),
    ("token do ngrok", re.compile(r"\b[0-9][A-Za-z0-9]{20,}_[A-Za-z0-9]{15,}\b")),
    ("token do GitHub", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("chave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("senha/token no código", re.compile(
        r"(?i)\b(admin_token|authtoken|ngrok_authtoken|password|senha|secret|api_key|token)\b\s*[\"']?\s*[:=]\s*[\"']"
        r"(?!\$\{)[A-Za-z0-9_\-]{16,}[\"']")),
    ("e-mail", re.compile(r"\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com|example\.(com|org))[A-Za-z0-9.-]+\.[a-z]{2,}\b")),
]
# Exemplos/marcadores que podem aparecer na documentação
ALLOWED_TEXT = {"ART-XXXX-XXXX"}
# Dados públicos importados (TibiaWiki): só procura arquivos/segredos fortes, não e-mails
SKIP_PATTERNS_IN = {"artemis/data/tibiawiki.json": {"e-mail"}, "artemis/data/hunts.json": {"e-mail"}}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          check=True).stdout


def file_list(all_files: bool) -> list[str]:
    if all_files:
        return [f for f in git("ls-files", "-z").split("\0") if f]
    return [f for f in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0") if f]


def content(path: str, all_files: bool) -> str:
    if all_files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""
    return git("show", f":{path}")


def forbidden(path: str) -> bool:
    name = path.replace("\\", "/")
    if any(fnmatch.fnmatch(name, a) or fnmatch.fnmatch(name.rsplit("/", 1)[-1], a) for a in ALLOWED_FILES):
        return False
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(name.rsplit("/", 1)[-1], p) for p in FORBIDDEN_FILES)


def scan(all_files: bool = False) -> list[str]:
    problems = []
    for path in file_list(all_files):
        if path.replace("\\", "/") == "tools/check_secrets.py":
            continue
        if forbidden(path):
            problems.append(f"{path}: arquivo sensível não pode ir para o GitHub")
            continue
        text = content(path, all_files)
        if "\0" in text[:2000]:
            continue  # binário (imagem etc.)
        skip = SKIP_PATTERNS_IN.get(path.replace("\\", "/"), set())
        for n, line in enumerate(text.splitlines(), 1):
            for label, rx in PATTERNS:
                if label in skip:
                    continue
                for m in rx.finditer(line):
                    if m.group(0) in ALLOWED_TEXT:
                        continue
                    shown = m.group(0)
                    shown = shown[:6] + "…" if len(shown) > 8 else "…"  # não reimprime o segredo inteiro
                    problems.append(f"{path}:{n}: {label} ({shown})")
    return problems


def main() -> int:
    all_files = "--all" in sys.argv
    problems = scan(all_files)
    if problems:
        print("BLOQUEADO: encontrei dados sensíveis que não podem ir para o GitHub:\n")
        for p in problems:
            print("  -", p)
        print("\nTire esses dados do arquivo (use o .env, que não é versionado) e tente de novo.")
        return 1
    print(f"Sem dados sensíveis ({'todos os arquivos' if all_files else 'arquivos do commit'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
