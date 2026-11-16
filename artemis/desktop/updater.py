"""Atualização automática pela rede.

O app lê um manifesto JSON (por padrão o `latest.json` da última Release do GitHub):

    {"version": "0.2.0", "url": "https://.../4rt3mi5-Setup-0.2.0.exe",
     "sha256": "...", "notes": "o que mudou",
     "web": {"url": "https://.../4rt3mi5-web-0.2.0.zip", "sha256": "...", "bridge": 1}}

Se a versão for maior que a instalada:
- a interface nova (`web`, desde a 0.18.0) é baixada, conferida e aplicada sem fechar o app;
- o instalador é baixado, conferido e roda em silêncio quando a pessoa fecha o app
  (ou na hora, pelo botão "Reiniciar agora").
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
class WebPack:
    url: str
    sha256: str
    bridge: int


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""
    web: WebPack | None = None


# Só aceita manifesto, instalador e interface vindos das Releases oficiais do projeto no GitHub.
TRUSTED_PREFIX = "https://github.com/50nnyc/4rt3mi5/releases/"
TRUSTED_REDIRECT_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
_SHA = re.compile(r"[0-9a-f]{64}")


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


def _web(data) -> WebPack | None:
    """Interface avulsa do manifesto; se vier estranha, é ignorada (o instalador continua valendo)."""
    if not isinstance(data, dict):
        return None
    url, sha, bridge = data.get("url"), str(data.get("sha256", "")).lower(), data.get("bridge")
    if not _trusted(url) or not _SHA.fullmatch(sha) or not isinstance(bridge, int) or isinstance(bridge, bool):
        return None
    return WebPack(url, sha, bridge)


def check(manifest_url: str, timeout: float = 8, current: str = __version__) -> UpdateInfo | None:
    """Retorna a atualização disponível, ou None se `current` já for a última versão."""
    if not _trusted(manifest_url):
        return None
    req = urllib.request.Request(manifest_url, headers={"User-Agent": "4rt3mi5", "Cache-Control": "no-cache"})
    with _opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read(64 * 1024))
    info = UpdateInfo(str(data["version"]), str(data["url"]), str(data["sha256"]).lower(), str(data.get("notes", ""))[:2000],
                      _web(data.get("web")))
    if not re.fullmatch(r"\d+(\.\d+){1,3}", info.version) or not _SHA.fullmatch(info.sha256):
        raise UntrustedUpdate("Manifesto de atualização inválido.")
    if not _trusted(info.url):
        raise UntrustedUpdate("Instalador fora das Releases oficiais do 4rt3mi5.")
    return info if _vtuple(info.version) > _vtuple(current) else None


def download(url: str, sha256: str, target: Path, timeout: float = 60, progress=None) -> Path:
    """Baixa só das Releases oficiais e confere o SHA-256; arquivo que não confere é apagado."""
    if not _trusted(url):
        raise UntrustedUpdate("Arquivo fora das Releases oficiais do 4rt3mi5.")
    req = urllib.request.Request(url, headers={"User-Agent": "4rt3mi5"})
    sha = hashlib.sha256()
    with _opener.open(req, timeout=timeout) as resp, open(target, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if sha.hexdigest() != sha256:
        Path(target).unlink(missing_ok=True)
        raise RuntimeError("O arquivo baixado não confere (SHA-256 diferente). Atualização cancelada.")
    return Path(target)


def download_installer(info: UpdateInfo, progress=None) -> Path:
    target = Path(tempfile.mkdtemp(prefix="4rt3mi5-update-")) / f"4rt3mi5-Setup-{info.version}.exe"
    return download(info.url, info.sha256, target, progress=progress)


def run_installer(path: Path, reopen: bool = True) -> None:
    """Instalação silenciosa. Ao fechar o app (reopen=False) não aparece nada e o app não reabre sozinho."""
    args = [str(path), "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    args.insert(1, "/SILENT" if reopen else "/VERYSILENT")
    if not reopen:
        args.append("/reabrir=nao")
    subprocess.Popen(args, close_fds=True)


def download_and_install(info: UpdateInfo, progress=None) -> None:
    """Baixa o instalador, valida o hash e inicia a instalação silenciosa. O app deve fechar em seguida."""
    run_installer(download_installer(info, progress))
