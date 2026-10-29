"""The images the firmware draws on its own, rendered by the PC renderer and baked into it.

Run from pc/ after changing how they look, then rebuild the firmware:

    .venv/Scripts/python tools/firmware_assets.py

Writes firmware/assets/offline-waiting.ov1z and offline-disconnected.ov1z, in the overlay
format of docs/PROTOCOL.md (opaque, 480×320). Uses the bundled open-licence fonts, never
Fontin, so the files can be committed.
"""

from pathlib import Path

from stashdisplay.link.protocol import encode_overlay
from stashdisplay.render import renderer

OUT = Path(__file__).resolve().parents[2] / "firmware" / "assets"
SCREENS = {
    "offline-waiting": "Waiting for the PC",
    "offline-disconnected": "PC disconnected",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, message in SCREENS.items():
        blob = encode_overlay(renderer.offline_screen(message).convert("RGBA"))
        (OUT / f"{name}.ov1z").write_bytes(blob)
        print(f"{name}.ov1z: {len(blob)} bytes")


if __name__ == "__main__":
    main()
