#include "compositor.h"

#include <Arduino.h>
#include <JPEGDEC.h>
#include <esp_heap_caps.h>
#include <miniz.h>

#include "display.h"

namespace compositor {
namespace {

static_assert(display::kWidth == kLandscapeH && display::kHeight == kLandscapeW, "panel is the landscape turned");

JPEGDEC jpeg;  // ~17 kB: never on the stack
tinfl_decompressor inflator;

struct Layers {
  const uint16_t *bg;
  const uint8_t *alpha;    // nullptr: background only
  const uint16_t *colour;
};

inline uint16_t blend(uint16_t b, uint16_t f, int a) {
  int br = b >> 11, bg = (b >> 5) & 63, bb = b & 31;
  int fr = f >> 11, fg = (f >> 5) & 63, fb = f & 31;
  int r = br + (fr - br) * a / 15, g = bg + (fg - bg) * a / 15, bl = bb + (fb - bb) * a / 15;
  return (r << 11) | (g << 5) | bl;
}

// Panel rows [y0, y0 + rows) are landscape columns; panel column px is landscape row 319 − px.
// Each panel column of the strip reads `rows` neighbouring landscape pixels.
void strip(uint16_t *dst, int y0, int rows, void *ctx) {
  const Layers &L = *static_cast<const Layers *>(ctx);
  for (int px = 0; px < display::kWidth; ++px) {
    size_t s = (size_t)(kLandscapeH - 1 - px) * kLandscapeW + y0;  // even: y0 is a multiple of 16
    const uint16_t *b = L.bg + s;
    uint16_t *d = dst + px;
    const uint8_t *a = L.alpha ? L.alpha + s / 2 : nullptr;
    uint64_t run = 1;  // any non-zero, non-all-ones value
    if (a && rows == 16) memcpy(&run, a, 8);
    if (!a || run == 0) {  // see-through: the background
      for (int k = 0; k < rows; ++k) d[k * display::kWidth] = __builtin_bswap16(b[k]);
      continue;
    }
    const uint16_t *c = L.colour + s;
    if (run == ~0ull) {  // opaque: the overlay
      for (int k = 0; k < rows; ++k) d[k * display::kWidth] = __builtin_bswap16(c[k]);
      continue;
    }
    for (int k = 0; k < rows; ++k) {
      int n = (k & 1) ? (a[k >> 1] & 15) : (a[k >> 1] >> 4);
      uint16_t out = n == 0 ? b[k] : n == 15 ? c[k] : blend(b[k], c[k], n);
      d[k * display::kWidth] = __builtin_bswap16(out);
    }
  }
}

int jpegDraw(JPEGDRAW *d) {
  auto *bg = static_cast<uint16_t *>(d->pUser);
  int w = min(d->iWidth, kLandscapeW - d->x);
  for (int row = 0; row < d->iHeight && d->y + row < kLandscapeH; ++row) {
    if (w > 0) memcpy(bg + (d->y + row) * kLandscapeW + d->x, d->pPixels + row * d->iWidth, w * 2);
  }
  return 1;
}

}  // namespace

uint8_t *allocOverlay() {
  auto *p = static_cast<uint8_t *>(heap_caps_aligned_alloc(16, kOverlayRaw + 1, MALLOC_CAP_SPIRAM));
  return p ? p + 1 : nullptr;
}

bool inflate(const uint8_t *z, size_t len, uint8_t *raw) {
  tinfl_init(&inflator);
  size_t in = len, out = kOverlayRaw;
  tinfl_status st = tinfl_decompress(&inflator, z, &in, raw, raw, &out,
                                     TINFL_FLAG_PARSE_ZLIB_HEADER | TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF);
  return st == TINFL_STATUS_DONE && out == kOverlayRaw && memcmp(raw, "OV1", 3) == 0 &&
         (raw[3] | raw[4] << 8) == kLandscapeW && (raw[5] | raw[6] << 8) == kLandscapeH;
}

bool decodeJpeg(const std::vector<uint8_t> &data, uint16_t *bg) {
  if (!jpeg.openRAM(const_cast<uint8_t *>(data.data()), data.size(), jpegDraw)) return false;
  jpeg.setPixelType(RGB565_LITTLE_ENDIAN);
  jpeg.setUserPointer(bg);
  bool ok = jpeg.decode(0, 0, 0);
  jpeg.close();
  return ok;
}

void fill(uint16_t *bg, uint16_t color) {
  for (size_t i = 0; i < kPixels; ++i) bg[i] = color;
}

void push(const uint16_t *bg, const uint8_t *overlayRaw) {
  Layers L{bg, nullptr, nullptr};
  if (overlayRaw) {
    L.alpha = overlayRaw + 7;
    L.colour = reinterpret_cast<const uint16_t *>(overlayRaw + 7 + kPixels / 2);
  }
  display::pushFrame(strip, &L);
}

}  // namespace compositor
