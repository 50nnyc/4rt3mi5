"""Configuração do app desktop, em %APPDATA%\\4rt3mi5\\config.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "4rt3mi5"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Endereço público do servidor (domínio DuckDNS com HTTPS na VM). Pode ser trocado na tela do código de acesso.
# O domínio antigo do ngrok continua funcionando para quem já tem o app instalado com ele salvo.
DEFAULT_SERVER_URL = "https://artemis-hunt.duckdns.org"
# Manifesto da última Release no GitHub (atualização automática).
DEFAULT_UPDATE_URL = "https://github.com/50nnyc/4rt3mi5/releases/latest/download/latest.json"


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
