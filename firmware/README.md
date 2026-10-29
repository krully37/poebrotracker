# Screen firmware

PlatformIO project for the Guition JC3248W535 (ESP32-S3). Install PlatformIO Core once:

```bash
python -m venv ~/.platformio/penv
~/.platformio/penv/bin/pip install platformio
```

On Windows the commands are in `~/.platformio/penv/Scripts/`. The board shows up as a COM port (Windows) or `/dev/cu.usbmodem*` (Mac), with no driver to install.

## Layout

| Path | Role |
|---|---|
| `lib/board/` | Board drivers: pins, panel (DMA pixel push), touch, USB serial |
| `src/bench/` | Step 5 hardware bench (env `bench`) |
| `src/` (rest) | The screen firmware, step 6 (env `jc3248w535`) |

## Bench (step 5)

It measures the panel, compositing, the decoders and USB, then shows a test pattern that dots follow under the finger. Results from 2026-10-29 are in `docs/SCOPE.md` §9.

```bash
cd pc && .venv/bin/python tools/bench_data.py PHOTO.jpg
cd firmware && pio run -e bench -t upload
```

`bench_data.py` writes the test files to `firmware/bench_data/` (not committed). Then open the serial port. The results print about 2 s after start-up, and these commands work one per line: `bench`, `pattern`, `page`, `speed <MHz>`, `bl <0-255>`, `usb <n>`, `usback <n>`. For the USB speed:

```bash
cd pc && .venv/bin/python tools/usb_bench.py PORT
```

Closing the serial port resets the board.
