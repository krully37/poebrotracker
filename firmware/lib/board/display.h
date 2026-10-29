// The AXS15231B panel. Only full frames are pushed (the panel ignores partial windows).
//
// Arduino_GFX sends the init sequence and the address window. The pixels go through our own
// SPI device on the same bus: two DMA strips in internal RAM, so the next strip is filled while
// the previous one is on the wire.
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace display {

// The panel's own orientation (portrait).
constexpr int kWidth = 320;
constexpr int kHeight = 480;
constexpr int kStripRows = 16;

bool begin(uint32_t hz = 40000000);
// Changes the QSPI clock for the pixel data (commands stay on Arduino_GFX's 40 MHz).
void setSpeed(uint32_t hz);
// The clock the SPI driver actually picked.
uint32_t speed();
// 0 = off, 255 = full.
void backlight(uint8_t level);

// Writes rows [y, y + rows) into dst, in panel byte order (big-endian RGB565).
using StripFn = void (*)(uint16_t *dst, int y, int rows, void *ctx);
void pushFrame(StripFn fill, void *ctx);
// A full frame of native little-endian RGB565, kWidth × kHeight.
void pushFrame(const uint16_t *fb);
// Little-endian RGB565 to panel order (big-endian).
void toPanelOrder(uint16_t *dst, const uint16_t *src, size_t n);
// The same frame through Arduino_GFX's own path (one blocking transfer at a time), for comparison.
void pushFrameLibrary(const uint16_t *fb);

}  // namespace display
