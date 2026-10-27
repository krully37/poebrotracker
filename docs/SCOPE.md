# Scope (v1)

Agreed 2026-10-27. This updates [BRIEF.md](BRIEF.md) wherever the two differ.
Items marked **[PROPOSED]** are technical choices made by Claude and still open to change.

## 1. What changed from the brief

| Topic | Brief | Now |
|---|---|---|
| Who draws the pages | The screen, from numbers sent by the PC | **The PC renders each page as an image.** The screen stores and shows the images, and handles anything that must be fast locally |
| Pages | 4 fixed pages | **Any number of pages**, all editable in a **settings page** with a live preview. A preset works out of the box |
| Page 4 | To be defined | Covered by the custom pages, with the widgets listed in §4 |
| Backgrounds | Black | Per-page background: **still image, GIF or video** |
| Disconnected | After 10–15 min of silence | 30 s heartbeat; **"PC disconnected" after ~90 s**, and the screen **dims** |
| Divine price | WealthyExile, else poe.ninja | Pluggable sources, in order: worked out from WealthyExile → the friends' own pricer (later) → poe.ninja |

The brief's non-negotiable constraints are unchanged. Nothing touches the game, and the cookie stays on the PC (the screen only ever receives images). WealthyExile is polled about every 5 minutes, and no personal cloud service is used.

## 2. Architecture

```
                      PC (Windows .exe, runs in background)                     Screen (ESP32-S3)
 WealthyExile --HTTPS+cookie--> fetch (every 5 min)                             flash: backgrounds (img/GIF/MJPEG)
 poe.ninja (≤ every 30 min) --> price sources                                    PSRAM: compressed page overlays
                                history + stats (div/h, session, league...)      compositor: overlay over bg frame
                                page renderer (Pillow) ──overlays──USB──────────> slide animation on swipe
 browser <── localhost ──────── settings page + exact preview (same renderer)    touch: swipe / tap / long press
                                                       <──── refresh, reset ───  offline screen + dimming
```

- **Overlay** = what the PC renders for a page: the text, numbers and charts on a transparent layer. The screen composites it over the page's background, frame by frame when the background is animated.
- The PC re-renders a page's overlay when its data changes, and once a minute for the clock and "synced X min ago".
- The screen keeps every page's overlay compressed in PSRAM and decompresses the visible one. With mostly-transparent overlays this means there is effectively no page cap.
- The screen draws only one thing on its own: the **offline screen** (PC disconnected, waiting for PC). It needs no data from the PC.

## 3. Screen behaviour

- Landscape 480×320, rotated in software (the panel has no hardware rotation). Full-frame pushes only.
- **Swipe left/right**: change page, with a slide animation.
- **Tap**: ask the PC for a refresh. The PC refuses if the last fetch was under 60 s ago, and the screen shows "too soon".
- **Long press** on the Session page: reset the session.
- **Pagination dots**, drawn by the screen. They switch to a "4/9" counter when there are many pages.
- **PC disconnected** after 90 s with no message, and the backlight dims. Full brightness returns on reconnect.
- **Stale data** badge (rendered by the PC) if the last successful fetch is over 15 min old.
- Firmware is flashed by the project owner before handing the screen over. The friend never flashes.

Frame rate for slides and animated backgrounds is **unknown until the hardware arrives**. Community reports show software rotation is the bottleneck: about 4 fps with a naive approach. The plan is to rotate in internal SRAM strips and push with DMA, and to measure this first.

## 4. Pages and widgets

**Preset out of the box** (all editable):
1. **Total**: stash value in divines, div/h in green, sparkline, "synced X min ago", clock.
2. **Top**: the 8 most valuable stacks plus per-tab totals.
3. **Session**: gain since the session started, and the divine price in chaos.

**Settings page** (served by the .exe on localhost, opened in the browser):
- Add, remove, reorder, hide or duplicate any page, built-in ones included.
- Edit a page's widgets with a **live preview that is exactly what the screen shows**.
- Set each page's background: upload an image, GIF or video. The PC resizes, crops and converts it.
- Configure league, poe.ninja items, intervals and the cookie in one place, with no hand-edited files.

**Widgets for v1:**
- Stash total, div/h, sparkline, session gain, top stacks, tab totals, divine price (the built-in pages are made from these).
- **Value since league start**: current value minus the first value recorded in the league.
- **poe.ninja item price**: one or more items, batched into one request per poe.ninja category, at most every 30 min.
- **Stack or tab value** from WealthyExile: a specific stack or stash tab.
- **Session/day stats**: gain today, best hour, and so on, from local history.
- Text and clock (for layout).

**Session** resets when the script starts and on a long press. It does not reset daily.

## 5. Backgrounds and media

- Formats: **still image, GIF, video** (video is converted to MJPEG on the PC with ffmpeg).
- Stored in the screen's flash (a ~10–12 MB filesystem partition, out of 16 MB). The settings page shows how much space is used and refuses uploads that don't fit. That's roughly 20–40 s of 480×320 video in total.
- **[PROPOSED]** Get ffmpeg through `imageio-ffmpeg`, which downloads it on first use, instead of bundling it (keeps the .exe small). Bundling is the alternative if your friend's PC can't download it.

## 6. Data sources

- **WealthyExile** (core): stash value, items and tabs. No documented API, so we reverse-engineer the site's own JSON requests. All of that lives in one adapter module, with a `--dump` mode for raw responses.
- **Divine price**: worked out from WealthyExile if it gives totals in both chaos and divines, else the friends' pricer (later), else poe.ninja.
- **poe.ninja**: official economy endpoints, used for the item-price widget and the divine price fallback. It sends a descriptive User-Agent, respects the cache and ETags, and polls at most every 30 min. Note: poe.ninja's docs ask desktop apps to proxy through their own backend. We accept that small deviation at this request rate.
- **History**: a local file in `%APPDATA%\stashdisplay`, which survives restarts. It feeds div/h, the sparkline, session, league-start and day stats.

## 7. Delivery

- **Private GitHub repo** (`krully37/poebrotracker`).
- **PC**: a single Windows `.exe` built by GitHub Actions (PyInstaller, no console window). It includes an auto-start toggle (a registry Run key) and a log file. Your friend needs no Python.
- **Firmware**: built with PlatformIO. CI checks that it compiles. Flashed by you from the Mac.
- Developed on macOS. The PC code runs on both macOS and Windows so it can be tested on the Mac, and Windows-only parts (auto-start, .exe, COM port behaviour) get a final test on a Windows PC.

## 8. Proposed technical choices [PROPOSED]

| Part | Choice | Why |
|---|---|---|
| PC language | Python 3.12+ | The brief's recommendation, with a good ecosystem for images (Pillow) and serial (pyserial) |
| Page rendering | Pillow, with bundled open-licence fonts | The same code produces the preview and the screen image |
| Settings page | Small local web server (Python) + plain HTML/JS, no build step | Nothing to install, and it opens in any browser |
| Overlay transfer | RGB565 + 4-bit alpha, zlib-compressed, sent in chunks over USB serial | The ESP32 ROM has zlib inflate built in. Mostly-transparent overlays compress very well |
| Firmware | Arduino core 3.x + Arduino_GFX (panel driver only), own compositor, JPEGDEC / AnimatedGIF (bitbank2) for media | No LVGL: it wouldn't be faster here, and the PC now does the layout |
| Filesystem on screen | LittleFS | Standard on ESP32, survives power loss |

## 9. Open questions

- Exact WealthyExile responses: do they include items, tabs, a chaos and divine total, league-start history? (Settled during reverse-engineering.)
- What the friends' pricer is and how it exposes prices (local app? file? HTTP?).
- Real frame rate for slides, GIF and video (measured as soon as the hardware arrives).
- USB on the board: native USB or CH340 (matters for the Windows driver and for how fast data can be sent).

## 10. Build order

1. Repo, CI skeleton, this scope.
2. PC: history, stats and the page renderer in **demo mode**, producing PNG previews on the Mac (no hardware needed).
3. Settings page with live preview and page editor.
4. Serial protocol (overlay transfer, touch events, heartbeat), tested against a simulated screen on the PC.
5. **Hardware arrives**: validate pinout, rotation, touch, then measure frame rates.
6. Firmware: compositor, slides, offline screen, dimming, then GIF and video backgrounds.
7. WealthyExile reverse-engineering (with your friend logged in), then the adapter.
8. Windows .exe, auto-start, install guide; final test on a Windows PC.
