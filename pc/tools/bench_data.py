"""Test data for the step 5 hardware bench (firmware env `bench`), written to firmware/bench_data/.

Run from pc/:

    .venv/Scripts/python tools/bench_data.py [PHOTO.jpg]

- bg.rgb565: a page background, raw little-endian RGB565 (PHOTO, or a gradient without one)
- overlay.ov1z: the Total page with demo data, as the PC sends it (docs/PROTOCOL.md)
- page.jpg: the background as a 480×320 JPEG, for the decoder timing
- anim.gif: the built-in level-up animation

The panel is portrait (320×480) and the bench does not rotate, so bg and overlay are turned a
quarter turn here to show the right way round. The JPEG and GIF are only timed, not shown.
Uses fallback fonts and no game art (nothing is downloaded), so the files can stay local.
"""

import argparse
import shutil
import time
from pathlib import Path

from PIL import Image

from stashdisplay import pages as pagelib
from stashdisplay.cli import demo_render_data
from stashdisplay.link.protocol import encode_overlay
from stashdisplay.media import compose_background
from stashdisplay.render import renderer

OUT = Path(__file__).resolve().parents[2] / "firmware" / "bench_data"
ANIM = Path(__file__).resolve().parents[1] / "stashdisplay" / "assets" / "anims" / "levelup.gif"


def rgb565(img: Image.Image) -> bytes:
    out = bytearray()
    raw = img.convert("RGB").tobytes()
    for i in range(0, len(raw), 3):
        r, g, b = raw[i:i + 3]
        v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        out += v.to_bytes(2, "little")
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("photo", nargs="?")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.photo:
        with Image.open(args.photo) as im:
            bg = compose_background(im, "cover", 50, 50)
    else:
        bg = Image.linear_gradient("L").resize((480, 320)).convert("RGB")
    bg.save(OUT / "page.jpg", quality=85)
    (OUT / "bg.rgb565").write_bytes(rgb565(bg.transpose(Image.Transpose.ROTATE_90)))

    page = pagelib.visible(pagelib.preset())[0]
    ov = renderer.overlay(page, demo_render_data(time.time(), seed=7))
    blob = encode_overlay(ov.transpose(Image.Transpose.ROTATE_90))
    (OUT / "overlay.ov1z").write_bytes(blob)

    shutil.copyfile(ANIM, OUT / "anim.gif")
    for f in sorted(OUT.iterdir()):
        print(f"{f.name}: {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
