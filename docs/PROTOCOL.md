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
| 0x07 | PLAY | PC → screen | `{"file": id \| null, "overlay": "@event" \| null, "seconds"}`: full-screen event animation |
| 0x08 | PING | PC → screen | `{}`: heartbeat |
| 0x09 | EVENT_ACK | PC → screen | empty. The seq is the event's. |
| 0x81 | ACK | screen → PC | `{"ok": true, ...}` or `{"ok": false, "error": "..."}`. The seq is the request's. |
| 0x82 | EVENT | screen → PC | `{"type": "tap" \| "page" \| "reset", "page": id, "action"?}` |
| 0x83 | LOG | screen → PC | `{"text"}`: debug output, not acknowledged |

**Inventory** (the ACK to HELLO):
```json
{"ok": true, "version": 1, "firmware": "…", "width": 480, "height": 320,
 "flash_total": 11534336, "flash_free": 9000000,
 "overlays": {"<page id>": "<crc>"},
 "files": {"<file id>": {"crc": "…", "size": 123, "format": "jpeg"}}}
```
The PC compares this with what it wants on the screen and only sends what differs. A reconnect after a cable pull resends nothing. After a power cycle, the overlays (kept in PSRAM) are resent; the files (in flash) are not.

**Page entries in PAGES:**
- `bg` is either `{"color": "#rrggbb"}` or `{"file": "<file id>", "color": "#rrggbb"}`. The colour is the fallback if the file is missing.
- `zones` lists `{"x", "y", "w", "h", "action"}` rectangles where a long press resets something. `action` is `"reset_session"` or `"reset_rate"`.
- Overlays for pages no longer listed are discarded. The current page is kept by id if it still exists, else the screen shows the first page.

**Transfers:**
- **Chunks** must arrive in order: the chunk's offset equals the bytes received so far. Otherwise the ACK is `{"ok": false, "error": "offset", "have": n}`, and the PC restarts the transfer.
- **Kinds:**
  - `overlay` goes to PSRAM under `id`: a page id, or `@event` for an event animation's text.
  - `file` goes to flash. `BEGIN` is refused with `"no_space"` (plus `flash_free`) when it cannot fit, counting the space a file of the same id would free.
  - `toast` is an overlay shown over the current page for `seconds` (default 2), then forgotten.
- **File ids:** `bg-<hash>` are page backgrounds, `anim-*` event animations, `boot` the power-on animation. A page sync deletes stale `bg-*` files only.
- **Formats:** `jpeg` and `gif` are 480×320, ready to show. `mjpeg` comes with the video step.

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
| Tap | Under **0.4 s** and within **12 px** of the touch-down point: `EVENT tap`. The PC answers with a refresh, or a "Too soon" toast. |
| Swipe | At least **60 px** horizontally, more horizontal than vertical: next (left) or previous (right) page, wrapping around. **0.28 s** slide, ease-out. Then `EVENT page`. |
| Long press | Held still **0.4 s** inside a zone: a ring of radius **30 px** appears around the finger and fills clockwise over **1.5 s**. Moving or lifting cancels it. When it closes: `EVENT reset` with the zone's action. The PC resets the value and sends a toast. Outside any zone, a long press does nothing. |
| Dots | Drawn by the screen at the bottom (y = 311), or an "n/N" counter above 8 pages. |
| Boot | At power-on, the `boot` file plays once if present, then the pages or the offline screen. |
