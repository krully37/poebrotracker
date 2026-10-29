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

// A buffer for one unpacked overlay, in PSRAM. It starts one byte past an even address, so the
// colour plane after the 7-byte header and the alpha plane is 2-byte aligned.
uint8_t *allocOverlay();
// Unpacks an overlay into raw (from allocOverlay). False when it is not a 480×320 overlay.
bool inflate(const uint8_t *z, size_t len, uint8_t *raw);
// A JPEG into a landscape RGB565 buffer. False when it cannot be decoded.
bool decodeJpeg(const std::vector<uint8_t> &data, uint16_t *bg);
void fill(uint16_t *bg, uint16_t color);
// The background with the overlay (unpacked, or nullptr) on top, sent to the panel.
void push(const uint16_t *bg, const uint8_t *overlayRaw);

}  // namespace compositor
