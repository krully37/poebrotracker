// Step 5 hardware bench. Runs every measurement at start-up and prints the results, then shows a
// test pattern and follows the finger. Commands over serial (one per line):
//   bench          run the measurements again
//   pattern        orientation and colour test pattern
//   page           the demo page: background with the overlay composited on top
//   speed <MHz>    QSPI clock for the pixel data, then the pattern again
//   bl <0-255>     backlight
//   usb <n>        receive n raw bytes as fast as they come, report the time
//   usback <n>     receive n bytes in 4 kB chunks, answering each with one byte (like the protocol)
#include <Arduino.h>
#include <AnimatedGIF.h>
#include <Arduino_GFX_Library.h>
#include <JPEGDEC.h>
#include <esp_heap_caps.h>
#include <esp_rom_crc.h>
#include <miniz.h>

#include "display.h"
#include "touch.h"
#include "usblink.h"

using display::kHeight;
using display::kWidth;

#define EMBEDDED(name, file)                                      \
  extern const uint8_t name##_start[] asm("_binary_bench_data_" file "_start"); \
  extern const uint8_t name##_end[] asm("_binary_bench_data_" file "_end");
EMBEDDED(bg, "bg_rgb565")
EMBEDDED(ov, "overlay_ov1z")
EMBEDDED(jpg, "page_jpg")
EMBEDDED(gif, "anim_gif")

// The ROM inflater keeps its ~11 kB state on the stack; Arduino's loop task has only 8 kB.
SET_LOOP_TASK_STACK_SIZE(32 * 1024);

namespace {

constexpr size_t kPixels = kWidth * kHeight;

uint16_t *bg;        // PSRAM, the background (little-endian RGB565)
uint8_t *overlay;    // PSRAM, the inflated overlay ("OV1" | w | h | alpha | colour)
uint16_t *scratch;   // PSRAM, decoder output and the drawing canvas
Arduino_Canvas *canvas;
uint16_t *frame;     // what is on screen now, so touch dots can be drawn over it

uint32_t ms() { return millis(); }

void *psram(size_t n) { return heap_caps_malloc(n, MALLOC_CAP_SPIRAM); }

// --- Overlay ------------------------------------------------------------------------------

size_t inflateOverlay() {
  size_t raw = 7 + kPixels / 2 + kPixels * 2;
  return tinfl_decompress_mem_to_mem(overlay, raw, ov_start, ov_end - ov_start,
                                     TINFL_FLAG_PARSE_ZLIB_HEADER);
}

// out = bg + (fg − bg) × a / 15, per channel, written big-endian for the panel.
void compositeStrip(uint16_t *dst, int y, int rows, void *) {
  const uint8_t *alpha = overlay + 7;
  const uint16_t *colour = (const uint16_t *)(overlay + 7 + kPixels / 2);
  size_t start = (size_t)y * kWidth, end = start + (size_t)rows * kWidth;
  for (size_t i = start; i < end; ++i) {
    uint8_t a = alpha[i >> 1];
    a = (i & 1) ? (a & 15) : (a >> 4);
    uint16_t b = bg[i], out;
    if (a == 0) {
      out = b;
    } else if (a == 15) {
      out = colour[i];
    } else {
      uint16_t f = colour[i];
      int br = b >> 11, bgn = (b >> 5) & 63, bb = b & 31;
      int fr = f >> 11, fg = (f >> 5) & 63, fb = f & 31;
      int r = br + (fr - br) * a / 15, g = bgn + (fg - bgn) * a / 15, bl = bb + (fb - bb) * a / 15;
      out = (r << 11) | (g << 5) | bl;
    }
    *dst++ = __builtin_bswap16(out);
  }
}

void compositeInto(uint16_t *fb) {
  for (int y = 0; y < kHeight; y += display::kStripRows) {
    compositeStrip(fb + y * kWidth, y, display::kStripRows, nullptr);
  }
  for (size_t i = 0; i < kPixels; ++i) fb[i] = __builtin_bswap16(fb[i]);
}

// --- JPEG and GIF -------------------------------------------------------------------------

JPEGDEC jpeg;

int jpegDraw(JPEGDRAW *d) {
  for (int row = 0; row < d->iHeight; ++row) {
    memcpy(scratch + (d->y + row) * 480 + d->x, d->pPixels + row * d->iWidth, d->iWidth * 2);
  }
  return 1;
}

AnimatedGIF gif;

// Draws one line of a frame into a persistent 480×320 canvas, skipping see-through pixels
// (the PC stores unchanged pixels as see-through, docs/PROTOCOL.md).
void gifDraw(GIFDRAW *d) {
  uint16_t *line = scratch + (d->iY + d->y) * 480 + d->iX;
  const uint16_t *pal = d->pPalette;
  const uint8_t *src = d->pPixels;
  if (d->ucHasTransparency) {
    uint8_t t = d->ucTransparent;
    for (int x = 0; x < d->iWidth; ++x) {
      if (src[x] != t) line[x] = pal[src[x]];
    }
  } else {
    for (int x = 0; x < d->iWidth; ++x) line[x] = pal[src[x]];
  }
}

// --- Screens ------------------------------------------------------------------------------

void showPattern() {
  canvas->fillScreen(RGB565_BLACK);
  int band = kHeight / 6;
  canvas->fillRect(0, 0, kWidth, band, RGB565_RED);
  canvas->fillRect(0, band, kWidth, band, RGB565_GREEN);
  canvas->fillRect(0, 2 * band, kWidth, band, RGB565_BLUE);
  canvas->setTextSize(3);
  canvas->setTextColor(RGB565_WHITE);
  canvas->setCursor(10, 10);
  canvas->print("1 RED (top)");
  canvas->setTextColor(RGB565_BLACK);
  canvas->setCursor(10, band + 10);
  canvas->print("2 GREEN");
  canvas->setTextColor(RGB565_WHITE);
  canvas->setCursor(10, 2 * band + 10);
  canvas->print("3 BLUE");
  for (int x = 0; x < kWidth; ++x) {  // grey ramp, left dark to right light
    canvas->drawFastVLine(x, 3 * band, band, canvas->color565(x * 255 / kWidth, x * 255 / kWidth, x * 255 / kWidth));
  }
  canvas->fillTriangle(0, 0, 40, 0, 0, 40, RGB565_YELLOW);  // top-left corner marker
  canvas->drawRect(0, 0, kWidth, kHeight, RGB565_WHITE);
  canvas->setTextSize(2);
  canvas->setTextColor(RGB565_WHITE);
  canvas->setCursor(10, 4 * band + 10);
  canvas->printf("%d MHz", (int)(display::speed() / 1000000));
  canvas->setCursor(10, 4 * band + 40);
  canvas->print("touch me: dots follow");
  memcpy(frame, canvas->getFramebuffer(), kPixels * 2);
  display::pushFrame(frame);
}

void showPage() {
  compositeInto(frame);
  display::pushFrame(frame);
}

// --- Measurements -------------------------------------------------------------------------

template <typename F>
float fps(int frames, F push) {
  uint32_t t = ms();
  for (int i = 0; i < frames; ++i) push();
  return frames * 1000.0f / (ms() - t);
}

void runBench() {
  usb.println("== bench ==");
  usb.printf("cpu %u MHz\n", (unsigned)getCpuFrequencyMhz());
  usb.printf("psram free %u, internal free %u\n", heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
                heap_caps_get_free_size(MALLOC_CAP_INTERNAL));

  uint32_t t = micros();
  size_t n = inflateOverlay();
  usb.printf("overlay inflate: %u bytes -> %u in %.1f ms\n", (unsigned)(ov_end - ov_start), (unsigned)n,
                (micros() - t) / 1000.0f);

  uint16_t *src = (uint16_t *)canvas->getFramebuffer();
  uint32_t speed = display::speed();
  usb.printf("push, Arduino_GFX path (40 MHz): %.1f fps\n", fps(10, [&] { display::pushFrameLibrary(src); }));
  for (uint32_t mhz : {40, 60, 80}) {
    display::setSpeed(mhz * 1000000);
    usb.printf("push, DMA strips from PSRAM (asked %u MHz, got %u kHz): %.1f fps\n", (unsigned)mhz,
                  (unsigned)(display::speed() / 1000), fps(20, [&] { display::pushFrame(src); }));
    usb.printf("push, strips left as they are (bus only): %.1f fps\n",
                  fps(20, [&] { display::pushFrame([](uint16_t *, int, int, void *) {}, nullptr); }));
  }
  display::setSpeed(speed);

  static uint16_t strip[kWidth * display::kStripRows];  // internal RAM, like the DMA strips
  t = micros();
  for (int y = 0; y < kHeight; y += display::kStripRows) {
    display::toPanelOrder(strip, src + y * kWidth, kWidth * display::kStripRows);
  }
  usb.printf("swap-copy only (PSRAM -> strip, one frame): %.1f ms\n", (micros() - t) / 1000.0f);
  t = micros();
  for (int y = 0; y < kHeight; y += display::kStripRows) {
    memcpy(strip, src + y * kWidth, kWidth * display::kStripRows * 2);
  }
  usb.printf("memcpy only (PSRAM -> strip, one frame): %.1f ms\n", (micros() - t) / 1000.0f);
  t = micros();
  for (int y = 0; y < kHeight; y += display::kStripRows) compositeStrip(strip, y, display::kStripRows, nullptr);
  usb.printf("composite only (bg + overlay, one frame): %.1f ms\n", (micros() - t) / 1000.0f);
  usb.printf("composite + push (%u MHz): %.1f fps\n", (unsigned)(speed / 1000000),
                fps(20, [&] { display::pushFrame(compositeStrip, nullptr); }));

  jpeg.openRAM((uint8_t *)jpg_start, jpg_end - jpg_start, jpegDraw);
  jpeg.setPixelType(RGB565_LITTLE_ENDIAN);
  t = micros();
  jpeg.decode(0, 0, 0);
  usb.printf("jpeg decode 480x320 (%u bytes): %.1f ms\n", (unsigned)(jpg_end - jpg_start),
                (micros() - t) / 1000.0f);
  jpeg.close();

  if (gif.open((uint8_t *)gif_start, gif_end - gif_start, gifDraw)) {
    int frames = 0, delays = 0, delay;
    t = micros();
    while (gif.playFrame(false, &delay) > 0) {
      ++frames;
      delays += delay;
    }
    uint32_t us = micros() - t;
    usb.printf("gif decode: %d frames in %.1f ms, %.1f ms/frame (the GIF wants %d ms/frame)\n", frames + 1,
                  us / 1000.0f, us / 1000.0f / (frames + 1), delays / (frames ? frames : 1));
    gif.close();
  } else {
    usb.printf("gif open failed: %d\n", gif.getLastError());
  }
  usb.println("== done ==");
}

// --- USB ----------------------------------------------------------------------------------

void receive(size_t total, bool ack) {
  static uint8_t buf[4096];
  usb.println("ready");
  size_t got = 0, sinceAck = 0;
  uint32_t crc = 0, t = 0, last = ms();
  while (got < total) {
    int n = usb.read(buf, min(sizeof(buf), total - got));
    if (n <= 0) {
      if (ms() - last > 3000) break;
      continue;
    }
    if (got == 0) t = micros();
    last = ms();
    crc = esp_rom_crc32_le(crc, buf, n);
    got += n;
    sinceAck += n;
    if (ack && (sinceAck >= sizeof(buf) || got == total)) {
      usb.write('k');
      sinceAck = 0;
    }
  }
  uint32_t us = micros() - t;
  usb.printf("\nusb%s: %u of %u bytes in %.1f ms, %.1f kB/s, crc %08x\n", ack ? "ack" : "", (unsigned)got,
                (unsigned)total, us / 1000.0f, got / 1.024f / (us / 1000.0f), (unsigned)crc);
}

void command(String line) {
  line.trim();
  int sp = line.indexOf(' ');
  String cmd = sp < 0 ? line : line.substring(0, sp);
  long arg = sp < 0 ? 0 : line.substring(sp + 1).toInt();
  if (cmd == "bench") {
    runBench();
    showPattern();
  } else if (cmd == "pattern") {
    showPattern();
  } else if (cmd == "page") {
    showPage();
  } else if (cmd == "speed" && arg > 0) {
    display::setSpeed(arg * 1000000);
    showPattern();
  } else if (cmd == "bl") {
    display::backlight(arg);
  } else if (cmd == "usb" && arg > 0) {
    receive(arg, false);
  } else if (cmd == "usback" && arg > 0) {
    receive(arg, true);
  } else if (cmd.length()) {
    usb.printf("unknown: %s\n", line.c_str());
  }
}

}  // namespace

void setup() {
  delay(1500);  // time for the PC to open the port after a reset

  bool ok = display::begin();
  usb.printf("display: %s\n", ok ? "ok" : "FAILED");
  usb.printf("touch: %s\n", touch::begin() ? "ok (0x3B answers)" : "FAILED (no answer at 0x3B)");

  // The real firmware keeps backgrounds in PSRAM, so time it from there, not from mapped flash.
  bg = (uint16_t *)psram(kPixels * 2);
  memcpy(bg, bg_start, kPixels * 2);
  overlay = (uint8_t *)psram(7 + kPixels / 2 + kPixels * 2);
  scratch = (uint16_t *)psram(kPixels * 2);
  frame = (uint16_t *)psram(kPixels * 2);
  canvas = new Arduino_Canvas(kWidth, kHeight, nullptr);
  canvas->begin(GFX_SKIP_OUTPUT_BEGIN);
  gif.begin(GIF_PALETTE_RGB565_LE);

  showPattern();
  display::backlight(255);
  runBench();
  showPattern();
}

void loop() {
  static String line;
  int c;
  while ((c = usb.read()) >= 0) {
    if (c == '\n') {
      command(line);
      line = "";
    } else {
      line += (char)c;
    }
  }

  static bool wasDown = false;
  static int16_t lastX = -1, lastY = -1;
  touch::Point p = touch::read();
  if (p.down && (p.x != lastX || p.y != lastY)) {
    usb.printf("touch %d %d\n", p.x, p.y);
    lastX = p.x;
    lastY = p.y;
    if (p.x >= 0 && p.x < kWidth && p.y >= 0 && p.y < kHeight) {
      for (int dy = -3; dy <= 3; ++dy) {
        for (int dx = -3; dx <= 3; ++dx) {
          int x = p.x + dx, y = p.y + dy;
          if (x >= 0 && x < kWidth && y >= 0 && y < kHeight) frame[y * kWidth + x] = RGB565_MAGENTA;
        }
      }
      display::pushFrame(frame);
    }
  } else if (!p.down && wasDown) {
    usb.println("touch up");
    lastX = lastY = -1;
  }
  wasDown = p.down;
  delay(10);
}
