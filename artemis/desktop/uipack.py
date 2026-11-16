"""Pacote da interface (0.18.0): a tela do app se atualiza sem fechar o programa.

Cada Release publica `4rt3mi5-web-<versão>.zip` (a pasta artemis/web) e o `latest.json` traz a URL,
o SHA-256 e a versão da "ponte" que essa interface exige. O app baixa só das Releases oficiais,
confere o hash, extrai com cuidado e passa a servir a interface de %APPDATA%\\4rt3mi5\\ui.
O resto do programa (exe e Python) chega pelo instalador, que roda quando a pessoa fecha o app.

Uso no build:  python -m artemis.desktop.uipack artemis/web dist/4rt3mi5-web-<versão>.zip
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

# Versão das funções que a interface chama no app (main.Bridge). Suba ao mudar ou remover alguma:
# apps com ponte menor deixam de aplicar a interface nova e esperam o instalador.
BRIDGE = 1

META = "pack.json"
ALLOWED_SUFFIXES = {".html", ".js", ".css", ".png", ".jpg", ".svg", ".ico", ".json", ".webmanifest", ".txt", ".ogg", ".mp3", ".woff2"}
MAX_FILES = 300
MAX_TOTAL = 30 * 1024 * 1024


class BadPack(RuntimeError):
    pass


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in str(v).strip().lstrip("v").split(".") if p.isdigit())


def build(src: Path, dest: Path) -> str:
    """Compacta a pasta da interface (nomes com '/') e devolve o SHA-256 do zip."""
    src, dest = Path(src), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(src).as_posix())
    return hashlib.sha256(dest.read_bytes()).hexdigest()


def _members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos or len(infos) > MAX_FILES:
        raise BadPack("Pacote da interface com quantidade de arquivos inválida.")
    if sum(i.file_size for i in infos) > MAX_TOTAL:
        raise BadPack("Pacote da interface grande demais.")
    for i in infos:
        p = PurePosixPath(i.filename)
        if "\\" in i.filename or p.is_absolute() or ".." in p.parts or ":" in i.filename or p.name == META:
            raise BadPack(f"Caminho inválido no pacote: {i.filename}")
        if p.suffix.lower() not in ALLOWED_SUFFIXES:
            raise BadPack(f"Tipo de arquivo não permitido no pacote: {i.filename}")
    if "index.html" not in {i.filename for i in infos}:
        raise BadPack("Pacote da interface sem index.html.")
    return infos


def extract(zip_path: Path, target: Path, version: str, bridge: int, sha256: str) -> None:
    """Extrai o pacote já conferido em `target` (troca a pasta inteira só no fim, se tudo deu certo)."""
    target = Path(target)
    tmp = target.with_name(target.name + ".novo")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in _members(zf):
                out = tmp.joinpath(*PurePosixPath(info.filename).parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        (tmp / META).write_text(json.dumps({"version": version, "bridge": int(bridge), "sha256": sha256}), encoding="utf-8")
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)


def read_meta(pack_dir: Path) -> dict | None:
    try:
        meta = json.loads((Path(pack_dir) / META).read_text(encoding="utf-8"))
        if isinstance(meta.get("version"), str) and isinstance(meta.get("bridge"), int) and (Path(pack_dir) / "index.html").is_file():
            return meta
    except (OSError, ValueError, AttributeError):
        pass
    return None


def usable(pack_dir: Path, app_version: str) -> dict | None:
    """O pacote baixado vale para este app? (mais novo que o app instalado e com ponte compatível)"""
    meta = read_meta(pack_dir)
    if meta and vtuple(meta["version"]) > vtuple(app_version) and meta["bridge"] <= BRIDGE:
        return meta
    return None


def copy_into(src: Path, live: Path) -> None:
    """Troca o conteúdo da pasta servida pela janela (sem trocar a pasta, que o servidor interno usa)."""
    live = Path(live)
    live.mkdir(parents=True, exist_ok=True)
    for old in live.iterdir():
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    for p in Path(src).iterdir():
        if p.name == META:
            continue
        shutil.copytree(p, live / p.name) if p.is_dir() else shutil.copy2(p, live / p.name)


def prepare_live(bundled: Path, pack_dir: Path, live: Path, app_version: str) -> str:
    """Na abertura: monta a pasta servida com o pacote baixado (se ainda valer) ou com a interface do instalador.
    Devolve a versão da interface que ficou valendo."""
    meta = usable(pack_dir, app_version)
    if meta is None:
        shutil.rmtree(pack_dir, ignore_errors=True)  # já veio pelo instalador (ou não serve mais)
    copy_into(pack_dir if meta else bundled, live)
    return meta["version"] if meta else app_version


if __name__ == "__main__":
    print(build(Path(sys.argv[1]), Path(sys.argv[2])))
