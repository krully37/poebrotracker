"""The settings page: a Flask app served on 127.0.0.1 only.

Protection against other websites open in the same browser:
- the Host header must be 127.0.0.1/localhost on our port (blocks DNS rebinding);
- every page and API call needs the per-install token, given once in the URL
  opened from the tray and then kept in a SameSite=Strict, HttpOnly cookie;
- requests that change something must carry a custom header, which a foreign
  site cannot send without a CORS preflight that we never allow.
"""

import hmac
import io
import logging
import threading
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request, send_file

from .. import autostart
from .. import pages as pagelib
from ..app import App
from ..media import MediaError
from ..render.data import METRICS
from ..render.fonts import BUNDLED, FALLBACK
from ..render.templates import HEADER_BOX, TEMPLATES
from ..render.theme import HEIGHT, WIDTH
from ..render.widgets import FRAMES, WIDGETS
from ..settings import LANGUAGES

log = logging.getLogger(__name__)

STATIC = Path(__file__).with_name("static")
COOKIE = "sd_token"
WRITE_HEADER = "X-Stashdisplay"
SIM_FPS = 20
EVENT_NAMES = {"boot": "Screen start", "launch": "Game start", "levelup": "Level-up", "death": "Death"}
SIM_CHARACTER = ("Testchar", "Witch")
PLACEHOLDERS = ["total", "rate", "session", "today", "best_hour", "league_gain", "div_price",
                "league", "time", "date", "session_since", "session_duration", "synced"]


def schema() -> dict:
    """Everything the editor needs to build its forms, taken from the Python definitions."""
    return {
        "screen": {"width": WIDTH, "height": HEIGHT, "header": list(HEADER_BOX)},
        "templates": [
            {"id": t.id, "name": t.name, "description": t.description,
             "slots": {name: list(box) for name, box in t.slots.items()}}
            for t in TEMPLATES.values()
        ],
        "widgets": [
            {"id": w.id, "name": w.name, "description": w.description, "frame": w.frame,
             "options": [o.__dict__ for o in w.options]}
            for w in WIDGETS.values()
        ],
        "metrics": [{"id": m.id, "label": m.label, "kind": m.kind} for m in METRICS.values()],
        "fonts": [*BUNDLED, *FALLBACK],
        "frames": FRAMES,
        "background_kinds": pagelib.BACKGROUND_KINDS,
        "background_fits": pagelib.BACKGROUND_FITS,
        "placeholders": PLACEHOLDERS,
        "languages": LANGUAGES,
    }


def create_app(app: App) -> Flask:
    web = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
    web.config["MAX_CONTENT_LENGTH"] = 310 * 1024 * 1024  # videos up to 300 MB
    store = app.store

    def port() -> int:
        return store.settings["web"]["port"]

    @web.before_request
    def guard():
        allowed_hosts = {f"127.0.0.1:{port()}", f"localhost:{port()}"}
        if web.testing:
            allowed_hosts.add("localhost")
        if request.host not in allowed_hosts:
            abort(403)
        if request.path.startswith("/static/") or request.path == "/":
            return None
        if not hmac.compare_digest(request.cookies.get(COOKIE, ""), store.token):
            abort(403)
        if request.method not in ("GET", "HEAD"):
            if request.headers.get(WRITE_HEADER) != "1":
                abort(403)
            origin = request.headers.get("Origin")
            if origin and origin.split("://", 1)[-1] not in allowed_hosts:
                abort(403)
        return None

    @web.after_request
    def no_cache(resp: Response) -> Response:
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    @web.get("/")
    def index():
        token = request.args.get("token")
        if token is not None:
            if not hmac.compare_digest(token, store.token):
                abort(403)
            resp = redirect("/")  # drop the token from the address bar
            resp.set_cookie(COOKIE, store.token, httponly=True, samesite="Strict")
            return resp
        if not hmac.compare_digest(request.cookies.get(COOKIE, ""), store.token):
            return send_file(STATIC / "locked.html")
        return send_file(STATIC / "index.html")

    # --- State and saving --------------------------------------------------------

    def state() -> dict:
        return {
            "settings": store.settings,
            "pages": store.pages,
            "has_cookie": bool(store.cookie),
            "media": app.media.list(),
            "status": app.status,
            "live": app.live_data is not None,
            "autostart": {"supported": autostart.supported(), "enabled": autostart.enabled()},
            "screen": screen_status(),
            "events": app.events_status(),
        }

    @web.get("/api/state")
    def get_state():
        return jsonify({**state(), "schema": schema()})

    @web.post("/api/save")
    def save():
        body = request.get_json(force=True) or {}
        app.save(body.get("settings"), body.get("pages"))
        return jsonify(state())

    @web.post("/api/normalize")
    def normalize():
        """Clean pages coming from an imported file before the editor uses them."""
        body = request.get_json(force=True) or {}
        pages = body.get("pages") if isinstance(body.get("pages"), list) else []
        return jsonify({"pages": [pagelib.normalize_page(p) for p in pages if isinstance(p, dict)]})

    @web.get("/api/preset")
    def preset():
        return jsonify({"pages": pagelib.preset()})

    # --- Preview -------------------------------------------------------------------

    @web.post("/api/preview")
    def preview():
        body = request.get_json(force=True) or {}
        page = pagelib.normalize_page(body.get("page") or {})
        png, is_demo = app.preview_png(page, int(body.get("index", 0)), int(body.get("count", 1)),
                                       force_demo=bool(body.get("demo")))
        resp = Response(png, mimetype="image/png")
        resp.headers["X-Demo-Data"] = "1" if is_demo else "0"
        return resp

    # --- Cookie --------------------------------------------------------------------

    @web.post("/api/cookie")
    def set_cookie():
        body = request.get_json(force=True) or {}
        store.cookie = str(body.get("cookie", "")).strip()
        store.save()
        return jsonify({"has_cookie": bool(store.cookie)})

    @web.post("/api/cookie/test")
    def test_cookie():
        # The WealthyExile adapter comes with the reverse-engineering step.
        return jsonify({"ok": False, "code": "not_implemented"})

    # --- Items and icons -----------------------------------------------------------

    @web.get("/api/items")
    def items():
        return jsonify({"items": app.assets.item_names(request.args.get("q", ""))})

    @web.get("/api/icon")
    def icon():
        path = app.assets.icon(request.args.get("name", ""))
        if path is None:
            abort(404)
        return send_file(path, mimetype="image/png")

    @web.get("/api/font/<name>")
    def fontin(name: str):
        """Fontin from the local cache, so the settings page can use the game font too."""
        files = app.assets.fontin()
        if name not in files:
            abort(404)
        return send_file(files[name], mimetype="font/ttf")

    # --- Media ---------------------------------------------------------------------

    @web.post("/api/media")
    def upload():
        file = request.files.get("file")
        if file is None:
            abort(400)
        try:
            return jsonify(app.media.add(file.filename or "upload", file.read()))
        except MediaError as e:
            return jsonify({"error": str(e)}), 400

    @web.post("/api/media/<media_id>/still")
    def media_still(media_id: str):
        try:
            return jsonify(app.media.set_still(media_id, request.get_data()))
        except MediaError as e:
            return jsonify({"error": str(e)}), 400

    @web.get("/api/media/<media_id>/thumb")
    def media_thumb(media_id: str):
        try:
            png = app.media.thumbnail(media_id)
        except MediaError:
            png = None
        if png is None:
            abort(404)
        return Response(png, mimetype="image/png")

    @web.delete("/api/media/<media_id>")
    def media_delete(media_id: str):
        in_use = [p["name"] for p in store.pages
                  if p["background"]["kind"] != "color" and p["background"]["value"] == media_id]
        in_use += [EVENT_NAMES[k] for k in EVENT_NAMES if store.settings["events"][k]["media"] == media_id]
        if in_use:
            return jsonify({"error": "in_use", "pages": in_use}), 409
        try:
            app.media.delete(media_id)
        except MediaError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"media": app.media.list()})

    # --- Screen and simulator ----------------------------------------------------------

    def screen_status() -> dict:
        link = app.link
        out = {"state": link.state if link else "off", **(link.info if link else {}),
               "simulator": app.simulator is not None}
        if app.simulator:
            sim, pair = app.simulator
            out["sim"] = {**sim.status(), "plugged": pair.plugged}
        if app.idle:
            out["idle"] = {"active": app.idle.active, "forced": app.idle.forced}
        return out

    @web.get("/api/screen")
    def get_screen():
        return jsonify(screen_status())

    def simulator():
        if app.simulator is None:
            abort(404)
        return app.simulator

    @web.get("/simulator")
    def simulator_page():
        simulator()
        return send_file(STATIC / "simulator.html")

    @web.get("/api/sim/stream")
    def sim_stream():
        sim, _ = simulator()

        def frames():
            while True:
                buf = io.BytesIO()
                sim.frame().save(buf, "JPEG", quality=90)
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.getvalue() + b"\r\n"
                time.sleep(1 / SIM_FPS)

        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @web.post("/api/sim/touch")
    def sim_touch():
        sim, _ = simulator()
        body = request.get_json(force=True) or {}
        x, y = float(body.get("x", 0)), float(body.get("y", 0))
        {"down": sim.touch_down, "move": sim.touch_move, "up": sim.touch_up}[body.get("kind", "up")](x, y)
        return jsonify({"ok": True})

    @web.post("/api/sim/cable")
    def sim_cable():
        _, pair = simulator()
        if (request.get_json(force=True) or {}).get("plugged"):
            pair.plug()
        else:
            pair.unplug()
        return jsonify(screen_status())

    @web.post("/api/sim/power")
    def sim_power():
        sim, _ = simulator()
        sim.power_cycle()
        return jsonify(screen_status())

    @web.post("/api/sim/idle")
    def sim_idle():
        """Pretend nobody has touched the PC for ages, so the idle cat can be tried at once."""
        simulator()
        if app.idle:
            app.idle.forced = bool((request.get_json(force=True) or {}).get("idle"))
            app.idle.check()
        return jsonify(screen_status())

    # --- Game events -------------------------------------------------------------------

    @web.get("/api/events")
    def get_events():
        return jsonify(app.events_status())

    @web.post("/api/events/character")
    def set_character():
        body = request.get_json(force=True) or {}
        app.characters.set_enabled(str(body.get("name", "")), bool(body.get("enabled")))
        return jsonify(app.events_status())

    @web.post("/api/events/test")
    def test_event():
        kind = (request.get_json(force=True) or {}).get("kind")
        if kind not in EVENT_NAMES:
            abort(400)
        own = app.characters.listing()
        name, level = (own[0]["name"], own[0]["level"]) if own else ("Exile", 92)
        if kind in ("boot", "launch"):
            name = ""  # not about a character
        return jsonify({"played": app.play_event(kind, name, level if kind == "levelup" else None, force=True)})

    @web.post("/api/sim/log")
    def sim_log():
        """Append fake Client.txt lines, so the whole path from the log to the screen runs."""
        simulator()
        kind = (request.get_json(force=True) or {}).get("kind")
        name, char_class = SIM_CHARACTER
        known = {c["name"]: c for c in app.characters.listing()}
        level = (known.get(name, {}).get("level") or 1) + 1
        now = time.strftime("%Y/%m/%d %H:%M:%S")
        stamp = now + " 123456789 cffb0734 [INFO Client 4242] : "
        lines = {
            "launch": [f"{now} ***** LOG FILE OPENING *****"],
            "levelup": [stamp + f"{name} ({char_class}) is now level {min(level, 100)}"],
            "death": [stamp + f"{name} has been slain."],
            # Someone joins the party's area, then levels up: ignored.
            "party": [stamp + "Partymate has joined the area.", stamp + "Partymate (Marauder) is now level 64"],
        }.get(kind)
        if lines is None or app.fake_log is None:
            abort(400)
        with open(app.fake_log, "a", encoding="utf-8", newline="") as f:
            f.writelines(line + "\r\n" for line in lines)
        return jsonify({"ok": True})

    # --- Windows autostart ----------------------------------------------------------

    @web.post("/api/autostart")
    def set_autostart():
        if not autostart.supported():
            return jsonify({"error": "unsupported"}), 400
        autostart.set_enabled(bool((request.get_json(force=True) or {}).get("enabled")))
        return jsonify({"supported": True, "enabled": autostart.enabled()})

    return web


def url(app: App) -> str:
    """The address the tray opens: it carries the token once, then the cookie takes over."""
    return f"http://127.0.0.1:{app.store.settings['web']['port']}/?token={app.store.token}"


def serve_in_background(app: App):
    """Start the settings page on a background thread and return the server (close() stops it).

    Binding happens here, so a port already in use (another copy running) raises OSError now.
    """
    from waitress import create_server

    server = create_server(create_app(app), host="127.0.0.1", port=app.store.settings["web"]["port"], threads=8)
    threading.Thread(target=server.run, daemon=True, name="settings-page").start()
    return server
