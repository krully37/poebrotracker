#include "screen.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <esp_heap_caps.h>
#include <math.h>

#include "anim.h"
#include "compositor.h"
#include "decor_sprites.h"
#include "display.h"
#include "gestures.h"
#include "idlecat.h"
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
constexpr int kUnderAnimation = 40;  // % brightness of the page under an over-the-page animation
constexpr uint32_t kSlideMs = 280;
constexpr int kMaxDots = 8;
constexpr int kDotGap = 14;
constexpr int kDotsY = 311;
constexpr uint16_t kGold = compositor::rgb565(kGoldR, kGoldG, kGoldB);
// The touch controller reports no finger now and then while one is down: only this long without
// one counts as lifting it.
constexpr uint32_t kLiftMs = 60;

enum class Mode { None, Waiting, Disconnected, Page, Animation, Idle };

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
uint8_t *topRaw;  // the toast, the reset banner or the event's text, unpacked
uint16_t *dimmed;  // the page under an over-the-page animation, panel order
std::string offlineKey, topKey;

// The PC's latest word, copied from `state` when its version changes.
uint32_t seenVersion = ~0u;
std::vector<Page> pages;
std::map<std::string, Overlay> overlays;
size_t current = 0;
std::string toastId;
bool playing = false;
Play play;
uint32_t playStarted = ~0u;  // play.startMs of the animation on screen
std::string idleSprite;
uint32_t idleSerial = 0, idleStarted = ~0u, idleFrameMs = 0;
bool waking = false;  // a finger came down on the idle cat

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

// Loads one event animation into PSRAM when there is one to load; looks twice a second at most.
void preloadSoon(uint32_t now) {
  static uint32_t last = 0;
  if (now - last < 500) return;
  last = now;
  anim::preloadOne();
}

// --- Frame ---------------------------------------------------------------------------------

void stopIdle(const char *why) {
  State::Lock l;
  state.idleSprite.clear();
  ++state.version;
  if (why) pclink::log("idle cat: %s", why);
}

// The idle cat bouncing on black. Any touch brings the pages back, then EVENT wake on release.
void showIdle(uint32_t now) {
  if (idleSerial != idleStarted) {
    idleStarted = idleSerial;
    if (!idlecat::start(idleSprite)) return stopIdle("cannot load the sprite");
    idleFrameMs = now - idlecat::kFrameMs;
  }
  touch::Point p = touch::read();
  if (p.down) {
    waking = true;
    lastTouchMs = now;
  } else if (waking && now - lastTouchMs >= kLiftMs) {
    waking = false;
    stopIdle(nullptr);
    sendEvent("wake", "");
    return;
  }
  shown = Mode::Idle;
  if (now - idleFrameMs < idlecat::kFrameMs) return;
  idleFrameMs = now;
  idlecat::step(now);
  Sprite cat = idlecat::sprite();
  Scene scene;
  scene.page = offlineBg;  // black, in either order
  scene.sprites = &cat;
  scene.spriteCount = 1;
  compositor::push(scene);
  display::backlight(kFull);
}

// The overlay with this id unpacked into topRaw, or nullptr.
const uint8_t *topOverlay(const std::string &id) {
  auto it = id.empty() ? overlays.end() : overlays.find(id);
  if (it == overlays.end()) return nullptr;
  std::string key = id + ":" + it->second.crc;
  if (topKey != key) topKey = compositor::inflate(it->second.data->data(), it->second.data->size(), topRaw) ? key : "";
  return topKey == key ? topRaw : nullptr;
}

Scene pageScene(Sprite *sprites) {
  Scene scene;
  scene.page = prepare(pages[current]).flat;
  scene.sprites = sprites;
  scene.spriteCount = addDots(sprites, 0);
  return scene;
}

void showAnimation(uint32_t now, bool online) {
  bool overPage = play.overPage && online && !pages.empty();
  if (play.startMs != playStarted) {
    playStarted = play.startMs;
    if (overPage) {  // the page as it was, dots included, dimmed; it shows where the GIF is see-through
      Sprite sprites[kMaxDots];
      compositor::render(pageScene(sprites), dimmed);
      compositor::dim(dimmed, kUnderAnimation);
    }
    anim::start(play.file, overPage);
  }
  if (!anim::advance(now)) return;
  const uint8_t *top = topOverlay(play.overlay);
  if (overPage) {
    compositor::OverPage frame{anim::canvas(), anim::mask(), dimmed, top};
    compositor::push(frame);
  } else {
    compositor::Layer layer;
    layer.bg = anim::canvas();
    layer.overlay = top;
    compositor::push(layer);
  }
  display::backlight(online || play.file == "boot" ? kFull : kDim);
}

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
  scene.top = topOverlay(topId);
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
  dimmed = static_cast<uint16_t *>(heap_caps_malloc(compositor::kPixels * 2, MALLOC_CAP_SPIRAM));
  anim::begin();
  touch::begin();
  // The start animation, from flash, before the PC is there (docs/PROTOCOL.md, "Boot").
  uint32_t length = anim::bootLength("boot");
  if (length) {
    State::Lock l;
    uint32_t now = millis();
    state.play = Play{"boot", "", now, now + length, false};
    state.playing = true;
    ++state.version;
  }
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
    if (state.playing && (int32_t)(now - state.play.untilMs) >= 0) {
      state.playing = false;
      ++state.version;
    }
    if (!state.idleSprite.empty() && !state.online(now)) {
      state.idleSprite.clear();  // the PC went away: the offline screen, as always
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
      playing = state.playing;
      play = state.play;
      idleSprite = state.idleSprite;
      idleSerial = state.idleSerial;
      if (slide.from >= pages.size()) slide.on = false;
      dirty = true;
    }
  }
  if (playing) {
    // Touch still works under an animation, like the simulator: a swipe changes the page beneath.
    if (online && !pages.empty()) readTouch(now);
    showAnimation(now, online);
    shown = Mode::Animation;
    return;
  }
  if (shown == Mode::Animation) {
    shown = Mode::None;  // the animation ended: draw what is underneath again
    playStarted = ~0u;
  }
  if (online && !idleSprite.empty()) {
    showIdle(now);
    return;
  }
  if (shown == Mode::Idle) {
    shown = Mode::None;
    idleStarted = ~0u;
    tracker = gestures::Tracker();
  }
  Mode mode = online && !pages.empty() ? Mode::Page : everHeard ? Mode::Disconnected : Mode::Waiting;
  if (mode != Mode::Page) {
    tracker = gestures::Tracker();  // a finger on the offline screen does nothing
    if (mode != shown) showOffline(mode);
    shown = mode;
    preloadSoon(now);
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
      return;
    }
    if (!isPrepared(prev)) {
      prepare(prev);
      return;
    }
  }
  if (!tracker.touching()) preloadSoon(now);
}

}  // namespace screen
