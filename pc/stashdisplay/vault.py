"""Keeps the WealthyExile cookie out of plain sight in settings.json.

On Windows it is encrypted with DPAPI (CryptProtectData): only the same Windows
user on the same PC can decrypt it. Elsewhere (development on macOS) it is
stored base64-encoded only, which is not encryption; the settings file is then
made readable by its owner only.
"""

import base64
import ctypes
import sys

ENTROPY = b"stashdisplay-cookie-v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32  # type: ignore[attr-defined]
    src, entropy, out = _blob(data), _blob(ENTROPY), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # Flag 0x1 = CRYPTPROTECT_UI_FORBIDDEN: never show a prompt.
    if not fn(ctypes.byref(src), None, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(out)):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def seal(secret: str) -> dict:
    if not secret:
        return {}
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        return {"dpapi": base64.b64encode(_dpapi(raw, protect=True)).decode()}
    return {"plain": base64.b64encode(raw).decode()}


def unseal(sealed: dict | None) -> str:
    if not sealed:
        return ""
    try:
        if "dpapi" in sealed and sys.platform == "win32":
            return _dpapi(base64.b64decode(sealed["dpapi"]), protect=False).decode("utf-8")
        if "plain" in sealed:
            return base64.b64decode(sealed["plain"]).decode("utf-8")
    except (OSError, ValueError):
        pass
    return ""  # unreadable (e.g. settings copied from another PC): ask for the cookie again
