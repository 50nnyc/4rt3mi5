"""App desktop do 4rt3mi5: janela nativa (WebView2) com a mesma interface do site."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import webview

from artemis import APP_NAME, __version__

from . import secure, uipack, updater
from .config import CONFIG_DIR, Config

SECRET_KEYS = {"key", "token", "acct"}  # código de acesso, token do aparelho e sessão da conta: criptografados no PC
UI_DIR = CONFIG_DIR / "ui"          # pasta que a janela serve (interface do instalador ou a baixada depois)
PACK_DIR = CONFIG_DIR / "ui-pack"   # interface nova já baixada e conferida, esperando entrar


APP_ID = "4rt3mi5.App"  # igual ao AppUserModelID dos atalhos (packaging/installer.iss)


def icon_path() -> str | None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    p = base / "4rt3mi5.ico"
    return str(p) if p.exists() else None


def _taskbar_identity() -> None:
    """Faz a barra de tarefas tratar a janela como o 4rt3mi5 (e não como python.exe): ícone e agrupamento próprios."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001 - só cosmético
        pass


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "web" if (base / "web").exists() else base / "artemis" / "web"


class Bridge:
    """Funções que a página chama via window.pywebview.api.*"""

    def __init__(self, ui_version: str = __version__) -> None:
        self.cfg = Config.load()
        self.ui_version = ui_version  # versão da interface na tela (pode passar do exe, 0.18.0)
        self._update: updater.UpdateInfo | None = None
        self._lock = threading.Lock()
        self._ulock = threading.Lock()
        self._installer: tuple[str, Path] | None = None  # (versão, instalador conferido) para rodar ao fechar
        self._downloading = False

    def get_config(self) -> dict:
        return {"api_base": self.cfg.server_url, "version": self.ui_version, "app_version": __version__}

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
        """Procura versão nova. A interface nova é baixada na hora; o instalador, em segundo plano.
        ui: "ready" (tela nova pronta para entrar), "current" (a tela já está na versão nova) ou "none"."""
        if not updater.is_frozen():
            return None  # rodando do código-fonte: sem atualização automática
        try:
            info = updater.check(self.cfg.update_url)
        except Exception:  # noqa: BLE001 - sem atualização se o GitHub não responder
            return None
        self._update = info
        if not info:
            return None
        if uipack.vtuple(info.version) <= uipack.vtuple(self.ui_version):
            ui = "current"
        elif (meta := uipack.usable(PACK_DIR, __version__)) and meta["version"] == info.version:
            ui = "ready"  # já baixada antes nesta sessão
        elif info.web and info.web.bridge <= uipack.BRIDGE and self._fetch_pack(info):
            ui = "ready"
        else:
            ui = "none"
        self._fetch_installer(info)
        return {"version": info.version, "notes": info.notes, "ui": ui}

    def _fetch_pack(self, info: updater.UpdateInfo) -> bool:
        try:
            tmp = Path(tempfile.mkdtemp(prefix="4rt3mi5-ui-"))
            try:
                z = updater.download(info.web.url, info.web.sha256, tmp / "web.zip", timeout=30)
                uipack.extract(z, PACK_DIR, info.version, info.web.bridge, info.web.sha256)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            return True
        except Exception:  # noqa: BLE001 - sem a tela nova, a atualização vem inteira pelo instalador
            return False

    def _fetch_installer(self, info: updater.UpdateInfo) -> None:
        with self._ulock:
            if self._downloading or (self._installer and self._installer[0] == info.version):
                return
            self._downloading = True

        def run() -> None:
            try:
                path = updater.download_installer(info)
                with self._ulock:
                    self._installer = (info.version, path)
            except Exception:  # noqa: BLE001 - tenta de novo na próxima verificação
                pass
            finally:
                with self._ulock:
                    self._downloading = False

        threading.Thread(target=run, daemon=True).start()

    def reload_ui(self):
        """Põe a interface baixada na pasta servida; a página recarrega em seguida (o app não fecha)."""
        meta = uipack.usable(PACK_DIR, __version__)
        if not meta:
            return "A versão nova da tela ainda não está pronta."
        try:
            uipack.copy_into(PACK_DIR, UI_DIR)
        except OSError as e:
            return str(e)
        self.ui_version = meta["version"]
        return None

    def install_update(self):
        """Botão "Reiniciar agora": instala na hora e o app reabre sozinho."""
        if not self._update:
            return "Nenhuma atualização disponível."
        try:
            with self._ulock:
                ready = self._installer if self._installer and self._installer[0] == self._update.version else None
                self._installer = None  # não roda de novo ao fechar
            path = ready[1] if ready else updater.download_installer(self._update)
            updater.run_installer(path, reopen=True)
        except Exception as e:  # noqa: BLE001
            return str(e)
        for w in webview.windows:
            w.destroy()
        return None

    def _install_on_close(self) -> bool:
        """Chamado quando a janela fecha (com _ para a página não enxergar): se o instalador novo já está baixado, instala em silêncio."""
        with self._ulock:
            pending, self._installer = self._installer, None
        if not pending:
            return False
        try:
            updater.run_installer(pending[1], reopen=False)
        except Exception:  # noqa: BLE001 - na próxima abertura ele baixa de novo
            return False
        return True


def main() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _taskbar_identity()
    # Deixa a trilha da abertura tocar sem precisar de um clique antes (o volume e o mudo
    # continuam com a pessoa, pelo botão de som).
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")
    ui, ui_version = web_dir(), __version__
    if updater.is_frozen():  # app instalado: a tela pode ter chegado depois, sem reinstalar (0.18.0)
        try:
            ui_version = uipack.prepare_live(web_dir(), PACK_DIR, UI_DIR, __version__)
            ui = UI_DIR
        except Exception:  # noqa: BLE001 - qualquer problema: usa a interface que veio no instalador
            ui, ui_version = web_dir(), __version__
    bridge = Bridge(ui_version)
    webview.create_window(
        APP_NAME,
        url=str(ui / "index.html"),
        js_api=bridge,
        width=1120,
        height=800,
        min_size=(380, 600),
        background_color="#0b0d12",
    )
    webview.start(http_server=True, private_mode=False, storage_path=str(CONFIG_DIR / "webview"), icon=icon_path())
    bridge._install_on_close()  # o resto da atualização (exe) entra agora, sem a pessoa ver


if __name__ == "__main__":
    main()
