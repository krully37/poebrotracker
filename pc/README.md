# PC app (`stashdisplay`)

Python 3.12+. Runs on Windows (target) and macOS (development).

## Setup

```bash
cd pc
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

On Windows, use `.venv\Scripts\pip` and `.venv\Scripts\python` instead.

## Run the app

```bash
.venv/bin/python -m stashdisplay run
```

This starts the settings page on `127.0.0.1` a tray icon, and the link to the screen over USB (found automatically) (click it, or right-click → Open settings). The settings page opens by itself on the first start. Starting a second copy only opens the settings of the running one. Add `--no-tray` to print the settings address in the terminal instead, and `--offline` to skip downloads.

### Without the screen: the simulator

```bash
.venv/bin/python -m stashdisplay run --no-tray --simulator
```

The app then talks to a simulated screen instead of the USB one, over the real protocol ([docs/PROTOCOL.md](../docs/PROTOCOL.md)). Open the **Simulator** tab in the settings page: it shows the screen exactly as the firmware will composite it. Click to tap, drag sideways to change page, and hold on a session or div/h value to reset it. The page also has buttons to unplug the cable and power-cycle the screen, and to write fake level-up, death and party-member lines to a test `Client.txt` (`Client-sim.txt` in the app folder), which the app follows like the game's own log.

The **Now playing** card follows Windows' media session (Spotify, browsers, most players), and its buttons control it. On the Mac, or with `--fake-media` on Windows, a pretend player with three tracks stands in.

The settings, pages, uploaded backgrounds and log live in `%APPDATA%\stashdisplay` on Windows and `~/Library/Application Support/stashdisplay` on macOS. Set `STASHDISPLAY_HOME` to use another folder, for example a throwaway one while testing.

The page is only reachable from this PC. It needs the per-install token, which the tray link carries once and a cookie keeps afterwards, so other websites open in the browser cannot read or change it.

## Preview the pages with demo data

```bash
.venv/bin/python -m stashdisplay preview --out preview --scale 2
```

The first run downloads the game icons and the Fontin font into the local cache (add `--offline` to skip this and use fallbacks). This writes, for each page, `pageN-<id>.png` (exactly what the screen will show), `pageN-<id>-overlay.png` (the transparent layer sent to the screen), and `all-pages.png` with every page side by side.

## Windows app (.exe)

```bash
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python packaging\build.py

This writes `dist\StashDisplay.exe`: one file, no console window, which starts the app when
double-clicked. GitHub Actions builds the same on every push (`.github/workflows/build.yml`); a `v*`
tag attaches it to a release. The friend's guide is [docs/INSTALL.md](../docs/INSTALL.md).

## Tests

```bash
.venv/bin/python -m pytest
```

## Code map

| Module | Role |
|---|---|
| `history.py` | Totals over time, saved to `history.json` |
| `stats.py` | div/h, session gain, today, best hour, sparkline |
| `pages.py` | Page definitions (JSON), defaults, preset pages |
| `render/templates.py` | Page templates and their slots |
| `render/widgets.py` | Widget types, their options, how they draw |
| `render/renderer.py` | Header, overlay, background, dots, preview |
| `render/data.py` | Metrics and formatting for a render |
| `assets.py` | Downloads and caches game icons (via poe.ninja) and Fontin |
| `render/frames.py` | PoE tooltip-style frames and the page header bar |
| `sources/` | Data sources: `demo.py` now, WealthyExile and poe.ninja later |
| `settings.py` | `settings.json`: settings, pages, the sealed cookie, the page token |
| `vault.py` | Cookie encryption (Windows DPAPI; base64 + owner-only file elsewhere) |
| `media.py` | Uploaded backgrounds: images, GIFs, videos and their still frames |
| `gamelog.py` | Follows the game's `Client.txt`: level-ups and deaths, which characters are the friend's |
| `nowplaying.py` | What the PC plays (Windows media session, or a fake player) and the media buttons |
| `app.py` | The running app shared by the settings page and the tray |
| `web/` | Settings page: Flask API (`server.py`) and the Alpine.js editor (`static/`) |
| `tray.py` | Tray icon and menu |
| `autostart.py` | "Start with Windows" (registry Run key) |
| `link/protocol.py` | Serial framing, message types, overlay format, timings |
| `link/client.py` | PC end of the link: finds the screen, syncs pages and files, handles touch events |
| `link/content.py` | What the screen should hold: overlays, backgrounds and event animations as JPEG/GIF, reset zones |
| `assets/anims/` | Built-in level-up and death animations (see its README) |
| `link/simulator.py` | Simulated screen (what the firmware will do) |
| `link/transport.py` | Serial port detection, and the in-process cable used by the simulator |
