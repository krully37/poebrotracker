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
| `lib/protocol/` | The PC ↔ screen framing, plain C++ (tested on the PC) |
| `src/` | The screen firmware (env `jc3248w535`, the default): `pclink` (USB link task, core 0), `screen` and `compositor` (core 1), `storage` (LittleFS), `state` (shared between the two) |
| `src/bench/` | Step 5 hardware bench (env `bench`) |
| `assets/` | Offline screens baked into the firmware, made by `pc/tools/firmware_assets.py` |

## Firmware

```bash
cd firmware && pio run -t upload
```

Files sent by the PC live in a LittleFS partition (`partitions.csv`), which uploading new firmware leaves alone.

## Tests

The framing tests run on the PC:

```bash
cd firmware && pio test -e native
```

They need a C++ compiler on PATH. The Mac has one. On Windows, install PlatformIO's MinGW once (`pio pkg install -g -t platformio/toolchain-gccmingw32`), then put `~/.platformio/packages/toolchain-gccmingw32/bin` first on PATH for the command.

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

Closing the serial port with a plain close resets the board; the PC app avoids it (`pc/stashdisplay/link/transport.py`).
