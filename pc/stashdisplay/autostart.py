"""Start with Windows: a value under HKCU\\...\\Run pointing at the app.

Only the current user is affected and no admin rights are needed. On other
systems autostart is reported as unsupported.
"""

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "stashdisplay"


def supported() -> bool:
    return sys.platform == "win32"


def command() -> str:
    """What Windows runs at logon: the packaged .exe, or pythonw for a source install."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" run'
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pythonw}" -m stashdisplay run'


def enabled() -> bool:
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_enabled(on: bool) -> None:
    if not supported():
        raise RuntimeError("autostart is only available on Windows")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
