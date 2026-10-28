"""Spin a cut-out still a few full turns: a 480×320 animation GIF for the screen, on black.

Run from pc/:

    .venv/Scripts/python tools/spin_gif.py CUTOUT.png OUT.gif --turns 5 --frames 12

CUTOUT.png has a transparent background (any cut-out tool will do). It turns clockwise around
the middle of its visible pixels, scaled so the whole turn fits the screen's height. Every turn
is the same frames over again, so the GIF loops with no jump.
"""

import argparse
import math

from PIL import Image

W, H = 480, 320


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cutout")
    ap.add_argument("gif")
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--frames", type=int, default=12, help="frames per turn")
    ap.add_argument("--fps", type=int, default=15)
    args = ap.parse_args()

    cut = Image.open(args.cutout).convert("RGBA")
    alpha = cut.getchannel("A")
    pts = [(x, y) for y in range(cut.height) for x in range(cut.width) if alpha.getpixel((x, y)) > 127]
    cx = sum(x for x, _ in pts) / len(pts)
    cy = sum(y for _, y in pts) / len(pts)
    reach = max(math.hypot(x - cx, y - cy) for x, y in pts) + 2
    # Centre the cut-out on a black square that holds it at any angle, then rotate that.
    side = math.ceil(2 * reach)
    square = Image.new("RGB", (side, side), "black")
    square.paste(cut, (round(side / 2 - cx), round(side / 2 - cy)), cut)

    frames = []
    for i in range(args.frames):
        turned = square.rotate(-360 * i / args.frames, Image.BICUBIC, fillcolor="black")
        canvas = Image.new("RGB", (W, H), "black")
        canvas.paste(turned.resize((H, H), Image.LANCZOS), ((W - H) // 2, 0))
        frames.append(canvas)
    palette = frames[0].quantize(256, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames] * args.turns
    # GIF delays are in 10 ms steps: spread the rounding so the average is exact (15 fps: 70, 70, 60).
    step = 1000 / args.fps
    durations = [round((i + 1) * step, -1) - round(i * step, -1) for i in range(len(frames))]
    frames[0].save(args.gif, save_all=True, append_images=frames[1:], duration=[int(d) for d in durations],
                   loop=0, optimize=False)
    print(f"{args.gif}: {len(frames)} frames, {sum(durations) / 1000:.2f} s")


if __name__ == "__main__":
    main()
