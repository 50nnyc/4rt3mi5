"""Proteção dos dados sensíveis salvos no PC (código de acesso e token do aparelho).

No Windows usa o DPAPI (CryptProtectData): o valor só pode ser aberto pelo mesmo
usuário do Windows, no mesmo PC. Copiar o config.json para outra máquina não
revela nada. Fora do Windows, devolve o valor como está.
"""
from __future__ import annotations

import base64
import ctypes
import sys

PREFIX = "dpapi:"
_ENTROPY = b"4rt3mi5-local-secret"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _call(fn_name: str, data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    src, ent, out = _blob(data), _blob(_ENTROPY), _Blob()
    fn = getattr(crypt32, fn_name)
    if fn_name == "CryptProtectData":
        ok = fn(ctypes.byref(src), "4rt3mi5", ctypes.byref(ent), None, None, 0x01, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x01, ctypes.byref(out))
    if not ok:
        raise OSError(f"{fn_name} falhou")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def available() -> bool:
    return sys.platform == "win32"


def protect(value: str) -> str:
    if not available() or value is None:
        return value
    return PREFIX + base64.b64encode(_call("CryptProtectData", value.encode("utf-8"))).decode("ascii")


def unprotect(value: str) -> str | None:
    """Abre um valor protegido. Valor antigo (sem proteção) volta como está."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    if not available():
        return None
    try:
        return _call("CryptUnprotectData", base64.b64decode(value[len(PREFIX):])).decode("utf-8")
    except (OSError, ValueError):
        return None  # de outro usuário/PC: o app pede o código de novo
