"""Video backgrounds: frames from the browser, the MJ1 file for the screen (docs/PROTOCOL.md)."""

import io
import struct

import pytest
from PIL import Image

from stashdisplay.link import content as contentlib
from stashdisplay.link import protocol as p
from stashdisplay.link.simulator import _decode_frames
from stashdisplay.media import MediaError, MediaStore


def jpeg(color, size=(640, 360)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def png(color, size=(640, 360)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def framed(frames):
    """What the settings page sends: each JPEG after its length."""
    return b"".join(struct.pack("<I", len(f)) + f for f in frames)


def video(media, frames=None):
    meta = media.add("clip.mp4", b"not decoded by Python")
    media.set_still(meta["id"], png("#204060"))
    if frames is not None:
        media.set_frames(meta["id"], framed(frames))
    return meta["id"]


def test_mjpeg_round_trip_and_offsets():
    frames = [jpeg("#ff0000"), jpeg("#00ff00"), jpeg("#0000ff")]
    blob = p.encode_mjpeg(frames, 83)
    assert blob[:3] == b"MJ1"
    frame_ms, count = struct.unpack_from("<HH", blob, 3)
    assert (frame_ms, count) == (83, 3)
    offsets = struct.unpack_from("<4I", blob, 7)
    assert offsets[0] == 7 + 4 * 4 and offsets[-1] == len(blob)
    assert p.decode_mjpeg(blob) == (83, frames)
    with pytest.raises(p.ProtocolError):
        p.decode_mjpeg(blob[:-1])  # the last offset is the file's size


def test_media_keeps_the_frames_the_browser_sends(tmp_path):
    media = MediaStore(tmp_path / "m")
    vid = video(media)
    assert media.video_frames(vid) == [] and media.frames_path(vid) is None
    frames = [jpeg("#ff0000"), jpeg("#00ff00")]
    meta = media.set_frames(vid, framed(frames))
    assert meta["video_frames"] == 2
    assert media.video_frames(vid) == frames
    with pytest.raises(MediaError):
        media.set_frames(vid, framed([b"not a jpeg"]))
    # At most VIDEO_MAX_SECONDS at VIDEO_FPS: the rest is cut.
    many = [jpeg("#000000", (16, 16))] * (p.VIDEO_FPS * p.VIDEO_MAX_SECONDS + 5)
    assert media.set_frames(vid, framed(many))["video_frames"] == p.VIDEO_FPS * p.VIDEO_MAX_SECONDS


def test_video_background_becomes_an_mjpeg_file(tmp_path):
    media = MediaStore(tmp_path / "m")
    builder = contentlib.ContentBuilder(media)
    page = {"background": {"kind": "video", "value": video(media, [jpeg("#ff0000"), jpeg("#0000ff")]),
                           "fit": "cover", "x": 50, "y": 50}}
    bg = builder.background(page)
    f = builder.files[bg["file"]]
    assert f.format == "mjpeg"
    frame_ms, jpegs = p.decode_mjpeg(f.data)
    assert frame_ms == round(1000 / p.VIDEO_FPS) and len(jpegs) == 2
    with Image.open(io.BytesIO(jpegs[1])) as im:
        assert im.size == (480, 320) and not im.info.get("progressive")
        r, g, b = im.convert("RGB").getpixel((240, 160))
        assert b > 200 and r < 50
    # The simulator plays it like the screen: every frame, at the frame time.
    shown = _decode_frames(f.data)
    assert [d for _, d in shown] == [frame_ms, frame_ms]


def test_video_without_frames_still_shows_its_first_frame(tmp_path):
    media = MediaStore(tmp_path / "m")
    builder = contentlib.ContentBuilder(media)
    page = {"background": {"kind": "video", "value": video(media), "fit": "cover", "x": 50, "y": 50}}
    assert builder.files[builder.background(page)["file"]].format == "jpeg"
