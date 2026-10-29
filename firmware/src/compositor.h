// Backgrounds and overlays in the PC's landscape layout (480×320), composited and turned to the
// portrait panel on the way out, one DMA strip at a time (docs/SCOPE.md §8b):
// panel x = 319 − landscape y, panel y = landscape x.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <vector>

#include "firmware.h"

namespace compositor {

constexpr size_t kPixels = kLandscapeW * kLandscapeH;
// "OV1" | w | h | alpha (4 bits a pixel) | colour (RGB565), docs/PROTOCOL.md
constexpr size_t kOverlayRaw = 7 + kPixels / 2 + kPixels * 2;

constexpr uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) { return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3); }

// A buffer for one unpacked overlay, in PSRAM. It starts one byte past an even address, so the
// colour plane after the 7-byte header and the alpha plane is 2-byte aligned.
uint8_t *allocOverlay();
// Unpacks an overlay into raw (from allocOverlay). False when it is not a 480×320 overlay.
bool inflate(const uint8_t *z, size_t len, uint8_t *raw);
// A JPEG into a landscape RGB565 buffer. False when it cannot be decoded.
bool decodeJpeg(const std::vector<uint8_t> &data, uint16_t *bg);
void fill(uint16_t *bg, uint16_t color);

// A page: its background with its overlay (unpacked, or nullptr) on top.
struct Layer {
  const uint16_t *bg = nullptr;
  const uint8_t *overlay = nullptr;
};

// A small overlay of any even width (unpacked, header included), at a landscape position.
struct Sprite {
  const uint8_t *ov1;
  int x, y;
};

// A page composited once, in panel order and byte order (kPixels values): pushing it, or
// sliding two of them, is then only copying rows. A sideways slide in landscape moves panel rows.
void flatten(const Layer &layer, uint16_t *flat);

struct Scene {
  const uint16_t *page = nullptr;  // flattened
  // While sliding: the page coming in (flattened), and how far the pages have moved (0–480 px).
  const uint16_t *incoming = nullptr;
  int shift = 0;
  bool forward = true;  // to the next page: everything moves left
  const uint8_t *top = nullptr;  // a full-screen overlay over the pages (toast, reset banner)
  const Sprite *sprites = nullptr;
  int spriteCount = 0;
  // A solid rectangle over everything, in landscape pixels (the reset banner's bar); w = 0: none.
  int barX = 0, barY = 0, barW = 0, barH = 0;
  uint16_t barColor = 0;
};

void push(const Scene &scene);
// A page composited on the way out, for what changes every frame (the offline screen too).
void push(const Layer &layer);

}  // namespace compositor
