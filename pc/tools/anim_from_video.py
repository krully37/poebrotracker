"""Turn a phone video into a 480×320 event animation GIF for the screen.

Needs ffmpeg on PATH. Run from pc/:

    .venv/Scripts/python tools/anim_from_video.py IN.mp4 OUT.gif --crop W:H:X:Y --part START-END ...

--crop is in the video's own pixels; keep W:H at 3:2. Each --part is START-END in seconds (either
side may be left empty) and the parts are joined in order, so a looping clip can start near its end.

Phone video has sensor noise that changes every pixel in every frame, which makes GIFs huge. The
video is denoised, then any pixel that changed less than --threshold since it was last shown keeps
its old value, so the GIF only stores what really moves (about 5× smaller).
"""

import argparse
import subprocess
import sys

from PIL import Image, ImageChops, ImageFilter

W, H = 480, 320


def freeze_noise(frame: Image.Image, shown: Image.Image, threshold: int) -> Image.Image:
    r, g, b = ImageChops.difference(frame, shown).split()
    changed = ImageChops.lighter(ImageChops.lighter(r, g), b)
    # Grow the changed area a little so the edges of moving parts update cleanly.
    mask = changed.point(lambda v: 255 if v > threshold else 0).filter(ImageFilter.MaxFilter(3))
    return Image.composite(frame, shown, mask)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video")
    ap.add_argument("gif")
    ap.add_argument("--crop", required=True, help="W:H:X:Y in the video's pixels")
    ap.add_argument("--part", action="append", default=[], help="START-END in seconds; repeatable")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--colors", type=int, default=128)
    ap.add_argument("--threshold", type=int, default=14)
    args = ap.parse_args()

    parts = args.part or ["-"]
    trims = []
    for i, part in enumerate(parts):
        start, _, end = part.partition("-")
        opts = ":".join(o for o in (start and f"start={start}", end and f"end={end}") if o)
        trims.append(f"[s{i}]trim{'=' + opts if opts else ''},setpts=PTS-STARTPTS[p{i}]")
    graph = (f"[0:v]split={len(parts)}" + "".join(f"[s{i}]" for i in range(len(parts))) + ";"
             + ";".join(trims) + ";" + "".join(f"[p{i}]" for i in range(len(parts)))
             + f"concat=n={len(parts)}:v=1,crop={args.crop},hqdn3d=3:3:8:8,"
             + f"scale={W}:{H}:flags=lanczos,fps={args.fps}")
    reader = subprocess.Popen(["ffmpeg", "-v", "error", "-i", args.video, "-filter_complex", graph,
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    writer = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                               "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "-", "-vf",
                               f"split[a][b];[a]palettegen=max_colors={args.colors}[p];"
                               "[b][p]paletteuse=dither=none:diff_mode=rectangle",
                               "-loop", "-1", args.gif], stdin=subprocess.PIPE)
    shown, frames = None, 0
    while len(raw := reader.stdout.read(W * H * 3)) == W * H * 3:
        frame = Image.frombytes("RGB", (W, H), raw)
        shown = frame if shown is None else freeze_noise(frame, shown, args.threshold)
        writer.stdin.write(shown.tobytes())
        frames += 1
    writer.stdin.close()
    if reader.wait() or writer.wait():
        sys.exit("ffmpeg failed")
    print(f"{args.gif}: {frames} frames, {frames / args.fps:.1f} s")


if __name__ == "__main__":
    main()
