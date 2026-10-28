"""GIF encoding for the screen. Every GIF sent to the screen goes through encode(), which keeps
files small: one palette for the whole GIF, and each pixel that did not change since the previous
frame is stored as transparent, so the screen keeps the one it already shows (disposal 1, "do not
dispose"). Re-encoding every frame in full instead makes a typical animation about 5× bigger.

The exception is a see-through GIF played over the page: there the transparent colour means "the
page shows here", so no colour is left to mean "unchanged". Each frame is stored whole, with
disposal 2 ("restore to background"), and the screen draws it on a fresh copy of the page."""

import io

from PIL import Image, ImageChops

UNCHANGED = 255  # palette index for "keep the previous pixel" (or "see-through"); the palette has 255 colours
PALETTE_SAMPLES = 16  # frames the shared palette is built from


def encode(frames: list[Image.Image], durations: list[int], see_through: bool = False) -> bytes:
    """A looping GIF from same-sized frames, with each frame's duration in ms. With see_through,
    pixels under half alpha become see-through and every frame is stored whole."""
    if see_through:
        clear = [f.convert("RGBA").getchannel("A").point(lambda a: 255 if a < 128 else 0) for f in frames]
    frames = [f.convert("RGB") for f in frames]
    palette = shared_palette(frames)
    # No dithering: it would spread every change into the still pixels around it.
    indexed = [_keep_unchanged_free(f.quantize(palette=palette, dither=Image.Dither.NONE), palette)
               for f in frames]
    if see_through:
        out = []
        for frame, mask in zip(indexed, clear):
            frame = frame.copy()
            frame.paste(UNCHANGED, mask=mask)
            out.append(frame)
    else:
        out = [indexed[0]]
        for prev, cur in zip(indexed, indexed[1:]):
            same = ImageChops.difference(_indices(cur), _indices(prev)).point(lambda v: 255 if v == 0 else 0)
            frame = cur.copy()
            frame.paste(UNCHANGED, mask=same)
            out.append(frame)
    buf = io.BytesIO()
    out[0].save(buf, "GIF", save_all=True, append_images=out[1:], duration=durations, loop=0,
                transparency=UNCHANGED, disposal=2 if see_through else 1, optimize=False)
    return buf.getvalue()


def shared_palette(frames: list[Image.Image]) -> Image.Image:
    """A 255-colour palette image built from up to PALETTE_SAMPLES frames spread over the GIF."""
    step = max(1, len(frames) // PALETTE_SAMPLES)
    sample = frames[::step][:PALETTE_SAMPLES]
    w, h = sample[0].size
    mosaic = Image.new("RGB", (w, h * len(sample)))
    for i, f in enumerate(sample):
        mosaic.paste(f, (0, h * i))
    colors = mosaic.quantize(UNCHANGED).getpalette()[:UNCHANGED * 3]
    colors += colors[-3:] * (256 - len(colors) // 3)  # fill up to 256 entries with the last colour
    palette = Image.new("P", (1, 1))
    palette.putpalette(colors)
    return palette


def _keep_unchanged_free(im: Image.Image, palette: Image.Image) -> Image.Image:
    """Moves any pixel quantized to UNCHANGED to index 254, which has the same colour."""
    if im.getextrema()[1] < UNCHANGED:
        return im
    fixed = Image.frombytes("P", im.size, _indices(im).point(lambda v: min(v, UNCHANGED - 1)).tobytes())
    fixed.putpalette(palette.getpalette())
    return fixed


def _indices(im: Image.Image) -> Image.Image:
    return Image.frombytes("L", im.size, im.tobytes())
