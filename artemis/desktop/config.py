"""Configuração do app desktop, em %APPDATA%\\4rt3mi5\\config.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "4rt3mi5"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Endereço público do servidor (ex.: o do Cloudflare Tunnel). Pode ser trocado na tela da chave.
DEFAULT_SERVER_URL = "http://localhost:8000"
# Troque SEU_USUARIO pelo seu usuário do GitHub.
DEFAULT_UPDATE_URL = "https://github.com/SEU_USUARIO/4rt3mi5/releases/latest/download/latest.json"


@dataclass
class Config:
    server_url: str = DEFAULT_SERVER_URL
    update_url: str = DEFAULT_UPDATE_URL
    storage: dict = field(default_factory=dict)  # chave de acesso, último nick...

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
