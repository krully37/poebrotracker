# Project brief — "Stash value" desk display for Path of Exile 1

This document is a **starting brief** for the software side. The hardware has been ordered but not yet received. Items marked **[TO VERIFY]** have not been confirmed on the actual hardware.

## 1. Goal

Build a small touchscreen for a friend who plays **Path of Exile 1**. It sits next to the keyboard and continuously shows the value of his stash, as computed by **WealthyExile**.

Inspiration: a Reddit post on r/pathofexile, "My loot goblin brain needed the number to keep going up even while I map, so I built this". Differences from the original:
- **USB-wired** to the PC (no Wi-Fi, no battery).
- **Larger screen**: 3.5", landscape orientation.
- **No auto-rotation**: the board has no accelerometer.

## 2. What the screen should show

Automatic refresh **every 5 minutes**. **Swipe** to change page, **tap** to force a refresh.

| Page | Content |
|---|---|
| 1. Total | Total stash value in **divines**, gain in **divines/hour**, a small **sparkline** of the trend, and a "synced X min ago" indicator |
| 2. Top | The **8 most valuable stacks** (name, quantity, value), plus **per-tab totals** |
| 3. Session | **Gain for the current session** (since launch or a reset) and the **current divine price** in chaos |
| 4. Free | To be defined. Ideas: divine price chart, countdown to the next league |

It also needs a pagination indicator (dots), the time, and a clear state when the PC or script is disconnected.

## 3. Non-negotiable constraints

- **Nothing touches the game**: no memory reading, no input injection, no overlay.
- **The WealthyExile session cookie stays on the PC.** The screen only receives pre-computed numbers.
- **Requests to WealthyExile are spaced out**, about every 5 minutes, matching normal site usage. No hammering.
- No dependency on a personal cloud service.

## 4. Hardware (ordered)

**Guition JC3248W535C_I_Y**: ESP32-S3 with a 3.5" capacitive touchscreen, case included.

- ESP32-S3 SoC, **16 MB flash, 8 MB PSRAM** (likely OPI [TO VERIFY]).
- **320×480** IPS display, **AXS15231B** controller on a **QSPI** bus. Capacitive touch is integrated into the same AXS15231B, on I2C.
- USB-C. Native ESP32-S3 USB or a USB-serial chip: [TO VERIFY] when plugged in.
- No IMU. A microSD slot and a LiPo charging circuit are present but not needed here.

### Known pitfalls with this display (must be respected)
- It only works with **full-screen refresh**. LVGL partial or direct render mode is broken.
- **No hardware rotation**: landscape mode (480×320) must be done **in software** (rotated canvas, or LVGL software rotation).
- Some batches ignore the address-window commands (0x2A/0x2B), probably non-genuine silicon. Always push the full frame.
- **TFT_eSPI does not support QSPI**. Use **Arduino_GFX ≥ 1.5** (moononournation) or ESP-IDF's esp_lcd.
- ESPHome has a JC3248W535 preset (mipi_spi component), useful as a configuration reference.

### Pinout most often cited by the community [TO VERIFY against the vendor docs or examples]
- Display QSPI: CS 45, SCK 47, D0 21, D1 48, D2 40, D3 39. Backlight: GPIO 1.
- Touch I2C: SDA 4, SCL 8, INT 3, address 0x3B.

### Likely build settings (Arduino ESP32 core 3.x)
- Board: *ESP32S3 Dev Module*. 16 MB flash. OPI PSRAM. *USB CDC On Boot* enabled if USB is native. A partition scheme with enough room for the app.

## 5. Proposed architecture

```
[WealthyExile (web)] --HTTPS + cookie--> [PC script] --USB serial (line-delimited JSON)--> [ESP32-S3 screen]
                                               ^                                                 |
                                               +------------- "refresh" when screen is tapped ---+
```

### 5.1 PC script (Python recommended)
- It connects to WealthyExile with the **user's session cookie**, stored in a local config file and never committed.
- **WealthyExile has no documented public API.** Use the browser developer tools (Network tab) to find the JSON requests the site itself uses to show the total and the stash details. Plan for:
  - a **`--dump` mode** that saves the raw responses so the parsing can be tuned;
  - an **isolated adapter** (a single module), so that when the site changes only one part needs rewriting.
- Computations done on the PC:
  - **divines/hour** from the history of totals;
  - **sparkline** over the last N points;
  - **session gain**;
  - **top 8** and **per-tab totals**.
- History is kept in a small local file (JSON or SQLite) so it survives a restart.
- **Divine price**: from WealthyExile if available, otherwise from the poe.ninja economy endpoints. These are officially supported (docs: https://poe.ninja/docs/api), with a request not to abuse them. League: the current PoE1 challenge league, configurable.
- **Automatic serial port detection** (VID/PID or handshake), with reconnection if the screen is unplugged and plugged back in.
- A **`--demo` mode** that sends fake data, so the screen can be developed without depending on WealthyExile.
- Starts automatically when the PC boots, running quietly in the background.

### 5.2 Serial protocol (proposal, to be adjusted)
- 115200 baud, **one JSON message per line**, terminated with `\n`.
- PC → screen:
  - `{"t":"hello"}`
  - `{"t":"data", "total":239.9, "rate":3.8, "spark":[...], "top":[{"n":"Divine Orb","q":120,"v":120.0},...], "tabs":[{"n":"Currency","v":180.2},...], "session":23.3, "divPrice":215, "ts":1730000000, "league":"..."}`
- Screen → PC:
  - `{"t":"hello","fw":"x.y"}`
  - `{"t":"refresh"}` on tap.
- The screen shows "PC disconnected" if nothing has arrived for more than 10–15 min.

### 5.3 Screen firmware (Arduino + Arduino_GFX)
- Full-screen framebuffer in PSRAM, software rotation to landscape, then push the full frame on every redraw.
- Read the I2C touch (AXS15231B): detect **left/right swipe** to change page, **tap** to send `refresh`.
- Clean rendering, in the style of the original:
  - black background, large main number, gain in green;
  - yellow or orange sparkline;
  - pagination dots;
  - a simply drawn divine icon, without reusing any game asset.
- LVGL is possible but not required: drawing directly on a canvas may be enough for 4 pages.

## 6. Suggested steps

1. **Hardware received**: flash an Arduino_GFX "hello world" example to validate the pinout, landscape display and touch.
2. Firmware with the 4 pages fed by hard-coded **fake data**.
3. PC script in **demo mode**, then the serial link and handshake.
4. **Reverse-engineer WealthyExile** with the user logged in: dump mode, then the parsing adapter.
5. Computations (divines/h, session, sparkline), history, divine price.
6. Auto-start at boot and a short install guide for the friend: flash the screen, configure the cookie, run the script.

## 7. Open questions

- Exact format of the WealthyExile responses, and whether the site already exposes the top items and per-tab totals.
- OS of the friend's PC (probably Windows): affects auto-start and the serial driver.
- Content of page 4.
- Is the board's USB native, or does it go through a CH340? To be checked when plugged in.

## 8. References

- Board specs and pitfalls: https://www.atomic14.com/esp32/boards/guition-jc3248w535/
- JC3248W535 getting started (FR): https://f1atb.fr/fr/domotique/esp32-s3/esp32-s3-ecran-capacitif-de-3-5-pouces-mise-en-route/
- Arduino_GFX: https://github.com/moononournation/Arduino_GFX
- AXS15231B driver notes (LVGL forum): https://forum.lvgl.io/t/jc3248w535-axs15231b-driver/18707
- Working ESPHome example: https://community.home-assistant.io/t/guition-3-5-320x480-jc3248w535en-lcd-dev-board-working-example/774022
- Alternative printable case (MakerWorld): https://makerworld.com/en/models/1026987-guition-jc3248w535-3-5-esp32-desktop-enclosure
- poe.ninja API (economy endpoints): https://poe.ninja/docs/api
