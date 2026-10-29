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

constexpr int W = display::kWidth;  // panel row stride of a strip

inline uint16_t blend(uint16_t b, uint16_t f, int a) {
  int br = b >> 11, bg = (b >> 5) & 63, bb = b & 31;
  int fr = f >> 11, fg = (f >> 5) & 63, fb = f & 31;
  int r = br + (fr - br) * a / 15, g = bg + (fg - bg) * a / 15, bl = bb + (fb - bb) * a / 15;
  return (r << 11) | (g << 5) | bl;
}

inline int nibble(const uint8_t *alpha, size_t i) { return (i & 1) ? alpha[i >> 1] & 15 : alpha[i >> 1] >> 4; }

// 16 alpha nibbles at once, for an even start: 0 = all see-through, ~0 = all opaque.
inline uint64_t run16(const uint8_t *alpha, size_t s) {
  uint64_t run;
  memcpy(&run, alpha + s / 2, 8);
  return run;
}

const uint16_t *colourPlane(const uint8_t *raw) { return reinterpret_cast<const uint16_t *>(raw + 7 + kPixels / 2); }

// `count` landscape pixels of a page from index s, down a panel column (d steps by W).
void composeRun(uint16_t *d, const Layer &L, size_t s, int count) {
  static const uint16_t kBlack[16] = {};  // runs are at most a strip's 16 rows
  const uint16_t *b = L.bg ? L.bg + s : kBlack;
  if (L.overlay) {
    const uint8_t *alpha = L.overlay + 7;
    const uint16_t *c = colourPlane(L.overlay) + s;
    uint64_t run = (count == 16 && !(s & 1)) ? run16(alpha, s) : 1;
    if (run == ~0ull) {  // opaque: the overlay
      for (int k = 0; k < count; ++k) d[k * W] = __builtin_bswap16(c[k]);
      return;
    }
    if (run != 0) {
      for (int k = 0; k < count; ++k) {
        int n = nibble(alpha, s + k);
        uint16_t out = n == 0 ? b[k] : n == 15 ? c[k] : blend(b[k], c[k], n);
        d[k * W] = __builtin_bswap16(out);
      }
      return;
    }
  }
  for (int k = 0; k < count; ++k) d[k * W] = __builtin_bswap16(b[k]);  // see-through: the background
}

// A full-screen overlay over what is already in the strip.
void overRun(uint16_t *d, const uint8_t *raw, size_t s, int count) {
  const uint8_t *alpha = raw + 7;
  if (count == 16 && !(s & 1) && run16(alpha, s) == 0) return;
  const uint16_t *c = colourPlane(raw) + s;
  for (int k = 0; k < count; ++k) {
    int n = nibble(alpha, s + k);
    if (n) d[k * W] = __builtin_bswap16(blend(__builtin_bswap16(d[k * W]), c[k], n));
  }
}

void drawSprite(uint16_t *dst, int y0, int rows, const Sprite &sp) {
  const uint8_t *h = sp.ov1;
  int w = h[3] | h[4] << 8, ht = h[5] | h[6] << 8;
  int lx0 = max(sp.x, y0), lx1 = min(sp.x + w, y0 + rows);
  if (lx0 >= lx1) return;
  const uint8_t *alpha = h + 7;
  const uint8_t *colour = h + 7 + (size_t)w * ht / 2;  // may be odd: read byte by byte
  for (int sy = 0; sy < ht; ++sy) {
    int ly = sp.y + sy;
    if (ly < 0 || ly >= kLandscapeH) continue;
    int px = kLandscapeH - 1 - ly;
    for (int lx = lx0; lx < lx1; ++lx) {
      size_t i = (size_t)sy * w + (lx - sp.x);
      int n = nibble(alpha, i);
      if (!n) continue;
      uint16_t c = colour[2 * i] | colour[2 * i + 1] << 8;
      uint16_t &d = dst[(lx - y0) * W + px];
      d = __builtin_bswap16(blend(__builtin_bswap16(d), c, n));
    }
  }
}

// Panel rows [y0, y0 + rows) are landscape columns X; panel column px is landscape row 319 − px.
// Each panel column of the strip reads `rows` neighbouring landscape pixels.
void composeStrip(uint16_t *dst, int y0, int rows, const Layer &layer) {
  for (int px = 0; px < W; ++px) composeRun(dst + px, layer, (size_t)(kLandscapeH - 1 - px) * kLandscapeW + y0, rows);
}

void layerStrip(uint16_t *dst, int y0, int rows, void *ctx) {
  composeStrip(dst, y0, rows, *static_cast<const Layer *>(ctx));
}

void copyRows(uint16_t *dst, const uint16_t *flat, int from, int count) {
  if (flat) {
    memcpy(dst, flat + (size_t)from * W, (size_t)count * W * 2);
  } else {
    memset(dst, 0, (size_t)count * W * 2);
  }
}

void sceneStrip(uint16_t *dst, int y0, int rows, void *ctx) {
  const Scene &S = *static_cast<const Scene *>(ctx);
  int y1 = y0 + rows;
  if (S.live) {
    composeStrip(dst, y0, rows, *S.live);
  } else if (!S.shift || !S.incoming) {
    copyRows(dst, S.page, y0, rows);
  } else if (S.forward) {
    // Panel row r (landscape column) shows the old page's row r + shift, then the new page's.
    int edge = kLandscapeW - S.shift;
    if (y0 < edge) copyRows(dst, S.page, y0 + S.shift, min(y1, edge) - y0);
    if (y1 > edge) {
      int from = max(y0, edge);
      copyRows(dst + (from - y0) * W, S.incoming, from + S.shift - kLandscapeW, y1 - from);
    }
  } else {
    // The new page's row r − shift + 480, then the old page's row r − shift.
    int edge = S.shift;
    if (y0 < edge) copyRows(dst, S.incoming, y0 - S.shift + kLandscapeW, min(y1, edge) - y0);
    if (y1 > edge) {
      int from = max(y0, edge);
      copyRows(dst + (from - y0) * W, S.page, from - S.shift, y1 - from);
    }
  }
  if (S.top) {
    for (int px = 0; px < W; ++px) overRun(dst + px, S.top, (size_t)(kLandscapeH - 1 - px) * kLandscapeW + y0, rows);
  }
  for (int i = 0; i < S.spriteCount; ++i) drawSprite(dst, y0, rows, S.sprites[i]);
  int bx0 = max(S.barX, y0), bx1 = min(S.barX + S.barW, y1);
  for (int lx = bx0; lx < bx1; ++lx) {
    for (int ly = S.barY; ly < S.barY + S.barH; ++ly) {
      dst[(lx - y0) * W + (kLandscapeH - 1 - ly)] = __builtin_bswap16(S.barColor);
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

bool inflateSprite(const uint8_t *z, size_t len, std::vector<uint8_t> &out) {
  constexpr int kFlags = TINFL_FLAG_PARSE_ZLIB_HEADER | TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF;
  uint8_t head[7];
  size_t in = len, got = sizeof(head);
  tinfl_init(&inflator);
  tinfl_status st = tinfl_decompress(&inflator, z, &in, head, head, &got, kFlags | TINFL_FLAG_HAS_MORE_INPUT);
  if (st < TINFL_STATUS_DONE || got != sizeof(head) || memcmp(head, "OV1", 3) != 0) return false;
  size_t w = head[3] | head[4] << 8, h = head[5] | head[6] << 8;
  if (!w || !h || (w & 1) || w * h > kPixels) return false;
  out.resize(7 + w * h / 2 + w * h * 2);
  tinfl_init(&inflator);
  in = len;
  got = out.size();
  st = tinfl_decompress(&inflator, z, &in, out.data(), out.data(), &got, kFlags);
  return st == TINFL_STATUS_DONE && got == out.size();
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

void flatten(const Layer &layer, uint16_t *flat) {
  for (int y = 0; y < display::kHeight; y += display::kStripRows) {
    composeStrip(flat + (size_t)y * W, y, display::kStripRows, layer);
  }
}

void overPageStrip(uint16_t *dst, int y0, int rows, void *ctx) {
  const OverPage &F = *static_cast<const OverPage *>(ctx);
  copyRows(dst, F.base, y0, rows);
  for (int px = 0; px < W; ++px) {
    size_t s = (size_t)(kLandscapeH - 1 - px) * kLandscapeW + y0;
    const uint8_t *m = F.mask + s;
    uint64_t any[2] = {0, 0};
    if (rows == 16) memcpy(any, m, 16);
    if (rows != 16 || any[0] || any[1]) {
      for (int k = 0; k < rows; ++k) {
        if (m[k]) dst[k * W + px] = __builtin_bswap16(F.canvas[s + k]);
      }
    }
    if (F.top) overRun(dst + px, F.top, s, rows);
  }
}

void push(const Scene &scene) { display::pushFrame(sceneStrip, const_cast<Scene *>(&scene)); }

void render(const Scene &scene, uint16_t *out) {
  for (int y = 0; y < display::kHeight; y += display::kStripRows) {
    sceneStrip(out + (size_t)y * W, y, display::kStripRows, const_cast<Scene *>(&scene));
  }
}

void dim(uint16_t *flat, int percent) {
  for (size_t i = 0; i < kPixels; ++i) {
    uint16_t c = __builtin_bswap16(flat[i]);
    int r = (c >> 11) * percent / 100, g = ((c >> 5) & 63) * percent / 100, b = (c & 31) * percent / 100;
    flat[i] = __builtin_bswap16((r << 11) | (g << 5) | b);
  }
}

void push(const OverPage &frame) { display::pushFrame(overPageStrip, const_cast<OverPage *>(&frame)); }

void push(const Layer &layer) { display::pushFrame(layerStrip, const_cast<Layer *>(&layer)); }

}  // namespace compositor
