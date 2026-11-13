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
import subprocess
import sys
import tempfile
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


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.strip().lstrip("v").split(".") if p.isdigit())


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def check(manifest_url: str, timeout: float = 8) -> UpdateInfo | None:
    """Retorna a atualização disponível, ou None se já estiver na última versão."""
    if not manifest_url or "SEU_USUARIO" in manifest_url:
        return None
    req = urllib.request.Request(manifest_url, headers={"User-Agent": "4rt3mi5", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    info = UpdateInfo(data["version"], data["url"], data["sha256"].lower(), data.get("notes", ""))
    return info if _vtuple(info.version) > _vtuple(__version__) else None


def download_and_install(info: UpdateInfo, progress=None) -> None:
    """Baixa o instalador, valida o hash e inicia a instalação silenciosa. O app deve fechar em seguida."""
    target = Path(tempfile.gettempdir()) / f"4rt3mi5-Setup-{info.version}.exe"
    req = urllib.request.Request(info.url, headers={"User-Agent": "4rt3mi5"})
    sha = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as resp, open(target, "wb") as f:
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
