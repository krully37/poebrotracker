#include "anim.h"

#include <AnimatedGIF.h>
#include <Arduino.h>
#include <esp_heap_caps.h>

#include <map>
#include <memory>

#include "compositor.h"
#include "pclink.h"
#include "storage.h"

namespace anim {
namespace {

constexpr uint32_t kMinBoot = 3000, kMaxBoot = 10000, kStill = 4000;
constexpr size_t kKeepFree = 1024 * 1024;  // PSRAM left for everything else when preloading

struct Cached {
  std::string crc;
  std::shared_ptr<std::vector<uint8_t>> data;
};
std::map<std::string, Cached> cache;

AnimatedGIF gif;  // large: never on the stack
uint16_t *canvas_;
uint8_t *mask_;
bool seeThrough_ = false;

// The file playing.
std::shared_ptr<std::vector<uint8_t>> data;
bool isGif = false, gifOpen = false, fresh = false;
uint32_t dueMs = 0;
// What the last frame drew, for disposal 2 ("restore to background") before the next one.
int lastX = 0, lastY = 0, lastW = 0, lastH = 0, lastDisposal = 0;

bool isAnimation(const std::string &id) { return id == "boot" || id.rfind("anim-", 0) == 0; }

std::shared_ptr<std::vector<uint8_t>> load(const std::string &id) {
  auto it = cache.find(id);
  storage::FileInfo f;
  if (it != cache.end() && storage::info(id, f) && f.crc == it->second.crc) return it->second.data;
  return storage::read(id);
}

void draw(GIFDRAW *d) {
  int y = d->iY + d->y;
  if (y < 0 || y >= kLandscapeH) return;
  lastX = d->iX;
  lastY = d->iY;
  lastW = d->iWidth;
  lastH = d->iHeight;
  lastDisposal = d->ucDisposalMethod;
  int w = min(d->iWidth, kLandscapeW - d->iX);
  uint16_t *line = canvas_ + y * kLandscapeW + d->iX;
  uint8_t *m = seeThrough_ ? mask_ + y * kLandscapeW + d->iX : nullptr;
  const uint8_t *src = d->pPixels;
  const uint16_t *pal = d->pPalette;
  bool see = d->ucHasTransparency;
  uint8_t t = d->ucTransparent;
  for (int x = 0; x < w; ++x) {
    if (see && src[x] == t) continue;  // unchanged (a delta frame) or see-through (over the page)
    line[x] = pal[src[x]];
    if (m) m[x] = 1;
  }
}

void clearLast() {
  for (int y = max(0, lastY); y < min(kLandscapeH, lastY + lastH); ++y) {
    int x0 = max(0, lastX), x1 = min(kLandscapeW, lastX + lastW);
    if (x1 <= x0) continue;
    memset(canvas_ + y * kLandscapeW + x0, 0, (x1 - x0) * 2);
    if (seeThrough_) memset(mask_ + y * kLandscapeW + x0, 0, x1 - x0);
  }
}

void closeGif() {
  if (gifOpen) gif.close();
  gifOpen = false;
}

}  // namespace

void begin() {
  canvas_ = static_cast<uint16_t *>(heap_caps_malloc(compositor::kPixels * 2, MALLOC_CAP_SPIRAM));
  mask_ = static_cast<uint8_t *>(heap_caps_malloc(compositor::kPixels, MALLOC_CAP_SPIRAM));
  gif.begin(GIF_PALETTE_RGB565_LE);
}

bool preloadOne() {
  auto files = storage::list();
  for (auto it = cache.begin(); it != cache.end();) {
    auto f = files.find(it->first);
    it = (f == files.end() || f->second.crc != it->second.crc) ? cache.erase(it) : std::next(it);
  }
  for (auto &[id, f] : files) {
    if (!isAnimation(id) || cache.count(id)) continue;
    if (heap_caps_get_free_size(MALLOC_CAP_SPIRAM) < f.size + kKeepFree) continue;
    auto data = storage::read(id);
    if (data) cache[id] = Cached{f.crc, data};
    return true;
  }
  return false;
}

uint32_t bootLength(const std::string &file) {
  storage::FileInfo f;
  if (!storage::info(file, f)) return 0;
  if (f.format != "gif") return kStill;
  auto bytes = load(file);
  GIFINFO info = {};
  if (!bytes || !gif.open(bytes->data(), bytes->size(), draw)) return kStill;
  gif.getInfo(&info);
  gif.close();
  return min(kMaxBoot, max(kMinBoot, (uint32_t)info.iDuration));
}

void start(const std::string &file, bool seeThrough) {
  closeGif();
  seeThrough_ = seeThrough;
  compositor::fill(canvas_, 0);
  if (seeThrough) memset(mask_, 0, compositor::kPixels);
  lastW = lastH = lastDisposal = 0;
  storage::FileInfo f;
  data = file.empty() || !storage::info(file, f) ? nullptr : load(file);
  isGif = data && f.format == "gif";
  if (data && !isGif && !compositor::decodeJpeg(*data, canvas_)) {
    pclink::log("animation %s: cannot decode", file.c_str());
  }
  if (isGif) {
    gifOpen = gif.open(data->data(), data->size(), draw);
    if (!gifOpen) pclink::log("animation %s: cannot open (%d)", file.c_str(), gif.getLastError());
  }
  fresh = true;
  dueMs = millis();
}

bool advance(uint32_t now) {
  if (fresh) {
    fresh = false;
    if (!gifOpen) return true;  // a still image, or black: drawn once
  }
  if (!gifOpen || (int32_t)(now - dueMs) < 0) return false;
  if (lastDisposal == 2) clearLast();
  int delay = 100;
  int more = gif.playFrame(false, &delay);
  if (more < 0) {
    closeGif();
    return false;
  }
  if (more == 0) gif.reset();  // that was the last frame: loop
  // Late frames show at once: the animation slows down rather than skipping (docs/SCOPE.md §8b).
  dueMs = now + max(20, delay);
  return true;
}

const uint16_t *canvas() { return canvas_; }

const uint8_t *mask() { return seeThrough_ ? mask_ : nullptr; }

}  // namespace anim
