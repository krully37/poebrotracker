"""Build the Windows app: one StashDisplay.exe, no console window (docs/SCOPE.md §7).

Run from pc/, with the dev install and PyInstaller:

    .venv\\Scripts\\pip install pyinstaller
    .venv\\Scripts\\python packaging\\build.py

Writes dist/StashDisplay.exe. GitHub Actions runs the same (.github/workflows/build.yml).
The game icons and Fontin are not inside: each PC downloads its own copy on first start.
"""

import os
import sys
from pathlib import Path

import PyInstaller.__main__

PC = Path(__file__).resolve().parents[1]
BUILD = PC / "build"
SEP = os.pathsep  # PyInstaller's "source;dest" separator: ";" on Windows


def icon() -> Path:
    """The tray icon, as the .exe's icon."""
    sys.path.insert(0, str(PC))
    from stashdisplay.tray import icon_image

    path = BUILD / "stashdisplay.ico"
    path.parent.mkdir(exist_ok=True)
    icon_image(256).save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def main() -> None:
    package = PC / "stashdisplay"
    data = [
        (package / "assets" / "fonts", "stashdisplay/assets/fonts"),
        (package / "assets" / "anims", "stashdisplay/assets/anims"),
        (package / "web" / "static", "stashdisplay/web/static"),
    ]
    args = [
        str(PC / "packaging" / "entry.py"),
        "--name", "StashDisplay",
        "--onefile",
        "--windowed",  # no console: the tray icon is the app's only window
        "--icon", str(icon()),
        "--distpath", str(PC / "dist"),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        "--noconfirm",
        "--clean",
        "--hidden-import", "pystray._win32",
        "--collect-submodules", "winrt",  # the media card's Windows APIs are namespace packages
        "--collect-submodules", "waitress",
    ]
    for source, dest in data:
        args += ["--add-data", f"{source}{SEP}{dest}"]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
