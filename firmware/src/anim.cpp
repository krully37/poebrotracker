#include "anim.h"

#include <Arduino.h>
#include <esp_heap_caps.h>

#include <map>
#include <memory>

#include "compositor.h"
#include "gifplayer.h"
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

GifPlayer *player;
uint16_t *canvas_;
uint8_t *mask_;
bool seeThrough_ = false;
bool fresh = false;  // a still image (or black) waiting to be drawn once

bool isAnimation(const std::string &id) { return id == "boot" || id.rfind("anim-", 0) == 0; }

std::shared_ptr<std::vector<uint8_t>> load(const std::string &id) {
  auto it = cache.find(id);
  storage::FileInfo f;
  if (it != cache.end() && storage::info(id, f) && f.crc == it->second.crc) return it->second.data;
  return storage::read(id);
}

}  // namespace

void begin() {
  canvas_ = static_cast<uint16_t *>(heap_caps_malloc(compositor::kPixels * 2, MALLOC_CAP_SPIRAM));
  mask_ = static_cast<uint8_t *>(heap_caps_malloc(compositor::kPixels, MALLOC_CAP_SPIRAM));
  player = new GifPlayer();
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
  uint32_t ms = bytes ? GifPlayer::length(*bytes) : 0;
  return ms ? min(kMaxBoot, max(kMinBoot, ms)) : kStill;
}

void start(const std::string &file, bool seeThrough) {
  player->close();
  seeThrough_ = seeThrough;
  compositor::fill(canvas_, 0);
  storage::FileInfo f;
  auto data = file.empty() || !storage::info(file, f) ? nullptr : load(file);
  if (data && f.format == "gif") {
    if (!player->open(data, canvas_, seeThrough ? mask_ : nullptr)) pclink::log("animation %s: cannot open", file.c_str());
  } else if (data && !compositor::decodeJpeg(*data, canvas_)) {
    pclink::log("animation %s: cannot decode", file.c_str());
  }
  if (seeThrough && !player->isOpen()) memset(mask_, 0, compositor::kPixels);
  fresh = true;
}

bool advance(uint32_t now) {
  if (player->isOpen()) {
    fresh = false;
    return player->advance(now);
  }
  bool draw = fresh;  // a still image, or black: drawn once
  fresh = false;
  return draw;
}

const uint16_t *canvas() { return canvas_; }

const uint8_t *mask() { return seeThrough_ ? mask_ : nullptr; }

}  // namespace anim
