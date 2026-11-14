"""App desktop do 4rt3mi5: janela nativa (WebView2) com a mesma interface do site."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import webview

from artemis import APP_NAME, __version__

from . import secure, updater
from .config import CONFIG_DIR, Config

SECRET_KEYS = {"key", "token"}  # código de acesso e token do aparelho: criptografados no PC


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "web" if (base / "web").exists() else base / "artemis" / "web"


class Bridge:
    """Funções que a página chama via window.pywebview.api.*"""

    def __init__(self) -> None:
        self.cfg = Config.load()
        self._update: updater.UpdateInfo | None = None
        self._lock = threading.Lock()

    def get_config(self) -> dict:
        return {"api_base": self.cfg.server_url, "version": __version__}

    def set_server(self, url: str) -> str:
        url = url.strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.cfg.server_url = url or self.cfg.server_url
        self.cfg.save()
        return self.cfg.server_url

    def kv_get(self, key: str):
        value = self.cfg.storage.get(key)
        if key in SECRET_KEYS and isinstance(value, str):
            plain = secure.unprotect(value)
            if plain is not None and not value.startswith(secure.PREFIX):
                self.kv_set(key, plain)  # valor salvo por versão antiga: protege agora
            return plain
        return value

    def kv_set(self, key: str, value) -> None:
        with self._lock:
            if value is None:
                self.cfg.storage.pop(key, None)
            else:
                self.cfg.storage[key] = secure.protect(value) if key in SECRET_KEYS and isinstance(value, str) else value
            self.cfg.save()

    def check_update(self):
        if not updater.is_frozen():
            return None  # rodando do código-fonte: sem atualização automática
        try:
            self._update = updater.check(self.cfg.update_url)
        except Exception:  # noqa: BLE001 - sem atualização se o GitHub não responder
            return None
        return {"version": self._update.version, "notes": self._update.notes} if self._update else None

    def install_update(self):
        if not self._update:
            return "Nenhuma atualização disponível."
        try:
            updater.download_and_install(self._update)
        except Exception as e:  # noqa: BLE001
            return str(e)
        for w in webview.windows:
            w.destroy()
        return None


def main() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    webview.create_window(
        APP_NAME,
        url=str(web_dir() / "index.html"),
        js_api=Bridge(),
        width=1120,
        height=800,
        min_size=(380, 600),
        background_color="#0b0d12",
    )
    webview.start(http_server=True, private_mode=False, storage_path=str(CONFIG_DIR / "webview"))


if __name__ == "__main__":
    main()
