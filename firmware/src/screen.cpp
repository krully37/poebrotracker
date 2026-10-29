#include "screen.h"

#include <Arduino.h>
#include <esp_heap_caps.h>

#include "compositor.h"
#include "display.h"
#include "pclink.h"
#include "state.h"
#include "storage.h"

#define EMBEDDED(name, file)                                                   \
  extern const uint8_t name##_start[] asm("_binary_assets_" file "_start"); \
  extern const uint8_t name##_end[] asm("_binary_assets_" file "_end");
EMBEDDED(waiting, "offline_waiting_ov1z")
EMBEDDED(disconnected, "offline_disconnected_ov1z")

namespace screen {
namespace {

constexpr uint8_t kFull = 255;
constexpr uint8_t kDim = 77;  // 30 %, docs/PROTOCOL.md

enum class Mode { None, Waiting, Disconnected, Page };

uint16_t *bg;        // landscape RGB565, PSRAM
uint8_t *overlay;    // unpacked, from compositor::allocOverlay()
Mode shown = Mode::None;
uint32_t shownVersion = 0;
std::string bgKey, overlayKey;  // what bg and overlay hold now

void showOffline(Mode mode) {
  bool waiting = mode == Mode::Waiting;
  std::string key = waiting ? "#waiting" : "#disconnected";
  if (overlayKey != key) {
    const uint8_t *z = waiting ? waiting_start : disconnected_start;
    size_t n = waiting ? waiting_end - waiting_start : disconnected_end - disconnected_start;
    overlayKey = compositor::inflate(z, n, overlay) ? key : "";
  }
  if (bgKey != "#black") {
    compositor::fill(bg, 0);
    bgKey = "#black";
  }
  compositor::push(bg, overlayKey == key ? overlay : nullptr);
  display::backlight(kDim);
}

void loadBackground(const Page &page) {
  storage::FileInfo f;
  bool hasFile = !page.bgFile.empty() && storage::info(page.bgFile, f);
  std::string key = hasFile ? page.bgFile + ":" + f.crc : "#" + std::to_string(page.bgColor);
  if (key == bgKey) return;
  if (hasFile && f.format == "jpeg") {
    auto data = storage::read(page.bgFile);
    if (data && compositor::decodeJpeg(*data, bg)) {
      bgKey = key;
      return;
    }
    pclink::log("background %s: cannot decode", page.bgFile.c_str());
  }
  // GIF and video backgrounds come with steps 6c and 6d; until then, the fallback colour.
  compositor::fill(bg, page.bgColor);
  bgKey = "#" + std::to_string(page.bgColor);
}

void showPage(const Page &page, const Overlay *ov) {
  loadBackground(page);
  std::string key = ov ? page.id + ":" + ov->crc : "";
  if (key != overlayKey) {
    overlayKey = "";
    if (ov && compositor::inflate(ov->data->data(), ov->data->size(), overlay)) {
      overlayKey = key;
    } else if (ov) {
      pclink::log("overlay %s: cannot unpack", page.id.c_str());
    }
  }
  compositor::push(bg, overlayKey.empty() ? nullptr : overlay);
  display::backlight(kFull);
}

}  // namespace

void begin() {
  bg = static_cast<uint16_t *>(heap_caps_malloc(compositor::kPixels * 2, MALLOC_CAP_SPIRAM));
  overlay = compositor::allocOverlay();
  tick();
}

void tick() {
  Mode mode;
  uint32_t version;
  Page page;
  Overlay ov;
  bool hasOverlay = false;
  {
    State::Lock l;
    uint32_t now = millis();
    version = state.version;
    if (state.online(now) && !state.pages.empty()) {
      mode = Mode::Page;
      page = state.pages[state.current];
      auto it = state.overlays.find(page.id);
      if (it != state.overlays.end()) {
        ov = it->second;  // keeps the blob alive while we unpack it
        hasOverlay = true;
      }
    } else {
      mode = state.everHeard ? Mode::Disconnected : Mode::Waiting;
    }
  }
  if (mode == shown && (mode != Mode::Page || version == shownVersion)) return;
  if (mode == Mode::Page) {
    showPage(page, hasOverlay ? &ov : nullptr);
  } else {
    showOffline(mode);
  }
  shown = mode;
  shownVersion = version;
}

}  // namespace screen
