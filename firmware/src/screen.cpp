#include "screen.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <esp_heap_caps.h>
#include <math.h>

#include "compositor.h"
#include "decor_sprites.h"
#include "display.h"
#include "gestures.h"
#include "pclink.h"
#include "state.h"
#include "storage.h"
#include "touch.h"

#define EMBEDDED(name, file)                                                   \
  extern const uint8_t name##_start[] asm("_binary_assets_" file "_start"); \
  extern const uint8_t name##_end[] asm("_binary_assets_" file "_end");
EMBEDDED(waiting, "offline_waiting_ov1z")
EMBEDDED(disconnected, "offline_disconnected_ov1z")

namespace screen {
namespace {

using compositor::Scene;
using compositor::Sprite;

constexpr uint8_t kFull = 255;
constexpr uint8_t kDim = 77;  // 30 %, docs/PROTOCOL.md
constexpr uint32_t kSlideMs = 280;
constexpr int kMaxDots = 8;
constexpr int kDotGap = 14;
constexpr int kDotsY = 311;
constexpr uint16_t kGold = compositor::rgb565(kGoldR, kGoldG, kGoldB);
// The touch controller reports no finger now and then while one is down: only this long without
// one counts as lifting it.
constexpr uint32_t kLiftMs = 60;

enum class Mode { None, Waiting, Disconnected, Page };

// A page made ready to draw: background decoded, then composited with its overlay into panel
// order (compositor::flatten). Three of them: the current page and its two neighbours, so a
// swipe starts at once and is only copying.
struct Prepared {
  std::string id, bgKey, flatKey;
  uint16_t *bg = nullptr;
  uint16_t *flat = nullptr;
  uint32_t used = 0;
};
Prepared slots[3];
uint32_t useClock = 0;
uint8_t *scratchOv;  // an overlay unpacked just long enough to flatten its page

uint16_t *offlineBg;
uint8_t *offlineOv;
uint8_t *topRaw;  // the toast or the reset banner, unpacked
std::string offlineKey, topKey;

// The PC's latest word, copied from `state` when its version changes.
uint32_t seenVersion = ~0u;
std::vector<Page> pages;
std::map<std::string, Overlay> overlays;
size_t current = 0;
std::string toastId;

Mode shown = Mode::None;
bool dirty = true;

gestures::Tracker tracker;
uint32_t lastTouchMs = 0;
float lastX = 0, lastY = 0;
bool holdShown = false;

struct Slide {
  bool on = false;
  size_t from = 0;
  bool forward = true;
  uint32_t start = 0;
  int frames = 0;
  uint32_t pushUs = 0;  // time spent compositing and pushing
} slide;

// --- Pages ---------------------------------------------------------------------------------

void loadBackground(Prepared &p, const Page &page) {
  storage::FileInfo f;
  bool hasFile = !page.bgFile.empty() && storage::info(page.bgFile, f);
  std::string key = hasFile ? page.bgFile + ":" + f.crc : "#" + std::to_string(page.bgColor);
  if (key == p.bgKey) return;
  if (hasFile && f.format == "jpeg") {
    auto data = storage::read(page.bgFile);
    if (data && compositor::decodeJpeg(*data, p.bg)) {
      p.bgKey = key;
      return;
    }
    pclink::log("background %s: cannot decode", page.bgFile.c_str());
  }
  // GIF and video backgrounds come with steps 6c and 6d; until then, the fallback colour.
  compositor::fill(p.bg, page.bgColor);
  p.bgKey = "#" + std::to_string(page.bgColor);
}

Prepared &prepare(const Page &page) {
  Prepared *slot = nullptr;
  for (auto &s : slots) {
    if (s.id == page.id) slot = &s;
  }
  if (!slot) {
    slot = &slots[0];
    for (auto &s : slots) {
      if (s.used < slot->used) slot = &s;
    }
    slot->id = page.id;
    slot->bgKey = slot->flatKey = "";
  }
  slot->used = ++useClock;
  loadBackground(*slot, page);
  auto it = overlays.find(page.id);
  std::string key = slot->bgKey + "|" + (it != overlays.end() ? it->second.crc : "");
  if (key != slot->flatKey) {
    compositor::Layer layer;
    layer.bg = slot->bg;
    if (it != overlays.end()) {
      if (compositor::inflate(it->second.data->data(), it->second.data->size(), scratchOv)) {
        layer.overlay = scratchOv;
      } else {
        pclink::log("overlay %s: cannot unpack", page.id.c_str());
      }
    }
    compositor::flatten(layer, slot->flat);
    slot->flatKey = key;
  }
  return *slot;
}

bool isPrepared(const Page &page) {
  for (auto &s : slots) {
    if (s.id == page.id) return true;
  }
  return false;
}

// --- Pagination ------------------------------------------------------------------------------

int addDots(Sprite *out, int n) {
  int count = pages.size();
  if (count <= 1) return n;
  if (count > kMaxDots) {
    char text[16];
    snprintf(text, sizeof(text), "%u/%d", (unsigned)current + 1, count);
    float width = 0;
    for (const char *c = text; *c; ++c) {
      for (auto &g : kGlyphs) width += g.c == *c ? g.advance : 0;
    }
    float x = (kLandscapeW - width) / 2;
    for (const char *c = text; *c; ++c) {
      for (auto &g : kGlyphs) {
        if (g.c != *c) continue;
        out[n++] = Sprite{g.sprite, (int)lroundf(x), kCounterTop};
        x += g.advance;
      }
    }
    return n;
  }
  int x0 = kLandscapeW / 2 - kDotGap * (count - 1) / 2;
  for (int i = 0; i < count; ++i) {
    out[n++] = Sprite{i == (int)current ? kDotOn : kDotOff, x0 + i * kDotGap - kDotSprite / 2, kDotsY - kDotSprite / 2};
  }
  return n;
}

// --- Touch ---------------------------------------------------------------------------------

void sendEvent(const char *type, const std::string &action) {
  JsonDocument doc;
  doc["type"] = type;
  doc["page"] = pages.empty() ? "" : pages[current].id;
  if (!action.empty()) doc["action"] = action;
  std::string s;
  serializeJson(doc, s);
  pclink::sendEvent(s);
}

void handle(const gestures::Result &r, uint32_t now) {
  switch (r.kind) {
    case gestures::Result::Tap:
      sendEvent("tap", r.action);
      break;
    case gestures::Result::Reset:
      sendEvent("reset", r.action);
      break;
    case gestures::Result::Page: {
      slide.on = true;
      slide.from = current;
      slide.forward = r.step > 0;
      slide.start = now;
      slide.frames = 0;
      slide.pushUs = 0;
      current = (current + pages.size() + r.step) % pages.size();
      {
        State::Lock l;
        if (state.pages.size() == pages.size()) state.current = current;
      }
      sendEvent("page", "");
      break;
    }
    case gestures::Result::None:
      break;
  }
}

const Zone *zoneAt(float x, float y) {
  if (pages.empty()) return nullptr;
  for (auto &z : pages[current].zones) {
    if (z.contains(x, y)) return &z;
  }
  return nullptr;
}

void readTouch(uint32_t now) {
  touch::Point p = touch::read();
  if (p.down) {
    lastTouchMs = now;
    lastX = p.y;  // the panel turned: landscape x = panel y, landscape y = 319 − panel x
    lastY = kLandscapeH - 1 - p.x;
    if (!tracker.touching()) {
      tracker.down(lastX, lastY, now, zoneAt(lastX, lastY));
    } else {
      tracker.move(lastX, lastY);
    }
  } else if (tracker.touching() && now - lastTouchMs >= kLiftMs) {
    handle(tracker.up(lastX, lastY, lastTouchMs, pages.size()), now);
  }
  handle(tracker.tick(now), now);
}

// --- Offline -------------------------------------------------------------------------------

void showOffline(Mode mode) {
  bool waiting = mode == Mode::Waiting;
  std::string key = waiting ? "waiting" : "disconnected";
  if (offlineKey != key) {
    const uint8_t *z = waiting ? waiting_start : disconnected_start;
    size_t n = waiting ? waiting_end - waiting_start : disconnected_end - disconnected_start;
    offlineKey = compositor::inflate(z, n, offlineOv) ? key : "";
  }
  compositor::Layer layer;
  layer.bg = offlineBg;
  layer.overlay = offlineKey == key ? offlineOv : nullptr;
  compositor::push(layer);
  display::backlight(kDim);
}

// --- Frame ---------------------------------------------------------------------------------

void showPage(uint32_t now) {
  Scene scene;
  float t = slide.on ? fminf(1, (float)(now - slide.start) / kSlideMs) : 1;
  if (slide.on && t >= 1) {
    pclink::log("slide: %d frames in %u ms, %u ms a frame pushing", slide.frames, (unsigned)(now - slide.start),
                (unsigned)(slide.frames ? slide.pushUs / slide.frames / 1000 : 0));
    slide.on = false;
  }
  if (slide.on) ++slide.frames;
  Prepared &cur = prepare(pages[current]);
  if (slide.on && slide.from < pages.size()) {
    // The page sliding out is the scene's page; the current one comes in.
    float eased = 1 - powf(1 - t, 3);
    Prepared &old = prepare(pages[slide.from]);
    scene.page = old.flat;
    scene.incoming = cur.flat;
    scene.shift = (int)(kLandscapeW * eased);
    scene.forward = slide.forward;
  } else {
    slide.on = false;
    scene.page = cur.flat;
  }
  // Over the pages: the reset banner while holding (its bar filling), else the toast.
  float progress;
  std::string action;
  holdShown = tracker.hold(now, progress, action);
  std::string topId = holdShown ? kHoldOverlay + action : toastId;
  auto it = topId.empty() ? overlays.end() : overlays.find(topId);
  if (it != overlays.end()) {
    std::string key = topId + ":" + it->second.crc;
    if (topKey != key) {
      topKey = compositor::inflate(it->second.data->data(), it->second.data->size(), topRaw) ? key : "";
    }
    if (topKey == key) scene.top = topRaw;
  }
  if (holdShown) {
    scene.barX = kHoldBarX;
    scene.barY = kHoldBarY;
    scene.barW = (int)(kHoldBarW * progress);
    scene.barH = kHoldBarH;
    scene.barColor = kGold;
  }
  Sprite sprites[kMaxDots];
  scene.sprites = sprites;
  scene.spriteCount = addDots(sprites, 0);
  uint32_t t0 = micros();
  compositor::push(scene);
  if (slide.on) slide.pushUs += micros() - t0;
  display::backlight(kFull);
}

}  // namespace

void begin() {
  for (auto &s : slots) {
    s.bg = static_cast<uint16_t *>(heap_caps_malloc(compositor::kPixels * 2, MALLOC_CAP_SPIRAM));
    s.flat = static_cast<uint16_t *>(heap_caps_malloc(compositor::kPixels * 2, MALLOC_CAP_SPIRAM));
  }
  scratchOv = compositor::allocOverlay();
  offlineBg = static_cast<uint16_t *>(heap_caps_malloc(compositor::kPixels * 2, MALLOC_CAP_SPIRAM));
  compositor::fill(offlineBg, 0);
  offlineOv = compositor::allocOverlay();
  topRaw = compositor::allocOverlay();
  touch::begin();
  tick();
}

void tick() {
  uint32_t now = millis();
  bool online, everHeard;
  {
    State::Lock l;
    if (!state.toast.empty() && (int32_t)(now - state.toastUntilMs) >= 0) {
      state.toast.clear();  // its overlay stays, like the simulator's
      ++state.version;
    }
    online = state.online(now);
    everHeard = state.everHeard;
    if (state.version != seenVersion) {
      seenVersion = state.version;
      pages = state.pages;
      overlays = state.overlays;
      current = state.current < pages.size() ? state.current : 0;
      toastId = state.toast;
      if (slide.from >= pages.size()) slide.on = false;
      dirty = true;
    }
  }
  Mode mode = online && !pages.empty() ? Mode::Page : everHeard ? Mode::Disconnected : Mode::Waiting;
  if (mode != Mode::Page) {
    tracker = gestures::Tracker();  // a finger on the offline screen does nothing
    if (mode != shown) showOffline(mode);
    shown = mode;
    return;
  }
  readTouch(now);
  float progress;
  std::string action;
  bool holding = tracker.hold(now, progress, action);
  if (dirty || shown != Mode::Page || slide.on || holding || holdShown) {
    showPage(now);
    shown = Mode::Page;
    dirty = false;
    return;
  }
  // Nothing to draw: get the neighbours ready for a swipe, one per tick.
  if (!tracker.touching() && pages.size() > 1) {
    const Page &next = pages[(current + 1) % pages.size()];
    const Page &prev = pages[(current + pages.size() - 1) % pages.size()];
    if (!isPrepared(next)) {
      prepare(next);
    } else if (!isPrepared(prev)) {
      prepare(prev);
    }
  }
}

}  // namespace screen
