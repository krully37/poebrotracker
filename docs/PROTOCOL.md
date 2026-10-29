# PC ↔ screen protocol (version 1)

The PC app and the screen talk over USB serial (921600 baud for bridge chips; native USB ignores it). The PC does all the rendering. The screen stores what it is sent, composites it, handles touch, and reports gestures back.

The reference implementations are in `pc/stashdisplay/link/`:
- `protocol.py`: framing, message types, overlay format, timing constants
- `client.py`: the PC side
- `simulator.py`: the screen side, which the firmware mirrors

If this document and the code disagree, the tests in `pc/tests/test_link.py` decide.

## Frames

```
COBS( type:u8 | seq:u16 LE | payload | crc32:u32 LE ) 0x00
```

- **COBS** encoding means 0x00 only appears as the frame end. A reader that loses sync drops bytes until the next 0x00. Boot logs and other garbage on the line cost one dropped frame, nothing more.
- **CRC-32** (zlib/IEEE) covers type, seq and payload. A frame with a bad CRC is dropped silently, and the sender's timeout resends it.
- **Payloads** are compact JSON objects, except `CHUNK`, which is binary.
- **Limits:** at most 4096 data bytes per chunk. A frame over about 4.2 kB is treated as garbage.

## Reliability

- **Requests and ACKs:** every PC → screen frame is a request, and the screen answers each one with `ACK`, carrying the same seq. The PC sends one request at a time. It waits up to **1 s** for the ACK, resends the identical frame up to **4** times, then drops the connection and starts looking for the screen again.
- **Duplicates:** if the screen receives the same type and seq as the request it just answered, it re-sends its previous ACK without applying the request again (its first ACK was lost).
- **Events:** the screen sends `EVENT` frames with its own seq counter. The PC answers each with `EVENT_ACK` (same seq, empty payload). The screen resends an unanswered event after 1 s, up to 4 times. The PC ignores events whose seq it has seen recently. Events are dropped while the PC is away.

## Messages

| Type | Name | Direction | Payload |
|---|---|---|---|
| 0x01 | HELLO | PC → screen | `{"version": 1, "time": unix}`. The ACK carries the inventory (below). The screen also discards half-finished transfers. |
| 0x02 | PAGES | PC → screen | `{"pages": [{"id", "overlay": crc, "bg": {...}, "zones": [...]}]}`, in display order |
| 0x03 | BEGIN | PC → screen | `{"xfer": u16, "kind": "overlay" \| "file" \| "toast", "id", "size", "crc", "format"?, "seconds"?}` |
| 0x04 | CHUNK | PC → screen | binary: `xfer:u16 LE`, `offset:u32 LE`, then data |
| 0x05 | END | PC → screen | `{"xfer"}`. The screen checks size and CRC, then stores the blob. |
| 0x06 | DELETE | PC → screen | `{"id"}`: delete a file from flash. The ACK carries `flash_free`. |
| 0x07 | PLAY | PC → screen | `{"file": id \| null, "overlay": "@event" \| null, "seconds", "over_page"?: true}`: event animation. The file loops until `seconds` have passed (black if `file` is null), with the overlay on top. Without `over_page` it fills the screen. With `over_page` the current page (background, overlay and dots) stays underneath, dimmed to **40 %**, and shows wherever the GIF's pixels are see-through. A new PLAY replaces the one playing. |
| 0x08 | PING | PC → screen | `{}`: heartbeat |
| 0x09 | EVENT_ACK | PC → screen | empty. The seq is the event's. |
| 0x0A | IDLE | PC → screen | `{"sprite": id \| null}` (added 2026-10-29): the PC is idle, so the screen shows this `sprite` file bouncing on black instead of the pages (see "Idle" below); `null` brings the pages back. An IDLE for the sprite already bouncing carries on from where it is. Refused with `"no_file"` if the file is missing. |
| 0x81 | ACK | screen → PC | `{"ok": true, ...}` or `{"ok": false, "error": "..."}`. The seq is the request's. |
| 0x82 | EVENT | screen → PC | `{"type": "tap" \| "page" \| "reset" \| "wake", "page": id, "action"?}`. A tap carries `action` when it lands in a tap zone. `wake`: the screen was touched while showing the idle cat. |
| 0x83 | LOG | screen → PC | `{"text"}`: debug output, not acknowledged |

**Inventory** (the ACK to HELLO):
```json
{"ok": true, "version": 1, "firmware": "…", "width": 480, "height": 320,
 "flash_total": 11534336, "flash_free": 9000000,
 "overlays": {"<page id>": "<crc>"},
 "files": {"<file id>": {"crc": "…", "size": 123, "format": "jpeg"}},
 "playing": "boot"}
```
`playing` is the file of the full-screen animation on screen right now, or `null` (added 2026-10-28). After the first sync of each connection the PC plays `boot`, unless `playing` is already `"boot"` (the screen just powered on and is showing it). A screen that leaves the field out counts as playing nothing.

The PC compares this with what it wants on the screen and only sends what differs. A reconnect after a cable pull resends nothing. After a power cycle, the overlays (kept in PSRAM) are resent; the files (in flash) are not.

**Page entries in PAGES:**
- `bg` is either `{"color": "#rrggbb"}` or `{"file": "<file id>", "color": "#rrggbb"}`. The colour is the fallback if the file is missing.
- `zones` lists `{"x", "y", "w", "h", "action", "gesture"?}` rectangles the screen reacts to.
  - `"gesture": "hold"` (the default when missing): a long press resets something. `action` is `"reset_session"` or `"reset_rate"`.
  - `"gesture": "tap"`: a tap runs a button of the media card. `action` is `"media_prev"`, `"media_toggle"` or `"media_next"`. No ring is drawn there, and a long press does nothing.
- Overlays for pages no longer listed are discarded. The current page is kept by id if it still exists, else the screen shows the first page.

**Transfers:**
- **Chunks** must arrive in order: the chunk's offset equals the bytes received so far. Otherwise the ACK is `{"ok": false, "error": "offset", "have": n}`, and the PC restarts the transfer.
- **Kinds:**
  - `overlay` goes to PSRAM under `id`: a page id, or `@event` for an event animation's text.
  - `file` goes to flash. `BEGIN` is refused with `"no_space"` (plus `flash_free`) when it cannot fit, counting the space a file of the same id would free.
  - `toast` is an overlay shown over the current page for `seconds` (default 2), then forgotten.
- **File ids:** `bg-<hash>` are page backgrounds, `anim-<event>-<hash>` event animations (`launch`, `levelup`, `death`), `boot` the start animation, `idle` the idle cat. A sync deletes every file the PC no longer wants, `boot` included (since 2026-10-28 the PC sends it like the others). Animations, `boot` included, are sent after the page list, so the pages show up first. An event whose animation is the same as `boot` gets no file of its own: PLAY names `boot`.
- **Formats:** `jpeg` and `gif` are 480×320, ready to show. `sprite` is a small image in the overlay format below (any even width, 4-bit alpha), drawn by the screen itself: the idle cat. `mjpeg` comes with the video step.
- **GIF frames are deltas.** After the first frame, a pixel that did not change is stored as the transparent colour, and frames use disposal 1 ("do not dispose"). The screen must draw each frame over the previous one, skipping transparent pixels, into a full 480×320 canvas that persists between frames. Disposal 2 ("restore to background") is honoured too. When the GIF loops, the first frame is complete again.
- **Except over the page.** A GIF played with `over_page` uses the transparent colour for "the page shows here", so its frames are not deltas: every frame is complete and uses disposal 2. The screen draws each one on a fresh copy of the dimmed page, with nothing left over from the frame before.

## Overlay format

zlib stream (with header) of:

```
"OV1" | width:u16 LE | height:u16 LE | alpha plane | colour plane
```

- **Alpha plane:** 4 bits per pixel, two pixels per byte, the even pixel in the high nibble. 0 = transparent, 15 = opaque.
- **Colour plane:** RGB565, u16 little-endian per pixel. Fully transparent pixels have colour 0, so empty areas compress to almost nothing.
- **Compositing:** `out = bg + (fg − bg) × a / 15` per channel. Typical pages are 15–25 kB compressed, from 384 kB raw.

## Screen behaviour

| | Value |
|---|---|
| Heartbeat | The PC sends something at least every **30 s** (PING when idle), and re-renders every page once a minute. |
| Offline | **90 s** without a valid frame: "PC disconnected" screen (built into the firmware), backlight at **30 %**. Any valid frame brings full brightness back. Before the first frame: "Waiting for the PC". |
| Tap | Under **0.4 s** and within **12 px** of the touch-down point: `EVENT tap`. Inside a tap zone (judged at touch-down) the event carries the zone's `action`, and the PC runs that media button; the card is re-sent once the player has changed. Elsewhere the PC answers with a refresh, or a "Too soon" toast. |
| Swipe | At least **60 px** horizontally, more horizontal than vertical: next (left) or previous (right) page, wrapping around. **0.28 s** slide, ease-out. Then `EVENT page`. |
| Long press | Held still **0.4 s** inside a zone: a ring of radius **30 px** appears around the finger and fills clockwise over **1.5 s**. Moving or lifting cancels it. When it closes: `EVENT reset` with the zone's action. The PC resets the value and sends a toast. Outside any zone, a long press does nothing. |
| Dots | Drawn by the screen at the bottom (y = 311), or an "n/N" counter above 8 pages. |
| Idle | After IDLE with a sprite: black, with the sprite drawn at full brightness. It starts in the middle, heading in a random diagonal direction at **100 px/s** (`IDLE_SPEED`), and bounces off the edges of its visible pixels as turned (alpha > 0), never leaving the screen. It turns to face its travel: angle = −atan2(vy, vx), counter-clockwise in degrees (upright going right, upside down going left), easing towards it with a **0.25 s** time constant (`IDLE_TURN`), to the nearest degree. Event animations (PLAY) are drawn instead while they play, then the cat again. Any touch on the cat (judged at touch-down, not during an animation) ends it, shows the pages and sends `EVENT wake` on release; the gesture does nothing else. HELLO, going offline, and deleting the sprite file all end it too. |
| Boot | At power-on, the `boot` file plays if present, then the pages or the offline screen. A GIF plays once, looping until **3 s** if shorter and cut at **10 s**; an image shows for **4 s**. A PLAY from the PC replaces it, like any other animation. |
