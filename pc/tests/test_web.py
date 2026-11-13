import io
import json
import os
import sys

import pytest
from PIL import Image

from stashdisplay import pages as pagelib
from stashdisplay import vault
from stashdisplay.app import App
from stashdisplay.assets import AssetCache
from stashdisplay.media import MediaError, MediaStore
from stashdisplay.settings import Store, normalize_settings
from stashdisplay.web.server import COOKIE, create_app

WRITE = {"X-Stashdisplay": "1"}


def png_bytes(size=(64, 40), color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def gif_bytes() -> bytes:
    frames = [Image.new("RGB", (32, 32), c) for c in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


@pytest.fixture
def app(tmp_path):
    store = Store.load(tmp_path / "settings.json")
    return App(store, AssetCache(root=tmp_path / "cache", offline=True), MediaStore(tmp_path / "media"))


@pytest.fixture
def client(app):
    web = create_app(app)
    web.testing = True
    c = web.test_client()
    c.set_cookie(COOKIE, app.store.token)
    return c


# --- Settings and vault ---------------------------------------------------------------

def test_settings_are_clamped_and_filled():
    s = normalize_settings({"interval": 5, "language": "de", "web": {"port": "80"}, "poeninja": "junk"})
    assert s["interval"] == 60  # never hammer WealthyExile
    assert s["language"] == "en"
    assert s["web"]["port"] == 1024
    assert s["poeninja"] == {"enabled": True, "interval": 1800}


def test_store_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    store = Store.load(path)
    store.cookie = "session=abc"
    pages = pagelib.preset()
    pages[1]["id"] = pages[0]["id"]  # duplicate ids get fixed
    store.update(settings={**store.settings, "language": "fr"}, pages=pages)
    again = Store.load(path)
    assert again.settings["language"] == "fr"
    assert again.cookie == "session=abc"
    assert again.token == store.token
    assert len({p["id"] for p in again.pages}) == len(again.pages)
    assert "session=abc" not in path.read_text()
    if sys.platform != "win32":
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_old_install_gets_the_maps_page_once(tmp_path):
    path = tmp_path / "settings.json"
    old = [p for p in pagelib.preset() if p["id"] != "maps"]
    path.write_text(json.dumps({"version": 1, "pages": old}), encoding="utf-8")
    store = Store.load(path)
    assert [p["id"] for p in store.pages] == ["total", "top", "session", "maps"]
    assert json.loads(path.read_text())["version"] == 2
    # Deleted by hand afterwards: it stays deleted.
    store.update(pages=old)
    assert [p["id"] for p in Store.load(path).pages] == ["total", "top", "session"]


def test_old_install_with_its_own_map_page_is_left_alone(tmp_path):
    path = tmp_path / "settings.json"
    own = {"id": "mine", "name": "My maps", "template": "hero", "slots": {"main": {"widget": "current_map"}}}
    path.write_text(json.dumps({"version": 1, "pages": [own]}), encoding="utf-8")
    assert [p["id"] for p in Store.load(path).pages] == ["mine"]


def test_vault_round_trip_and_bad_input():
    assert vault.unseal(vault.seal("a=b; c=d")) == "a=b; c=d"
    assert vault.seal("") == {}
    assert vault.unseal({"plain": "%%%"}) == ""
    assert vault.unseal({"dpapi": "AAAA"}) == "" or sys.platform == "win32"


# --- Security --------------------------------------------------------------------------

def test_token_in_url_sets_cookie_then_redirects(app):
    web = create_app(app)
    web.testing = True
    c = web.test_client()
    assert b"tray" in c.get("/").data  # locked page without the token
    assert c.get("/api/state").status_code == 403
    assert c.get("/?token=wrong").status_code == 403
    r = c.get(f"/?token={app.store.token}")
    assert r.status_code == 302 and r.headers["Location"] == "/"
    assert "HttpOnly" in r.headers["Set-Cookie"] and "SameSite=Strict" in r.headers["Set-Cookie"]
    assert c.get("/api/state").status_code == 200


def test_foreign_host_is_refused(client):
    assert client.get("/api/state", headers={"Host": "evil.example:47821"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403


def test_writes_need_header_and_same_origin(client):
    assert client.post("/api/save", json={}).status_code == 403
    bad_origin = {**WRITE, "Origin": "http://evil.example"}
    assert client.post("/api/save", json={}, headers=bad_origin).status_code == 403
    assert client.post("/api/save", json={}, headers={**WRITE, "Origin": "http://localhost"}).status_code == 200


def test_state_never_contains_the_cookie(client, app):
    app.store.cookie = "secret-session"
    body = client.get("/api/state").get_data(as_text=True)
    assert "secret-session" not in body
    assert json.loads(body)["has_cookie"] is True


# --- API -------------------------------------------------------------------------------

def test_preview_returns_a_screen_sized_png(client):
    page = pagelib.preset()[0]
    r = client.post("/api/preview", json={"page": page, "index": 0, "count": 4}, headers=WRITE)
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert r.headers["X-Demo-Data"] == "1"
    assert Image.open(io.BytesIO(r.data)).size == (480, 320)


def test_save_normalizes_what_the_editor_sends(client, app):
    pages = pagelib.preset()
    pages[0]["slots"]["main"]["size"] = "999"
    pages[0]["slots"]["side"] = {"widget": "nope"}
    r = client.post("/api/save", json={"settings": {"interval": 1}, "pages": pages}, headers=WRITE)
    assert r.status_code == 200
    assert app.store.settings["interval"] == 60
    assert app.store.pages[0]["slots"]["main"]["size"] == 150
    assert app.store.pages[0]["slots"]["side"] is None


def test_import_drops_junk(client):
    pages = [{"template": "grid4", "name": "Mine"}, "junk", {"template": "unknown"}]
    r = client.post("/api/normalize", json={"pages": pages}, headers=WRITE)
    out = r.get_json()["pages"]
    assert [p["template"] for p in out] == ["grid4", "hero"]
    assert set(out[0]["slots"]) == {"top1", "top2", "bottom1", "bottom2"}


def test_media_upload_still_and_delete(client, app):
    r = client.post("/api/media", data={"file": (io.BytesIO(png_bytes()), "bg.jpg")},
                    headers=WRITE, content_type="multipart/form-data")
    meta = r.get_json()
    assert meta["kind"] == "image" and meta["width"] == 64
    assert client.get(f"/api/media/{meta['id']}/thumb").mimetype == "image/png"

    pages = pagelib.preset()
    pages[0]["background"] = {"kind": "image", "value": meta["id"], "fit": "cover", "x": 50, "y": 50}
    client.post("/api/save", json={"pages": pages}, headers=WRITE)
    preview = client.post("/api/preview", json={"page": pages[0]}, headers=WRITE)
    assert Image.open(io.BytesIO(preview.data)).convert("RGB").getpixel((240, 312)) != (0, 0, 0)

    r = client.delete(f"/api/media/{meta['id']}", headers=WRITE)
    assert r.status_code == 409 and r.get_json()["pages"] == [pages[0]["name"]]
    client.post("/api/save", json={"pages": pagelib.preset()}, headers=WRITE)
    assert client.delete(f"/api/media/{meta['id']}", headers=WRITE).get_json()["media"] == []


def test_media_kinds_and_rejects(tmp_path):
    media = MediaStore(tmp_path)
    gif = media.add("loop.gif", gif_bytes())
    assert gif["kind"] == "gif" and gif["frames"] == 3
    video = media.add("clip.mp4", b"\x00" * 100)
    assert video["kind"] == "video" and video["needs_still"]
    assert media.still_path(video["id"]) is None
    assert media.set_still(video["id"], png_bytes())["needs_still"] is False
    with pytest.raises(MediaError):
        media.add("notes.txt", b"hello")
    with pytest.raises(MediaError):
        media.get("../settings")


def test_event_test_button_covers_screen_and_game_start(client, app):
    for kind in ("boot", "launch", "levelup", "death", "lastportal"):
        r = client.post("/api/events/test", json={"kind": kind}, headers=WRITE)
        assert r.status_code == 200 and r.get_json() == {"played": False}  # no screen in this test
    assert client.post("/api/events/test", json={"kind": "nope"}, headers=WRITE).status_code == 400
    assert set(app.store.settings["events"]) == {"client_log", "boot", "launch", "levelup", "death", "lastportal"}


def test_an_unreadable_settings_file_does_not_stop_the_app(tmp_path):
    """The .exe has no window to say why it did not start: it starts with the defaults instead,
    and keeps the file it could not read beside the new one."""
    path = tmp_path / "settings.json"
    path.write_text('{"settings": {"language": "fr"}, "pages": [', encoding="utf-8")  # cut short
    store = Store.load(path)
    assert store.settings["language"] == "en" and [p["id"] for p in store.pages] == [p["id"] for p in pagelib.preset()]
    assert (tmp_path / "settings.broken.json").read_text(encoding="utf-8").startswith('{"settings": {"language": "fr"}')
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2  # a good file again

    # Valid JSON with values of the wrong kind: each falls back on its own, the rest is kept.
    path.write_text(json.dumps({"version": "2", "settings": {"language": "fr"}, "pages": "none", "cookie": "a=b",
                                "token": 5}), encoding="utf-8")
    store = Store.load(path)
    assert store.settings["language"] == "fr" and store.pages and store.cookie == "" and isinstance(store.token, str)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert Store.load(path).pages
