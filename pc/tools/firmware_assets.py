"""The images the firmware draws on its own, rendered by the PC renderer and baked into it.

Run from pc/ after changing how they look, then rebuild the firmware:

    .venv/Scripts/python tools/firmware_assets.py

Writes, in the overlay format of docs/PROTOCOL.md:
- firmware/assets/offline-waiting.ov1z and offline-disconnected.ov1z (opaque, 480×320)
- firmware/src/decor_sprites.h: the pagination dots and the glyphs of the "4/9" counter, as the
  renderer draws them (renderer.dots), unpacked, for the screen to place itself; and where the
  reset banner's bar is (theme.HOLD_BAR), which the screen fills

Uses the bundled open-licence fonts, never Fontin, so the files can be committed.
"""

import zlib
from pathlib import Path

from PIL import Image

from stashdisplay.link.protocol import HOLD_OVERLAY, encode_overlay
from stashdisplay.render import draw, renderer
from stashdisplay.render.fonts import font
from stashdisplay.render.templates import Box
from stashdisplay.render.theme import DOTS_Y, GOLD, HEIGHT, HOLD_BAR, MUTED, WIDTH

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"
OUT = FIRMWARE / "assets"
HEADER = FIRMWARE / "src" / "decor_sprites.h"
GLYPHS = "0123456789/"
DOT = 10  # sprite size around a dot's centre
SCREENS = {
    "offline-waiting": "Waiting for the PC",
    "offline-disconnected": "PC disconnected",
}


def sprite(img: Image.Image) -> bytes:
    """Unpacked overlay bytes: "OV1" | w | h | alpha | colour."""
    return zlib.decompress(encode_overlay(img))


def c_array(name: str, data: bytes) -> str:
    rows = [", ".join(f"0x{b:02x}" for b in data[i:i + 20]) for i in range(0, len(data), 20)]
    body = ",\n    ".join(rows)
    return f"const uint8_t {name}[] = {{\n    {body}\n}};\n"


def decor_header() -> str:
    # Two dots, the current one first, as renderer.dots draws them; cut out around their centres.
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    renderer.dots(img, 0, 2)
    cx = WIDTH // 2 - 7
    top = DOTS_Y - DOT // 2
    on = img.crop((cx - DOT // 2, top, cx + DOT // 2, top + DOT))
    off = img.crop((cx + 14 - DOT // 2, top, cx + 14 + DOT // 2, top + DOT))
    # Counter glyphs, each drawn alone at the left of a cell, with its advance.
    f = font("Inter", 11, 600)
    out = [
        "// Made by pc/tools/firmware_assets.py: do not edit.",
        "// Pagination as renderer.dots draws it, in the overlay format, unpacked.",
        "#pragma once",
        "",
        "#include <stdint.h>",
        "",
        f"constexpr int kDotSprite = {DOT};  // dots are drawn centred on (x, {DOTS_Y})",
        f"constexpr int kCounterTop = {DOTS_Y - 7};",
        "",
        "// The reset banner (an overlay from the PC, HOLD_OVERLAY + action) and its bar, filled in gold.",
        f'constexpr const char *kHoldOverlay = "{HOLD_OVERLAY}";',
        "constexpr int kHoldBarX = {}, kHoldBarY = {}, kHoldBarW = {}, kHoldBarH = {};".format(*HOLD_BAR),
        "constexpr uint8_t kGoldR = 0x{}, kGoldG = 0x{}, kGoldB = 0x{};".format(GOLD[1:3], GOLD[3:5], GOLD[5:7]),
        "",
        c_array("kDotOn", sprite(on)),
        c_array("kDotOff", sprite(off)),
    ]
    table = []
    for i, ch in enumerate(GLYPHS):
        cell = Image.new("RGBA", (16, 14), (0, 0, 0, 0))
        draw.text_in(draw.Ctx(cell, None), Box(0, 0, 16, 14), ch, f, MUTED, "left")
        out.append(c_array(f"kGlyph{i}", sprite(cell)))
        table.append(f"    {{'{ch}', {f.getlength(ch):.2f}f, kGlyph{i}}},")
    out += [
        "struct Glyph {",
        "  char c;",
        "  float advance;",
        "  const uint8_t *sprite;",
        "};",
        "",
        "const Glyph kGlyphs[] = {",
        *table,
        "};",
        "",
    ]
    return "\n".join(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, message in SCREENS.items():
        blob = encode_overlay(renderer.offline_screen(message).convert("RGBA"))
        (OUT / f"{name}.ov1z").write_bytes(blob)
        print(f"{name}.ov1z: {len(blob)} bytes")
    HEADER.write_text(decor_header(), encoding="utf-8", newline="\n")
    print(f"{HEADER.name}: written")


if __name__ == "__main__":
    main()
