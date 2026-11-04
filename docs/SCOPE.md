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
| Divine price | WealthyExile, else poe.ninja | PoE Pricer (the friends' own pricer) when it runs, else WealthyExile's own (§6) |
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
- **Tap**: ask the PC for a refresh. The PC ignores it if the last fetch was under 60 s ago, silently (decided 2026-10-29: the "Too soon" toast was annoying).
- **Long press** on a value that can be reset: a banner in the tooltip style shows at the top, "Resetting div/h" or "Resetting session", with a gold bar that fills in about 1.5 s; lifting early cancels. When it is full, that value resets. (Decided 2026-10-29 on the real screen: the first design, a ring around the finger, was hidden by the finger.) Resettable values: **session** (gain, chart) and **div/h** (the rate starts counting again from that moment). League start, today and best hour cannot be reset, so a long press there does nothing. The PC tells the screen which areas of each page are resettable.
- **Pagination dots**, drawn by the screen. They switch to a "4/9" counter when there are many pages.
- **Start animation** ("Screen start" in settings, the `boot` file): at power-on the screen plays it from its own flash (no PC needed), then shows the pages, or the offline screen if the PC is not there yet. It follows the event rule in §5b (a GIF plays once, looping until 3 s if shorter, cut at 10 s). Decided 2026-10-28:
  - The built-in one is the owner's cat spinning: 5 turns in 4 s, made from one sharp frame of `images/spin.mp4` (the real spin is too blurred; steps in `pc/stashdisplay/assets/anims/README.md`).
  - It also plays **each time the PC connects**: the app starting, the cable plugged back in, or a reconnect after the link dropped. The PC skips it when the screen says it is already playing it, which is the case right after a power-on.
  - The PC sends and updates the `boot` file like any other. It can be turned off (the file is then deleted), and the friend can replace it in the settings page (same upload and conversion as the event animations).
  - The game start (§5b) uses the same cat by default. When both are the same, the screen keeps one copy and the game start plays the `boot` file.
- **Idle cat** (decided 2026-10-29): when the PC is not being used, the screen shows the owner's cat (the left one in `images/idle-photo.jpg`, cut out) bouncing off the screen's edges on black, like the old Windows screen savers.
  - "Not used" is Windows' own idle clock: no keyboard or mouse input (`GetLastInputInfo`, read once a second, nothing hooked). The default is **10 minutes**, editable in settings (1 to 120), with an on/off switch. No cat while music or a video plays (the Now playing source says so). Outside Windows the idle time is unknown, so the cat never shows there, except with the simulator's "Pretend the PC is idle" button.
  - It bounces off the edges of the cat itself, not of its box, and **turns to face where it goes** (upright going right, upside down going left), easing into the new direction after each bounce. 100 px/s, 150 px wide, full brightness.
  - **The screen animates it**: the PC sends the cut-out cat once (about 13 kB in flash, the `idle` file) and then only says "idle" or "not idle". Turning a 150×130 sprite each frame is a few milliseconds on the ESP32-S3; if the real frame rate says otherwise, the fallback is turned copies pre-rendered by the PC (72 of them, about 1 MB).
  - A touch on the cat shows the pages for 1 minute, then the cat comes back if the PC is still idle. That touch does nothing else (no refresh). Event animations play as usual and the cat comes back after them. PC disconnected wins: offline screen and dimming as always.
  - Built-in only for now: replacing the cat from the settings page can come later.
- **PC disconnected** after 90 s with no message, and the backlight dims. Full brightness returns on reconnect.
- **Stale data** badge (rendered by the PC) if the last successful fetch is over 15 min old.
- Firmware is flashed by the project owner before handing the screen over. The friend never flashes.

Frame rates, measured in step 5 (2026-10-29, numbers in §9): a full frame goes to the panel at **61 fps**, and an overlay composited over a background at **27 fps** so far. The composite is now the slow part; step 6 speeds it up (skip see-through rows, both cores).

**Rotation** is left aside for now (owner, 2026-10-29). The panel is portrait (320×480). Standing in landscape as delivered, the panel's top edge is on the left: landscape x = panel y, landscape y = 319 − panel x. Touch reports panel coordinates, the same as the image.

## 4. Pages and widgets

**Preset out of the box** (all editable):
1. **Total**: stash value in divines, div/h in green, sparkline, "synced X min ago", clock.
2. **Top**: the 8 most valuable items (several of the same item count as one row), plus per-tab totals.
3. **Session**: gain since the session started, and the divine price in chaos.
4. **Maps** (added in step 9, §5c): the current map with its live timer, maps this session, per hour, average map time and div per map.

A fourth example page, **League** (since league start, today, best hour, item prices), was dropped on 2026-10-27: "since league start" is about the same number as the stash total, and today and best hour are already on Total and Session. Its widgets and metrics stay available for custom pages.

**Settings page** (served by the .exe on localhost, opened in the browser):
- Add, remove, reorder, hide or duplicate any page, built-in ones included.
- Edit a page's widgets with a **live preview that is exactly what the screen shows**.
- Set each page's background: upload an image, GIF or video. The PC resizes, crops and converts it.
- Configure poe.ninja items, intervals and the cookie in one place, with no hand-edited files.

**Widgets for v1:**
- Stash total, div/h, sparkline, session gain, most valuable items, tab totals, divine price (the built-in pages are made from these).
- **Value since league start**: current value minus the first value recorded in the league.
- **poe.ninja item price**: one or more items, batched into one request per poe.ninja category, at most every 30 min.
- **Stack or tab value** from WealthyExile: a specific stack or stash tab.
- **Session/day stats**: gain today, best hour, and so on, from local history.
- Text and clock (for layout).
- **Notes** (added 2026-10-27): the friend's own text over several lines. Line breaks are kept, a line starting with "- " becomes a bullet, and placeholders are filled in. The text auto-fits the card by default, or uses a fixed size, and is cut with "…" when it cannot fit. A full-page note uses the "Single slot" template, below the page's top bar.
- **Now playing** (added 2026-10-27): what the PC plays, with previous, play/pause and next buttons, each a single tap on the screen.
  - Source: Windows' own media session (the one behind the volume flyout), which Spotify, browsers, VLC and most players publish to. Commands go through the same API, never as simulated key presses. No account or online service.
  - Shows the cover art, title, and artist (or the player's name). Not the playback position: a progress bar would mean re-sending the card every second, and the real screen's speed is not known yet.
  - The PC polls the session about once a second and re-sends the page when the track, the cover, or play/pause changes, and only if a visible page has the card.
  - Buttons sit under the title, beside the cover, when each gets at least 50 px (about 8 mm); in narrower cards they take a row across the whole card.
  - Outside Windows (the Mac, while developing) and with `--fake-media`, a pretend player stands in.
  - The screen side is a new kind of touch zone, `"gesture": "tap"` (see `docs/PROTOCOL.md`).

**Session** resets when the script starts and on a long press. It does not reset daily.

## 4b. Visual style (PoE look)

Decided 2026-10-27. This is a private tool that is never distributed, so it uses the game's own art. That art is never committed to the repo.

- **Real item icons**, from GGG's image server (`web.poecdn.com`), using the links in poe.ninja's economy data. The full-size originals (`/image/Art/...`) are used when available. Divination cards share the game's card inventory icon.
- **Fontin** (the game's font) for titles, labels, item names and numbers. It is downloaded from the designer's site (exljbris.com), whose licence allows free use but forbids redistribution. Fontin has no "×", so quantities are written "x148".
- **Tooltip-style frames redrawn in code**: gradient header bar, gold-brown borders, diamond ornaments. Each slot can use `tooltip` (header with the title), `plain` (frame only) or `none`.
- Icons and fonts are **downloaded on first run and cached** in `%APPDATA%\stashdisplay\cache`. The icon index is refreshed at most once a week (~26 poe.ninja requests). Without the cache (offline, or download failed), the renderer falls back to bundled fonts and a drawn divine orb.
- **The game's colour codes** (owner, 2026-11-04; this replaces "not used: in-game text colours by item type"). Everything is in `pc/stashdisplay/render/theme.py`:
  - **Item names** (Most valuable, Item prices) use the game's colour for the item's poe.ninja list: currency and the other exchange items beige `#AA9E82`, divination cards `#0EBAFF`, gems `#1BA29B`, uniques `#AF6025`, maps `#C8C8C8`. Unknown items stay white.
  - **Map tiers** are white for T1–5, yellow for T6–10 and red for T11 and up. An area level below the maps' levels stays gold.
  - **The current-map card is the map's tooltip** (concept B of three, owner, 2026-11-04). In a tooltip frame:
    - The header bar shows the map's name in its tier colour.
    - Under it, a property line on one row: "Map Tier: 16", "Portals: 2" and "Deaths: 0", with names in the game's property grey `#7F7F7F`.
    - Separator lines in the tier colour, fading at both ends, split the sections.
    - The timer is centred, with "Paused" or "Outside the map" under it.
    - At the bottom, the mechanics are coloured lines centred like a map's mods. Each gets its own line when there is room. Otherwise several share a line, then "+3" for the rest. The timer keeps at least 52 px.
    - In a plain frame or none, the name heads the card instead.
    - The Most valuable list gets the tooltip's fading separator between its rows. Its frame stays gold, since the list mixes item types.
    - Concepts A (coloured data in the gold frames) and C (the card glowing in the main mechanic's colour) were not taken.
  - **Mechanic colours:** Bestiary is rust orange, Delirium grey, Delve azurite cyan, Incursion blue, Betrayal (Syndicate) green, Blight yellow, Harvest teal, Ultimatum red, Maven magenta and Expedition brass. Among the side areas, Abyss is olive, a Vaal area is corrupted red `#D20000`, a Trial is gold and Starfall is orange. The owner picked Betrayal green, Blight yellow, Delirium grey and Incursion blue.
  - **Deaths** are red once there is one, and **portals** are in the portal's blue.

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
- Intervals, poe.ninja items, and Start with Windows.

**Backgrounds in this step**
- Upload, crop and convert images, GIFs and videos. The preview shows a still frame. The animated preview comes with the firmware media step, once the real frame rate is known. The browser extracts a video's still frame, so the settings page itself needs no ffmpeg; ffmpeg only comes in with the MJPEG conversion.

**Tech**
- **Flask** served by **Waitress** (stable, pure Python, works well on Windows), plus **Alpine.js** bundled as a file (no CDN, no build step).
- **Render speed:** 55–80 ms per page today (M-series Mac). The target is under 20 ms by cropping drawing work to each element's area instead of the full screen.

## 5. Backgrounds and media

- Formats: **still image, GIF, video**. A video becomes an MJPEG file of our own (`mjpeg`, docs/PROTOCOL.md), decided 2026-10-29:
  - **No ffmpeg.** The settings page's browser decodes the video (as it already does for its still frame), steps through it at **12 fps** and sends the frames to the PC app, which fits each one to the screen (cover or contain, like images) at **JPEG quality 70**, about 20 kB a frame.
  - **At most 10 s**, looped: about 2.4 MB each. A longer video is cut.
  - The screen **reads each frame from flash** as it plays (a video does not fit in the free PSRAM), on the page shown only, like GIF backgrounds.
  - Videos uploaded before this keep showing their first frame until uploaded again.
- **Every GIF sent to the screen is re-encoded by `pc/stashdisplay/link/gif.py`** (decided 2026-10-28): one 255-colour palette for the whole GIF, no dithering, and pixels that did not change since the previous frame stored as transparent. That is lossless after the palette step and keeps a mostly still animation about 5× smaller than storing every frame in full (the level-up GIF: 3.5 MB → 0.7 MB). It applies to backgrounds, event animations and the start animation alike. Phone-camera noise is not frozen here (that would be lossy); `pc/tools/anim_from_video.py` does it for the built-in animations.
- Stored in the screen's flash (a ~10–12 MB filesystem partition, out of 16 MB). The settings page shows how much space is used and refuses uploads that don't fit. That's roughly 20–40 s of 480×320 video in total.

## 5b. Game events (game start, level-up, death)

- PoE1 has no combat log. The game writes a chat and events log, `Client.txt`, in its `logs` folder. The PC **tails** that file read-only, starting from the end, because it can be several GB. This is the same passive approach as many community tools, and it does not touch the game (no memory reading, no input, no overlay).
- Built as a **general "log event → animation" system** configured in the settings page. **v1 events:**
  - **Level-up**, from lines like `: CharName (Class) is now level 92`
  - **Death**, from lines like `: CharName has been slain.`
  - **Game start** (added 2026-10-28), from the line the game writes each time it starts: `2026/08/19 22:07:49 ***** LOG FILE OPENING *****`. Checked against the owner's log: 84 starts, each one such line. It plays the start animation (the spinning cat, §3) by default, for 4 s, and has its own switch and media in settings. If the game is already running when the app starts, nothing plays.
- Only system lines count (`] : ` right after the log prefix), so typing those words in chat triggers nothing. The game-start line has no prefix at all, and a chat line always has one, so it cannot be typed either.
- **Own characters only.** A name in a level-up line is taken as one of the friend's characters, unless that name was ever seen joining or leaving the area (only other players do that). The settings page lists the learned characters with a tick box each. Known gaps: a party member who levels up before ever sharing an area is learned by mistake (untick it), and a new character that dies before its first level-up is not known yet.
- **Last portal** (added 2026-11-04): the map tracker's own event, §5c.
- **Every level-up plays**; there is no level threshold. Each event can be turned on or off.
- **Over the page** (decided 2026-10-28): a GIF with see-through pixels (built-in or the friend's) plays over the current page, which stays underneath dimmed to 40 %. It is fitted inside the screen, on its bottom edge, with its visible part centred left to right (bottom-right corner until 2026-10-29, moved to the centre after seeing it on the screen). GIF pixels are fully opaque or fully see-through, nothing in between. The built-in death GIF is the owner's cat screaming, cut out from its background, about 180×320 on the right of the screen. A GIF with no see-through pixels, an image or a video plays full screen as before.
- **Full-screen animation** otherwise, then back to the current page. The built-in animations are GIFs made for this project (`pc/stashdisplay/assets/anims/`), shown as they are, with no text on top. A GIF plays once, except for level-up, whose GIF (built-in or the friend's) plays twice (decided 2026-10-28); anything shorter than 3 s loops until 3 s, and anything past 10 s is cut. The built-in level-up GIF is the owner's cat pawing at its food tray, made with `pc/tools/anim_from_video.py` (the steps are in `pc/stashdisplay/assets/anims/README.md`). The friend can replace each one with their own GIF, image or video in the settings page.
- **The built-in animations and the idle cat are a surprise** (decided 2026-11-04): nothing the friend reads hints at what they show. The settings page calls them "Default" ("Par défaut") and the idle screen "an animation", the install guides say the same, and Test is greyed out while an event is on its default, so it only plays the friend's own files. The exe packs the animation files without their README. The file names (`death.gif`, `idle.png`...) stay, as they only repeat the event names. Any new built-in animation follows the same rule.
- **Until a GIF exists** (or if it does not fit on the screen), the PC sends a text card instead: "Level 92" or "Slain", with the character name, or "Path of Exile" for a game start, for 4 s.
- **Bursts:** the newest event replaces the one playing, except that a level-up never cuts a death short.
- Animations are stored on the screen in advance, so the PC only sends a small "play" message and playback starts within about a second. Events that happen while the screen is unplugged are dropped, not queued.
- The `Client.txt` path is auto-detected (the standalone install, Steam and its other library folders; the most recently written one wins) and can be changed in settings. The file is read from its end at start-up, opened only for each read (so it can still be deleted), and read from the start again when it is emptied or replaced.
- Animations share the flash budget in §5 with the backgrounds and the start animation.

## 5c. Map tracker (decided 2026-10-29, step 9)

Idea from Exile UI (Lailloken/Exile-UI, MIT, an AutoHotkey overlay): its map tracker reads `Client.txt` only. We **copy the idea in our own code** and do not bundle or update Exile UI: it draws over the game and sends key presses, which §1's hard rules forbid for this app. The friend keeps using Exile UI for levelling; this screen is for mapping.

- **Log lines.** Each area change writes `<date> <time> … Generating level 83 area "MapWorldsCitySquare" with seed 1234567` (then `: You have entered City Square.`, which gives the display name). In the owner's log (Aug 2026): 4,454 area lines, 1,110 map entries, 515 distinct map seeds, 252 of them entered again through a portal.
- **What counts as a map:** Exile UI's list: atlas maps (`MapWorlds*`), Maven, Atlas encounters (`MapAtlasEncounter_*`), uber bosses and league-mechanic areas. **Side areas** (Abyss boss, Vaal side area `mapsidearea`, lab trials, Starfall crater) count as part of the map they were entered from. A **new map** starts when a map area is entered with another area id or another seed; the same seed again is the same map plus one portal. Hideouts, towns and campaign areas are not maps (campaign is ignored: the friend levels with Exile UI).
- **Tier:** area level − 67 (83 → T16); below 68, the level is shown.
- **Map time:** only time spent inside the map and its side areas; hideout time does not count. It **pauses after 10 s with no keyboard or mouse input** on the PC (owner's choice; Windows idle time, `pc/stashdisplay/idle.py`, as for the idle cat).
- **Per map:** mechanics seen (from NPC lines: Einhar, Niko, Alva, Strange Voice for Delirium, Jun and the Syndicate, Sister Cassia, Oshabi, the Trialmaster, the Maven…), deaths and portals.
- **What the screen shows:** a ready-made **"Maps"** page, and the values as widgets/metrics usable on any page: maps this session and today, maps per hour, average map time, **div per map** (session gain ÷ maps this session; one map's own earnings can't be known from 5-minute stash values), and a **current map** widget (name, tier, live timer, mechanic tags, deaths, portals).
- **Session:** the same session as div/h: holding the session value resets the map count too. "Today" starts at local midnight, like the other stats.
- **History:** a local `maps.json` in the app folder, enough for the session and day numbers. No list in the settings page for now.
- **WealthyExile sync after a map (on by default, a setting):** back in the hideout after a map, the app syncs WealthyExile, **at most once every 5 minutes**, then reads it 30 s later as for a tap. This changes the earlier "only on a tap" rule (§6), so div per map stays current without tapping.
- **Last portal (decided 2026-11-04):** going back into a regular atlas map (`MapWorlds*`) for the fifth time, which leaves one of the device's six portals, plays the "run" animation: a short film clip the owner picked (`images/run-bitch-run.gif`), as a game event of its own (`lastportal`, §5b) with its switch and media in settings, on by default. Only atlas maps, since Maven, uber and Atlas encounter areas can open fewer portals; only the friend's own ways in count, as for the portal number (a party member's are not in the log). It plays full screen, cropped to fill (cover), twice: 5 s. Like a level-up, it never cuts a death short. The clip is committed as a built-in animation (the repo is private), reduced to 64 colours so it takes 1.8 MB on the screen instead of 2.9 MB (live footage changes every pixel, so `gif.encode()` saves little on it).
- **Later, a separate step:** encounter alerts (Nameless Seer, Reflecting Mist, Infamous mercenaries) as toasts or animations, tagged on the map they happened in.

**Built 2026-10-30** (`pc/stashdisplay/maps.py`, tests in `pc/tests/test_maps.py`). What was settled while building, beyond the decisions above:
- **Checked against the owner's log:** the tracker finds exactly the 515 `MapWorlds*` maps (one per seed), 588 maps with the rest of the list (Maven, Atlas encounters, Legion, Sirus, Atziri, ...). The "252 entered again" counted every second area line of a seed; 317 of those are the same map written again with nothing in between (a death and checkpoint, a reconnect), which costs no portal. Through a portal, 160 maps were entered more than once. 283 deaths and 12 kinds of mechanic tags were found.
- **Map list:** Exile UI's prefixes (any case), except the Rogue Harbour (`HeistHub`) and the Sanctum's entrance, which are towns. Not maps: Kingsmarch (`KalguuranSettlersLeague`), the lab, Delve, and this league's own `Deepwater*` areas (143 + 56 lines in the owner's log), which Exile UI's list does not have either. Atlas encounters (`MapAtlasEncounter_*`) are entered from the hideout, so they are maps of their own.
- **Portals:** the first entry is portal 1; each entry from outside the map and its side areas (the hideout, a town) adds one. A side area entered with no map yet counts as a map of its own.
- **Mechanics:** NPC lines have the speaker right after the bracket (`[INFO Client 1234] Einhar, Beastmaster: ...`), with no `: `. They are matched by exact speaker name; a chat line starts with a channel sign or a player name, and player names have no spaces or commas, so only one-word speakers (Oshabi, Rog) could be faked, by a player of that exact name talking in local chat. Tags: Bestiary, Delve, Incursion, Delirium, Betrayal (Jun and the 17 Syndicate members), Blight, Harvest, Ultimatum, Maven, Expedition (Dannig, Gwennen, Rog, Tujen), plus the side areas: Abyss, Vaal area, Trial, Starfall. Deaths: "has been slain" or "has committed suicide" of an own character (§5b), in the map or its side areas.
- **Timer:** ticked once a second (a gap over 5 s, the PC asleep, is not counted). Outside Windows the idle time is unknown and the timer never pauses. On the screen it is "7:05" (or "1:02:09"), with "Paused" or "Outside the map" beside it. **Live:** while it runs and the page shown has the current-map card, the PC re-renders that page alone each second and sends its overlay without a whole sync (about 40 ms on USB; `docs/PROTOCOL.md`). After an app restart the tracker does not know where the friend is until the next area line, so the timer waits for it.
- **Numbers:** maps per hour = maps this session ÷ time since the session's first map started, shown once that is 15 min; average map time = the session's maps, without the one being run; div per map = session gain ÷ maps this session. A map counts in the session and the day it started in. Holding "maps this session" resets the session, like the session gain.
- **Demo data:** until the first real map, previews and the screen show made-up maps (with demo stash data); real maps show as soon as there is one, even before WealthyExile is read.
- **maps.json** keeps 14 days of maps, like the stash history; saved at each change and every minute while the timer runs.
- **Maps page:** a new "Wide + four tiles" template (`wide4`): the current-map card on top, then maps this session (with today's under it), per hour, average and div per map. It is **last in the preset**, so a fresh install (or "Reset" in the page list) gets it. **An existing install gets it added once** (owner, 2026-10-30): `settings.json` is now version 2, and loading a version-1 file appends the Maps page, unless a page already has the id `maps` or a current-map widget. A Maps page deleted afterwards stays deleted. The settings page offers templates, not ready-made pages, so there was no other list to add it to.
- **Sync after a map:** when the friend leaves a map for any non-map area. A sync less than 5 min after the last one, a tap's included, waits until the 5 min are up; a tap's sync also covers a map that just ended. No toast (the tap's "Syncing WealthyExile..." is there because a tap needs an answer). Setting: `maps.sync_after_map`, in a "Map tracker" panel of the settings page.
- **Simulator:** buttons to open a new map, go into a side area, make an NPC speak, go back to the hideout and back in by a portal.

## 6. Data sources

- **WealthyExile** (core): stash value, items and tabs. No documented API, so we reverse-engineer the site's own JSON requests. All of that lives in one adapter module, with a `--dump` mode for raw responses.
  - How (decided 2026-10-29, step 7): the site's requests are read from the owner's own logged-in Chrome tab through the Claude in Chrome extension, which hides cookie values; nothing logs in for the owner and nothing works around a Cloudflare check. Raw responses stay in `pc/dumps/` (ignored by git); tests use small made-up copies.
  - The adapter uses `requests` with the pasted Cookie header and a descriptive User-Agent, every 5 min. An expired cookie shows "Cookie expired" on the screen and the tray and stops fetching until a new one is pasted; a Cloudflare check or an unexpected page shows "WealthyExile unavailable" and waits for the next turn. **Built 2026-11-04** (it had been missed: until then the screen only said "stale" after 15 min): the error replaces "synced X ago" in the top bar as soon as a read fails, and the tray's first line (and its hover text) adds it. A turned-down cookie is remembered as a hash, in memory only; nothing goes to WealthyExile with it again, a tap's sync and the sync after a map included, and a tap does nothing. A new cookie is read on the next turn. The settings page's forced demo preview shows no error.
  - Freshness (decided 2026-10-29): a free account updates only when synced, so **a tap on the screen syncs WealthyExile**, at most once a minute, then the app reads the new values 30 s later (a sync takes about 25 s). Between taps the app reads every 5 min. Since step 9 it also syncs on its own after a map, at most every 5 min (§5c). Found 2026-10-29: the site's **Sync stash** button calls the Next.js server action `syncUser` (not `syncTabs`) with `[price threshold per stack, newest snapshot's createdAt, user.lastHourlySync]`, POSTed to `/stash` with the action's id (read from the site's scripts, it changes with each deployment) and the `x-deployment-id` header. Checked from the app's own code: the sync landed 24 s later.
  - **Tokens:** WealthyExile's replies can carry the session itself (a server action's reply echoed the session cookie's value, with the account name and its GGG access token inside; seen 2026-10-29, the owner revoked and logged in again). Nothing from WealthyExile is ever logged, and `dump` scrubs every token-like value before writing.
  - When the page cannot be read as expected, the screen shows "WealthyExile changed" with the last good value, and `stashdisplay dump` saves what came back, scrubbed, into `pc/dumps/`.
- **poe-pricer** (MDero/poe-pricer, the friends' pricer, decided 2026-10-29): when it runs (found through its `/api/ping`), the settings page can pick it as the stash source instead of WealthyExile, and it is the first source for the divine price. Its address is a setting (default 127.0.0.1:5175, where the friend runs it).
  - What its total counts (owner, 2026-10-29): only the bulk items (`/api/wealth/families`: Currency, Scarab, DivinationCard...) and the tabs of uniques; rares and gear are left out, too hard to price. PoE Pricer gives no tab types, so unique tabs are found by name: those holding a word from the `poepricer.unique_tabs` setting ("unique" by default). On the owner's home server: about 43.8 divines (WealthyExile shows 38.6, as it drops stacks under 10 chaos).
- **Divine price**: PoE Pricer's when it runs (the WealthyExile totals are then rescaled to it), else WealthyExile's own (`priceMap`, per league).
- **League** (decided 2026-10-27): there is no league setting. The friend plays the current softcore trade league. Until WealthyExile is read (step 7), poe.ninja prices use the first league in poe.ninja's list, which is the current softcore trade one. After that, prices follow the league WealthyExile reports, so the two can never disagree, including in the first hours of a new league.
- **poe.ninja**: official economy endpoints, used for the item-price widget and the divine price fallback. It sends a descriptive User-Agent, respects the cache and ETags, and polls at most every 30 min. Note: poe.ninja's docs ask desktop apps to proxy through their own backend. We accept that small deviation at this request rate.
- **History**: a local file in `%APPDATA%\stashdisplay`, which survives restarts. It feeds div/h, the sparkline, session, league-start and day stats.
- **XP/hour** (wanted, not scheduled yet): `Client.txt` only logs level-ups, not experience. GGG's official API returns each character's `experience` (`GET /character`, scope `account:characters`), and desktop apps may use it as a "public client" (OAuth with PKCE and a local redirect). This needs the app registered with GGG, and the friend logging in to his PoE account once to approve it. Not in v1: set aside until after the hand-over (2026-11-04).

## 7. Delivery

- **Private GitHub repo** (`krully37/poebrotracker`).
- **PC**: a single Windows `.exe` built by GitHub Actions (PyInstaller, no console window). It includes an auto-start toggle (a registry Run key) and a log file. Your friend needs no Python.
- **Firmware**: built with PlatformIO. CI checks that it compiles. Flashed by you from the Mac.
- Developed on macOS. The PC code runs on both macOS and Windows so it can be tested on the Mac, and Windows-only parts (auto-start, .exe, COM port behaviour) get a final test on a Windows PC.
- **Demo for filming** (decided 2026-10-30): `stashdisplay demo [--simulator]` plays a ~33 s show on the real screen, or on the simulator to rehearse: the start animation, a level-up, a new map with its timer, Einhar, a death, back to the hideout with the sync toast and 6 divines of loot, then the idle cat until the screen is touched. Enter starts it once the screen is ready, and plays it again after. It runs on demo data in `<app folder>\demo`, emptied at each start, with 16 made-up maps already run; the real settings, history and maps are never touched. The stash value climbs every 3 s (demo points without price noise). Pages are swiped by hand while filming: there are no on-screen cues, and the PC cannot change the page. The game events go through a fake `Client.txt`, the real path from the log to the screen. The map timer and the idle cat ignore the PC's own idle time during the demo. The timeline is one list at the top of `pc/stashdisplay/demo.py`.

## 8. Proposed technical choices [PROPOSED]

| Part | Choice | Why |
|---|---|---|
| PC language | Python 3.12+ | The brief's recommendation, with a good ecosystem for images (Pillow) and serial (pyserial) |
| Page rendering | Pillow; PoE look (§4b); bundled open-licence fonts as fallback | The same code produces the preview and the screen image |
| Settings page | Flask + Waitress, Alpine.js bundled, no build step (see §4c) | Stable, nothing to install, and it opens in any browser |
| Overlay transfer | RGB565 + 4-bit alpha, zlib-compressed, sent in chunks over USB serial | The ESP32 ROM has zlib inflate built in. Mostly-transparent overlays compress very well |
| Firmware | Arduino core 3.x + Arduino_GFX (panel init only), own DMA pixel push, own compositor, own USB serial driver, JPEGDEC / AnimatedGIF (bitbank2) for media | No LVGL: it wouldn't be faster here, and the PC now does the layout. Arduino_GFX's own push is 28 fps against 61, and Arduino's USB Serial loses bytes (§9) |
| Filesystem on screen | LittleFS | Standard on ESP32, survives power loss |

## 8b. Firmware design (step 6)

Decided 2026-10-29.

- **Landscape:** the screen stands in landscape, and the protocol stays 480×320 landscape. The firmware turns the image while compositing (panel x = 319 − landscape y, panel y = landscape x). Each 16-row panel strip reads 32-byte runs of the landscape image, one cache line each, so turning costs about nothing. Touch is mapped back the same way.
- **Order**, one commit each:
  - **6a:** the USB link (frames, ACKs, inventory, transfers to PSRAM and flash), offline screen and dimming. **Done 2026-10-29:** the real PC app syncs with the screen (HELLO answered in 26 ms, the three animations stored in flash with their CRC checked), the current page shows in landscape, and "Waiting for the PC" / "PC disconnected" show dimmed. The flash has 13.5 MB for files.
  - **6b:** pages: compositor, swipe slide, dots, tap, long-press banner, toast. **Done 2026-10-29.** Each page is composited once into the panel's own order when it changes (bg + overlay, ~35 ms), so a slide only copies rows: **45 fps** (13 frames in 0.29 s), limited by the panel bus. The touch controller sometimes reports no finger while one is down, so only 60 ms without one counts as lifting it. The dots and the "4/9" counter are baked into the firmware from the PC renderer (`pc/tools/firmware_assets.py`).
  - **6c:** animations (events over the page and full screen, boot animation), the idle cat and GIF backgrounds. Decided 2026-10-29, in three commits (6c-1 events and boot, 6c-2 idle cat, 6c-3 GIF backgrounds):
    - The event animations and `boot` are kept loaded in PSRAM after each sync (about 2 MB), so a level-up starts at once.
    - A GIF background animates only on the page shown, at the GIF's speed up to about 15 fps (what compositing allows); during a slide it holds still.
    - A frame that is late shows as soon as it is ready: an animation may play a little slower, never skipping.
    - The idle cat moves at 30 fps, turned with bilinear filtering.
    - **6c-1 done 2026-10-29:** level-up (full screen, twice), death (over the dimmed page) and the boot cat (at power-on, from flash) checked on the screen. The death cat is now centred.
    - **6c-2 done 2026-10-29:** the idle cat bounces and turns on the screen, and a touch brings the pages back (EVENT wake). The turns are not perfectly smooth yet (whole degrees, the sprite turned again for each one); good enough for now (owner).
    - **6c-3 done 2026-10-29:** a GIF page background plays smoothly behind the overlay on the page shown, holds still on its current frame during a slide or an animation over the page, and the long-press banner shows over it. Pages beside it use its first frame. A background GIF is read from flash as it plays, never loaded whole into PSRAM (since 2026-10-29: loading it failed when PSRAM was short); so are event animations not preloaded yet. With everything loaded (three animations, a GIF background) 1.7 MB of PSRAM is left; HELLO's answer carries `psram_free` for that.
  - **6d:** video backgrounds (§5). **Done 2026-10-29:** a phone video uploaded in the settings page plays on the screen behind the page and holds still during slides. Per frame: 3 ms to read it from flash (about 6.7 MB/s), 37 ms to decode it.
  - The framing is also unit-tested on the PC (`pio test -e native`).
- **Flash:** one 3 MB app partition, no over-the-air updates (the owner flashes by USB); LittleFS gets the rest, about 12.9 MB.
- **Two cores:** core 0 runs the USB link (read, ACK, write to flash); core 1 runs the display (touch, compositing, animations). Overlays stay compressed in PSRAM; the current page and its two neighbours are kept unpacked (~1.2 MB), so a swipe starts at once.
- **Closing the COM port resets the board** (§9). Fixed on the PC side (2026-10-29): `transport.py` drops RTS, then DTR, before closing, and the screen keeps running. Only an app that is killed (or crashes) still resets it, because Windows then closes the port the plain way; the screen then plays the boot animation and waits for the PC.

## 9. Open questions

- **Map tracker choices, answered 2026-10-30** (§5c):
  1. Existing installs get the Maps page added on their own: **yes**, once (§5c, "Maps page").
  2. The map timer updates **every second**, unless that is a problem on the real screen.
  3. The league's own `Deepwater*` areas are **not maps** (owner: "whatever", so the recommendation stands, matching Exile UI's list).
- **Waiting on the owner (2026-10-30):**
  - Still to try on the real screen during real mapping (the owner will, when he can): the live timer, and the WealthyExile sync after a map against the live site.
  - **iPhone as the screen (idea, 2026-10-30; set aside by the owner: build for the friend first):** an old iPhone shows the pages over Wi-Fi instead of the ESP32 screen. The plan is a web page that reuses the simulator's compositing and touch, served by a second, display-only server on the local network, with its own token in a QR-code link. The settings server stays on 127.0.0.1. Opened with "Add to Home Screen", Auto-Lock off and Guided Access. Waiting on two answers: the iPhone model and iOS version (old Safari may need extra work), and whether a LAN display server is acceptable given the 127.0.0.1 rule. About a day of work, with no firmware change.

- WealthyExile, **found 2026-10-29** (owner's account, from his Chrome tab):
  - No JSON API. The stash page's HTML (`GET https://wealthyexile.com/`, Next.js) embeds everything in its `self.__next_f` payload: `user.preferredLeague`, `user.lastSynced`, per-tab `tabValues` (hourly, chaos), `items` (name, quantity, tab, chaos price, icon, category) and `priceMap` (Divine Orb price per league). It also embeds an `accessToken`: never logged, dumped or kept.
  - A free account's data changes only when it is synced: loading the page does not sync (last sync 16:26 UTC, still so at 18:04 after several loads). The hourly sync is premium-only. The site's **Sync stash** button calls the `syncUser` server action (not `syncTabs`, as first thought); a tap on the screen calls it too (§6).
- MDero/poe-pricer (the friends' pricer; private repo): a local app on `127.0.0.1:5175`, no login on its API. `GET /api/ping` → `{"app": "poe-pricer"}` (to detect it), `/api/wealth?league=` (value per tab over time), `/api/rates?league=` → `{"divineToChaos"}`, `/api/tabs`, `/api/items?league=&tabId=` (also lists items gone from the stash, which the app skips), `/api/wealth/families` (value per item family). Checked 2026-10-29 on the owner's home server; it is a stash source since step 7 (§6).
- `Client.txt` line formats: **checked on 2026-10-27 against a real English-client log** (the owner's, Steam install, March to August 2026, 166k lines). All 333 level-up lines and every "has been slain." system line match; chat lines with "died" or "slain" are ignored. Party members' level-ups and deaths **do** appear there; all of the ~20 other players in that log were also seen joining or leaving the area, so none was learned as an own character (zero false animations). Non-Latin names (Chinese, Korean, Cyrillic) parse fine. The friend's client is in English too (confirmed 2026-10-27), so no other language is needed.
- Windows checks on 2026-10-27 (no screen): tests pass on Python 3.13; `Client.txt` was found through Steam's registry key and `libraryfolders.vdf` on another drive; the simulator and the fake log events work; the DPAPI vault round-trips. Real USB was checked with the screen on 2026-10-29 (steps 5–8), the built `.exe` included.
- Hardware: **checked 2026-10-29** with the bench firmware (`firmware/README.md`). ESP32-S3 rev 0.2, 16 MB flash, 8 MB PSRAM. The pins in `firmware/lib/board/board.h` work: panel, backlight, and touch at I2C 0x3B, which covers the whole panel (corners read 12–310 × 14–461). Colours are right (no red/blue swap). The factory firmware is backed up outside the repo (`H:\dev\bropoetracker-factory-backup\`, owner's Windows PC; restore with `esptool write-flash 0 <file>`).
- Speeds, **measured 2026-10-29** at 240 MHz, built with `-O2` (this platform passes no `-O` flag by default, which made everything 2–4× slower):

  | | |
  |---|---|
  | Full frame, Arduino_GFX's own push | 28 fps |
  | Full frame, our DMA strips at **40 MHz** | **61 fps** (the bus alone: 62) |
  | Same at 80 MHz | 117 fps, but the image is corrupt (dotted text and lines), so the panel stays at 40 MHz. 60 MHz rounds down to 40 |
  | Overlay over a background (composite only) | 35 ms, so 27 fps with the push |
  | Overlay unpack (ROM zlib, 23 kB → 384 kB) | 28 ms |
  | JPEG 480×320 decode (JPEGDEC, S3 SIMD) | 49 ms, about 20 fps of video |
  | GIF decode, level-up animation | 20 ms a frame (it wants 66) |
  | USB from the PC, raw / one ACK every 4 kB | 611 / 604 kB/s, nothing lost. A page overlay takes ~40 ms, the level-up GIF ~1.1 s |
- USB serial: Arduino's `Serial` (HWCDC) pushes each received byte through a FreeRTOS queue from its interrupt and **drops bytes** when the queue is full (143 kB of 200 kB arrived). The firmware uses its own driver (`firmware/lib/board/usblink.h`), reading the USB FIFO directly, so the PC simply waits when the screen is busy.
- **Closing the COM port resets the board** (the USB-Serial/JTAG reset lines), and so does opening it with DTR/RTS off; opening it with pyserial's defaults does not. Fixed in step 6: the app drops RTS, then DTR, before closing, so Quit or a reconnect leaves the screen running (§8b).
- USB on the board: **settled 2026-10-29, native USB.** The USB-C port goes straight to the ESP32-S3's USB-Serial/JTAG (`VID_303A&PID_1001`, no CH340). Windows 11 loads its built-in USB serial driver on its own (COM port plus a "USB JTAG/serial debug unit"), so the friend installs no driver. Transfer speed: see the speeds below.
- XP/hour (after the hand-over, §6): register an app with GGG's developer program, and whether that registration is approved.

## 10. Build order

1. Repo, CI skeleton, this scope.
2. PC: history, stats and the page renderer in **demo mode**, producing PNG previews on the Mac (no hardware needed).
3. Settings page with live preview and page editor.
4. Serial protocol (overlay transfer, file transfer to the screen's flash, touch events, heartbeat), tested against a simulated screen on the PC. The simulator is also a page in the settings app: the screen exactly as the firmware will composite it, driven with the mouse. The protocol is specified in `docs/PROTOCOL.md`.
4b. `Client.txt` event watcher (level-up, death), tested against sample log lines, then a real log.
5. **Hardware arrives**: validate pinout, rotation, touch, then measure frame rates. **Done 2026-10-29** (§9).
6. Firmware: compositor, slides, offline screen, dimming, then GIF and video backgrounds, and the boot animation.
7. WealthyExile reverse-engineering, then the adapter. Done with the owner's own WealthyExile account (decided 2026-10-29), not the friend's: the site works the same for every account, and the friend only pastes his own cookie at the end. **Done 2026-10-29:** the screen shows the real stash from WealthyExile (read every 5 min, counted like the site with the account's stack threshold), a tap syncs it with a "Syncing WealthyExile..." toast, PoE Pricer can be the source instead (bulk items and tabs of uniques) and gives the divine price, and the item-price card has poe.ninja prices. All checked on the owner's account, home server and screen.
8. Windows .exe, auto-start, install guide; final test on a Windows PC. **Done 2026-10-29:** `pc/packaging/build.py` makes one windowed `StashDisplay.exe` (PyInstaller, 24 MB, the tray icon as its icon; double-clicking it runs the app). It was tested on the owner's Windows PC: it found the screen and read WealthyExile. GitHub Actions (`.github/workflows/build.yml`) runs the PC tests, builds the .exe as an artifact (and attaches it to a release for a `v*` tag), and checks the firmware compiles and passes its tests. The friend's guide is `docs/INSTALL.md` (French: `docs/INSTALL.fr.md`). The .exe is not signed, so Windows SmartScreen warns once (the guide says what to click).
9. Map tracker from `Client.txt` (§5c): maps, map time, div per map, the Maps page and widgets, and the WealthyExile sync after a map. Decided 2026-10-29. **Done 2026-10-30:** checked against the owner's real log and in the simulator; not yet on the real screen during real mapping.
