#include "display.h"

#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <driver/spi_master.h>
#include <esp_heap_caps.h>

#include "board.h"

namespace display {
namespace {

constexpr size_t kStripPixels = kWidth * kStripRows;

Arduino_DataBus *bus;
Arduino_AXS15231B *gfx;
spi_device_handle_t dev;
uint16_t *strips[2];
spi_transaction_ext_t trans[2];

bool addDevice(uint32_t hz) {
  // Same shape as Arduino_GFX's device; it drives CS by hand, and so do we.
  spi_device_interface_config_t cfg = {};
  cfg.command_bits = 8;
  cfg.address_bits = 24;
  cfg.mode = SPI_MODE0;
  cfg.clock_source = SPI_CLK_SRC_DEFAULT;
  cfg.clock_speed_hz = (int)hz;
  cfg.spics_io_num = -1;
  cfg.flags = SPI_DEVICE_HALFDUPLEX;
  cfg.queue_size = 2;
  return spi_bus_add_device(SPI2_HOST, &cfg, &dev) == ESP_OK;
}

void copyStrip(uint16_t *dst, int y, int rows, void *ctx) {
  toPanelOrder(dst, static_cast<const uint16_t *>(ctx) + y * kWidth, (size_t)rows * kWidth);
}

}  // namespace

void toPanelOrder(uint16_t *dst, const uint16_t *src, size_t n) {
  // Two pixels per 32-bit word; both pointers are 4-byte aligned here.
  auto *d = reinterpret_cast<uint32_t *>(dst);
  auto *s = reinterpret_cast<const uint32_t *>(src);
  for (size_t i = 0; i < n / 2; ++i) {
    uint32_t v = s[i];
    d[i] = ((v & 0x00FF00FF) << 8) | ((v >> 8) & 0x00FF00FF);
  }
  if (n & 1) dst[n - 1] = __builtin_bswap16(src[n - 1]);
}

bool begin(uint32_t hz) {
  ledcAttach(pins::kBacklight, 20000, 8);
  backlight(0);
  // Shared interface: Arduino_GFX takes the bus only while it writes, so our device can use it too.
  bus = new Arduino_ESP32QSPI(pins::kLcdCs, pins::kLcdSck, pins::kLcdD0, pins::kLcdD1, pins::kLcdD2,
                              pins::kLcdD3, true);
  gfx = new Arduino_AXS15231B(bus, GFX_NOT_DEFINED, 0, false, kWidth, kHeight, 0, 0, 0, 0,
                              axs15231b_320480_type1_init_operations,
                              sizeof(axs15231b_320480_type1_init_operations));
  if (!gfx->begin()) return false;
  for (auto &s : strips) {
    s = (uint16_t *)heap_caps_aligned_alloc(16, kStripPixels * 2, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!s) return false;
  }
  return addDevice(hz);
}

void setSpeed(uint32_t hz) {
  spi_bus_remove_device(dev);
  addDevice(hz);
}

uint32_t speed() {
  int khz = 0;
  spi_device_get_actual_freq(dev, &khz);
  return khz * 1000u;
}

void backlight(uint8_t level) { ledcWrite(pins::kBacklight, level); }

void pushFrame(StripFn fill, void *ctx) {
  gfx->startWrite();
  gfx->writeAddrWindow(0, 0, kWidth, kHeight);
  gfx->endWrite();

  spi_device_acquire_bus(dev, portMAX_DELAY);
  digitalWrite(pins::kLcdCs, LOW);
  constexpr int kCount = kHeight / kStripRows;
  for (int i = 0; i < kCount; ++i) {
    int k = i & 1;
    if (i >= 2) {
      spi_transaction_t *done;
      spi_device_get_trans_result(dev, &done, portMAX_DELAY);
    }
    fill(strips[k], i * kStripRows, kStripRows, ctx);
    spi_transaction_ext_t &t = trans[k];
    t = {};
    t.base.flags = SPI_TRANS_MODE_QIO;
    if (i == 0) {
      t.base.cmd = 0x32;          // quad pixel write
      t.base.addr = 0x003C00;     // RAMWRC: continue at the window start set above
    } else {
      // No command or address: the same write goes on while CS stays low.
      t.base.flags |= SPI_TRANS_VARIABLE_CMD | SPI_TRANS_VARIABLE_ADDR | SPI_TRANS_VARIABLE_DUMMY;
    }
    t.base.tx_buffer = strips[k];
    t.base.length = kStripPixels * 16;
    spi_device_queue_trans(dev, &t.base, portMAX_DELAY);
  }
  for (int i = 0; i < 2; ++i) {
    spi_transaction_t *done;
    spi_device_get_trans_result(dev, &done, portMAX_DELAY);
  }
  digitalWrite(pins::kLcdCs, HIGH);
  spi_device_release_bus(dev);
}

void pushFrame(const uint16_t *fb) { pushFrame(copyStrip, (void *)fb); }

void pushFrameLibrary(const uint16_t *fb) {
  gfx->draw16bitRGBBitmap(0, 0, const_cast<uint16_t *>(fb), kWidth, kHeight);
}

}  // namespace display
