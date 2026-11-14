"""Atualização automática pela rede.

O app lê um manifesto JSON (por padrão o `latest.json` da última Release do GitHub):

    {"version": "0.2.0", "url": "https://.../4rt3mi5-Setup-0.2.0.exe",
     "sha256": "...", "notes": "o que mudou"}

Se a versão for maior que a instalada, baixa o instalador, confere o SHA-256 e
roda em modo silencioso; o instalador fecha o app, atualiza e reabre.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from artemis import __version__


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""


# Só aceita manifesto e instalador vindos das Releases oficiais do projeto no GitHub.
TRUSTED_PREFIX = "https://github.com/50nnyc/4rt3mi5/releases/"
TRUSTED_REDIRECT_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")


class UntrustedUpdate(RuntimeError):
    pass


def _trusted(url: str) -> bool:
    return isinstance(url, str) and url.startswith(TRUSTED_PREFIX) and ".." not in url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Segue redirecionamentos só para os servidores de download do GitHub, sempre em HTTPS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urllib.parse.urlsplit(newurl)
        if p.scheme != "https" or p.hostname not in TRUSTED_REDIRECT_HOSTS:
            raise UntrustedUpdate(f"Redirecionamento para servidor não confiável: {p.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.strip().lstrip("v").split(".") if p.isdigit())


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def check(manifest_url: str, timeout: float = 8) -> UpdateInfo | None:
    """Retorna a atualização disponível, ou None se já estiver na última versão."""
    if not _trusted(manifest_url):
        return None
    req = urllib.request.Request(manifest_url, headers={"User-Agent": "4rt3mi5", "Cache-Control": "no-cache"})
    with _opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read(64 * 1024))
    info = UpdateInfo(str(data["version"]), str(data["url"]), str(data["sha256"]).lower(), str(data.get("notes", ""))[:2000])
    if not re.fullmatch(r"\d+(\.\d+){1,3}", info.version) or not re.fullmatch(r"[0-9a-f]{64}", info.sha256):
        raise UntrustedUpdate("Manifesto de atualização inválido.")
    if not _trusted(info.url):
        raise UntrustedUpdate("Instalador fora das Releases oficiais do 4rt3mi5.")
    return info if _vtuple(info.version) > _vtuple(__version__) else None


def download_and_install(info: UpdateInfo, progress=None) -> None:
    """Baixa o instalador, valida o hash e inicia a instalação silenciosa. O app deve fechar em seguida."""
    if not _trusted(info.url):
        raise UntrustedUpdate("Instalador fora das Releases oficiais do 4rt3mi5.")
    target = Path(tempfile.mkdtemp(prefix="4rt3mi5-update-")) / f"4rt3mi5-Setup-{info.version}.exe"
    req = urllib.request.Request(info.url, headers={"User-Agent": "4rt3mi5"})
    sha = hashlib.sha256()
    with _opener.open(req, timeout=60) as resp, open(target, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if sha.hexdigest() != info.sha256:
        target.unlink(missing_ok=True)
        raise RuntimeError("O arquivo baixado não confere (SHA-256 diferente). Atualização cancelada.")
    subprocess.Popen(
        [str(target), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
        close_fds=True,
    )
