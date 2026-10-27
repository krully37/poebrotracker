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
| Game events | Not in the brief | **Level-up and death animations**, triggered by reading the game's `Client.txt` log (see §5b) |

The brief's non-negotiable constraints are unchanged. Nothing touches the game, and the cookie stays on the PC (the screen only ever receives images). WealthyExile is polled about every 5 minutes, and no personal cloud service is used.

## 2. Architecture

```
                      PC (Windows .exe, runs in background)                     Screen (ESP32-S3)
 WealthyExile --HTTPS+cookie--> fetch (every 5 min)                             flash: backgrounds (img/GIF/MJPEG)
 poe.ninja (≤ every 30 min) --> price sources                                    PSRAM: compressed page overlays
 Client.txt (tail, read-only) -> event watcher ──"play anim"──USB──────────────> full-screen event animations
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
- **Long press** on a value that can be reset: a ring is drawn around the finger and fills in about 1.5 s; lifting early cancels. When it closes, that value resets. Resettable values: **session** (gain, chart) and **div/h** (the rate starts counting again from that moment). League start, today and best hour cannot be reset, so a long press there does nothing. The PC tells the screen which areas of each page are resettable.
- **Pagination dots**, drawn by the screen. They switch to a "4/9" counter when there are many pages.
- **Boot animation**: at power-on the screen plays a GIF from its own flash once (no PC needed), then shows the pages, or the offline screen if the PC is not there yet. A default animation ships out of the box; the friend can replace it in the settings page (same upload and conversion as backgrounds).
- **PC disconnected** after 90 s with no message, and the backlight dims. Full brightness returns on reconnect.
- **Stale data** badge (rendered by the PC) if the last successful fetch is over 15 min old.
- Firmware is flashed by the project owner before handing the screen over. The friend never flashes.

Frame rate for slides and animated backgrounds is **unknown until the hardware arrives**. Community reports show software rotation is the bottleneck: about 4 fps with a naive approach. The plan is to rotate in internal SRAM strips and push with DMA, and to measure this first.

## 4. Pages and widgets

**Preset out of the box** (all editable):
1. **Total**: stash value in divines, div/h in green, sparkline, "synced X min ago", clock.
2. **Top**: the 8 most valuable items (several of the same item count as one row), plus per-tab totals.
3. **Session**: gain since the session started, and the divine price in chaos.

A fourth example page, **League** (since league start, today, best hour, item prices), was dropped on 2026-10-27: "since league start" is about the same number as the stash total, and today and best hour are already on Total and Session. Its widgets and metrics stay available for custom pages.

**Settings page** (served by the .exe on localhost, opened in the browser):
- Add, remove, reorder, hide or duplicate any page, built-in ones included.
- Edit a page's widgets with a **live preview that is exactly what the screen shows**.
- Set each page's background: upload an image, GIF or video. The PC resizes, crops and converts it.
- Configure league, poe.ninja items, intervals and the cookie in one place, with no hand-edited files.

**Widgets for v1:**
- Stash total, div/h, sparkline, session gain, most valuable items, tab totals, divine price (the built-in pages are made from these).
- **Value since league start**: current value minus the first value recorded in the league.
- **poe.ninja item price**: one or more items, batched into one request per poe.ninja category, at most every 30 min.
- **Stack or tab value** from WealthyExile: a specific stack or stash tab.
- **Session/day stats**: gain today, best hour, and so on, from local history.
- Text and clock (for layout).

**Session** resets when the script starts and on a long press. It does not reset daily.

## 4b. Visual style (PoE look)

Decided 2026-10-27. This is a private tool that is never distributed, so it uses the game's own art. That art is never committed to the repo.

- **Real item icons**, from GGG's image server (`web.poecdn.com`), using the links in poe.ninja's economy data. The full-size originals (`/image/Art/...`) are used when available. Divination cards share the game's card inventory icon.
- **Fontin** (the game's font) for titles, labels, item names and numbers. It is downloaded from the designer's site (exljbris.com), whose licence allows free use but forbids redistribution. Fontin has no "×", so quantities are written "x148".
- **Tooltip-style frames redrawn in code**: gradient header bar, gold-brown borders, diamond ornaments. Each slot can use `tooltip` (header with the title), `plain` (frame only) or `none`.
- Icons and fonts are **downloaded on first run and cached** in `%APPDATA%\stashdisplay\cache`. The icon index is refreshed at most once a week (~26 poe.ninja requests). Without the cache (offline, or download failed), the renderer falls back to bundled fonts and a drawn divine orb.
- Not used: in-game text colours by item type.

## 4c. Settings page (step 3)

Decided 2026-10-27.

**Access**
- A **tray icon** next to the Windows clock shows the status (connected, last sync, errors). Its menu has Open settings, Refresh now, Start with Windows, and Quit.
- The settings page opens in the browser. It is served on `127.0.0.1` only, and requests are checked so that other websites cannot change settings or read the cookie (a per-install token plus Host/Origin checks).
- The interface is in **English and French**, with a switch. All text comes from a translation file. Item names stay as the game names them.

**Editor**
- Layout: the page list on the left (drag to reorder, show/hide, duplicate, add), the preview in the middle (480×320 at 2× zoom), and the options of the selected slot on the right.
- **Click a slot on the preview** to select it. The side panel shows the widget type, its options (forms generated from each widget's option list), and the frame style. The page template and background are chosen under the preview.
- The **preview is the real renderer**: the PC renders it after each edit, outdated requests are cancelled, and images are swapped without flicker. It shows the friend's **real data** once synced, with demo data before that and a switch to force demo data.
- **Saving:** edits update the preview immediately, and **Save** writes the settings and sends the pages to the screen. Undo and redo work while editing, plus "Revert to last saved".
- Extras in this step: **export/import** pages as a file, **reset to preset**, and a **fixed size** option for numbers. Swapping slots by drag comes later.

**Settings beyond pages**
- WealthyExile cookie: pasted into a masked field, with a "Test" button. On Windows it is stored encrypted with DPAPI (Windows' per-user encryption), not as plain text. It is not read from the browser automatically (Chrome encrypts its cookies, and that would mean touching the browser's credential store).
- League, intervals, poe.ninja items, and Start with Windows.

**Backgrounds in this step**
- Upload, crop and convert images, GIFs and videos. The preview shows a still frame. The animated preview comes with the firmware media step, once the real frame rate is known. The browser extracts a video's still frame, so the settings page itself needs no ffmpeg; ffmpeg only comes in with the MJPEG conversion.

**Tech**
- **Flask** served by **Waitress** (stable, pure Python, works well on Windows), plus **Alpine.js** bundled as a file (no CDN, no build step).
- **Render speed:** 55–80 ms per page today (M-series Mac). The target is under 20 ms by cropping drawing work to each element's area instead of the full screen.

## 5. Backgrounds and media

- Formats: **still image, GIF, video** (video is converted to MJPEG on the PC with ffmpeg).
- Stored in the screen's flash (a ~10–12 MB filesystem partition, out of 16 MB). The settings page shows how much space is used and refuses uploads that don't fit. That's roughly 20–40 s of 480×320 video in total.
- **[PROPOSED]** Get ffmpeg through `imageio-ffmpeg`, which downloads it on first use, instead of bundling it (keeps the .exe small). Bundling is the alternative if your friend's PC can't download it.

## 5b. Game events (level-up, death)

- PoE1 has no combat log. The game writes a chat and events log, `Client.txt`, in its `logs` folder. The PC **tails** that file read-only, starting from the end, because it can be several GB. This is the same passive approach as many community tools, and it does not touch the game (no memory reading, no input, no overlay).
- Built as a **general "log event → animation" system** configured in the settings page. **v1 events:**
  - **Level-up**, from lines like `: CharName (Class) is now level 92`
  - **Death**, from lines like `: CharName has been slain.`
- Only system lines count (`] : ` right after the log prefix), so typing those words in chat triggers nothing.
- **Own characters only.** A name in a level-up line is taken as one of the friend's characters, unless that name was ever seen joining or leaving the area (only other players do that). The settings page lists the learned characters with a tick box each. Known gaps: a party member who levels up before ever sharing an area is learned by mistake (untick it), and a new character that dies before its first level-up is not known yet.
- **Every level-up plays**; there is no level threshold. Each event can be turned on or off.
- **Full-screen animation**, then back to the current page. The built-in animations are GIFs made for this project (`pc/stashdisplay/assets/anims/`), shown as they are, with no text on top. A GIF plays once; one shorter than 3 s loops until 3 s, and anything past 10 s is cut. The friend can replace each one with their own GIF, image or video in the settings page.
- **Until a GIF exists** (or if it does not fit on the screen), the PC sends a text card instead: "Level 92" or "Slain", with the character name, for 4 s.
- **Bursts:** the newest event replaces the one playing, except that a level-up never cuts a death short.
- Animations are stored on the screen in advance, so the PC only sends a small "play" message and playback starts within about a second. Events that happen while the screen is unplugged are dropped, not queued.
- The `Client.txt` path is auto-detected (the standalone install, Steam and its other library folders; the most recently written one wins) and can be changed in settings. The file is read from its end at start-up, opened only for each read (so it can still be deleted), and read from the start again when it is emptied or replaced.
- Animations share the flash budget in §5 with the backgrounds and the boot animation.

## 6. Data sources

- **WealthyExile** (core): stash value, items and tabs. No documented API, so we reverse-engineer the site's own JSON requests. All of that lives in one adapter module, with a `--dump` mode for raw responses.
- **Divine price**: worked out from WealthyExile if it gives totals in both chaos and divines, else the friends' pricer (later), else poe.ninja.
- **poe.ninja**: official economy endpoints, used for the item-price widget and the divine price fallback. It sends a descriptive User-Agent, respects the cache and ETags, and polls at most every 30 min. Note: poe.ninja's docs ask desktop apps to proxy through their own backend. We accept that small deviation at this request rate.
- **History**: a local file in `%APPDATA%\stashdisplay`, which survives restarts. It feeds div/h, the sparkline, session, league-start and day stats.
- **XP/hour** (wanted, not scheduled yet): `Client.txt` only logs level-ups, not experience. GGG's official API returns each character's `experience` (`GET /character`, scope `account:characters`), and desktop apps may use it as a "public client" (OAuth with PKCE and a local redirect). This needs the app registered with GGG, and the friend logging in to his PoE account once to approve it. To be decided before step 7.

## 7. Delivery

- **Private GitHub repo** (`krully37/poebrotracker`).
- **PC**: a single Windows `.exe` built by GitHub Actions (PyInstaller, no console window). It includes an auto-start toggle (a registry Run key) and a log file. Your friend needs no Python.
- **Firmware**: built with PlatformIO. CI checks that it compiles. Flashed by you from the Mac.
- Developed on macOS. The PC code runs on both macOS and Windows so it can be tested on the Mac, and Windows-only parts (auto-start, .exe, COM port behaviour) get a final test on a Windows PC.

## 8. Proposed technical choices [PROPOSED]

| Part | Choice | Why |
|---|---|---|
| PC language | Python 3.12+ | The brief's recommendation, with a good ecosystem for images (Pillow) and serial (pyserial) |
| Page rendering | Pillow; PoE look (§4b); bundled open-licence fonts as fallback | The same code produces the preview and the screen image |
| Settings page | Flask + Waitress, Alpine.js bundled, no build step (see §4c) | Stable, nothing to install, and it opens in any browser |
| Overlay transfer | RGB565 + 4-bit alpha, zlib-compressed, sent in chunks over USB serial | The ESP32 ROM has zlib inflate built in. Mostly-transparent overlays compress very well |
| Firmware | Arduino core 3.x + Arduino_GFX (panel driver only), own compositor, JPEGDEC / AnimatedGIF (bitbank2) for media | No LVGL: it wouldn't be faster here, and the PC now does the layout |
| Filesystem on screen | LittleFS | Standard on ESP32, survives power loss |

## 9. Open questions

- Exact WealthyExile responses: do they include items, tabs, a chaos and divine total, league-start history? (Settled during reverse-engineering.)
- What the friends' pricer is and how it exposes prices (local app? file? HTTP?).
- `Client.txt` line formats: **checked on 2026-10-27 against a real English-client log** (the owner's, Steam install, March to August 2026, 166k lines). All 333 level-up lines and every "has been slain." system line match; chat lines with "died" or "slain" are ignored. Party members' level-ups and deaths **do** appear there; all of the ~20 other players in that log were also seen joining or leaving the area, so none was learned as an own character (zero false animations). Non-Latin names (Chinese, Korean, Cyrillic) parse fine. The friend's client is in English too (confirmed 2026-10-27), so no other language is needed.
- Windows checks on 2026-10-27 (no screen): tests pass on Python 3.13; `Client.txt` was found through Steam's registry key and `libraryfolders.vdf` on another drive; the simulator and the fake log events work; the DPAPI vault round-trips. Real USB is still untested.
- Real frame rate for slides, GIF and video (measured as soon as the hardware arrives).
- USB on the board: native USB or CH340 (matters for the Windows driver and for how fast data can be sent).
- XP/hour: register an app with GGG's developer program (see §6), and whether that registration is approved.

## 10. Build order

1. Repo, CI skeleton, this scope.
2. PC: history, stats and the page renderer in **demo mode**, producing PNG previews on the Mac (no hardware needed).
3. Settings page with live preview and page editor.
4. Serial protocol (overlay transfer, file transfer to the screen's flash, touch events, heartbeat), tested against a simulated screen on the PC. The simulator is also a page in the settings app: the screen exactly as the firmware will composite it, driven with the mouse. The protocol is specified in `docs/PROTOCOL.md`.
4b. `Client.txt` event watcher (level-up, death), tested against sample log lines, then a real log.
5. **Hardware arrives**: validate pinout, rotation, touch, then measure frame rates.
6. Firmware: compositor, slides, offline screen, dimming, then GIF and video backgrounds, and the boot animation.
7. WealthyExile reverse-engineering (with your friend logged in), then the adapter.
8. Windows .exe, auto-start, install guide; final test on a Windows PC.
