import io
import random

from PIL import Image, ImageChops, ImageDraw

from stashdisplay.link import gif
from stashdisplay.link.content import gif_for_screen
from stashdisplay.link.simulator import _decode_frames

W, H = 480, 320


def scene(n: int, colors: int = 100) -> list[Image.Image]:
    """A still, noisy background (few enough colours to survive the palette) with a square moving
    over it, held still for the last two frames."""
    rnd = random.Random(1)
    palette = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(colors)]
    bg = Image.new("RGB", (W, H))
    bg.putdata([rnd.choice(palette) for _ in range(W * H)])
    frames = []
    for i in range(n):
        f = bg.copy()
        x = min(i, n - 2) * 20
        ImageDraw.Draw(f).rectangle((x, 100, x + 60, 160), fill=(0, 0, 0), outline=(255, 255, 255))
        frames.append(f)
    return frames


def test_round_trip_is_exact_as_the_screen_decodes_it():
    frames = scene(8)
    data = gif.encode(frames, [100] * len(frames))
    decoded = _decode_frames(data)
    assert len(decoded) >= len(frames) - 1  # Pillow may merge the two identical last frames
    for want, (got, _) in zip(frames, decoded):
        assert ImageChops.difference(want, got).getbbox() is None


def test_only_what_changes_is_stored():
    frames = scene(20)
    one = gif.encode(frames[:1], [100])
    many = gif.encode(frames, [100] * len(frames))
    assert len(many) < 2 * len(one)  # 19 more frames cost less than a second full frame


def test_more_colours_than_the_palette_never_turn_transparent():
    grad = Image.new("RGB", (W, H))
    grad.putdata([(x * 255 // W, y * 255 // H, (x + y) % 256) for y in range(H) for x in range(W)])
    frames = [grad, grad.transpose(Image.Transpose.FLIP_LEFT_RIGHT)]
    for want, (got, _) in zip(frames, _decode_frames(gif.encode(frames, [100, 100]))):
        assert max(hi for _, hi in ImageChops.difference(want, got).getextrema()) < 64


def test_see_through_frames_are_whole_and_show_the_page_where_clear():
    # A red square that moves right: where it was, the page must show again (no delta trick).
    frames = []
    for x in (0, 100):
        f = Image.new("RGBA", (W, H))
        ImageDraw.Draw(f).rectangle((x, 100, x + 60, 160), fill=(255, 0, 0, 255))
        frames.append(f)
    data = gif.encode(frames, [100, 100], see_through=True)
    with Image.open(io.BytesIO(data)) as im:
        im.seek(1)
        assert im.disposal_method == 2
    decoded = _decode_frames(data)
    for want, (got, _) in zip(frames, decoded):
        assert got.mode == "RGBA" and ImageChops.difference(want, got).getbbox() is None


def test_screen_gifs_use_the_encoder(tmp_path):
    frames = scene(20)
    src = tmp_path / "in.gif"
    frames[0].save(src, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    data = gif_for_screen(src, {"fit": "cover", "x": 50, "y": 50})
    with Image.open(io.BytesIO(data)) as im:
        im.seek(1)
        assert im.disposal_method == 1
    assert len(data) < 2 * len(gif.encode(frames[:1], [100]))
