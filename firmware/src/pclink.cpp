#include "pclink.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <miniz.h>

#include <map>

#include "firmware.h"
#include "protocol.h"
#include "state.h"
#include "storage.h"
#include "usblink.h"

namespace pclink {
namespace {

constexpr size_t kMaxOverlay = 1024 * 1024;  // compressed; real pages are 15–25 kB
constexpr size_t kFlashMargin = 16 * 1024;    // LittleFS needs a few blocks of its own

struct Xfer {
  std::string kind, id, crc, format;
  uint32_t size = 0;
  float seconds = 2;
  std::shared_ptr<std::vector<uint8_t>> buf;  // overlay and toast
  std::unique_ptr<storage::Writer> file;      // file
  uint32_t have() const { return buf ? buf->size() : file->written(); }
};

std::map<uint16_t, Xfer> xfers;

struct LastReply {
  bool valid = false;
  uint8_t type = 0;
  uint16_t seq = 0;
  std::vector<uint8_t> raw;
} lastReply;

QueueHandle_t outbox;  // std::string* from other tasks: events and logs, already framed

struct Pending {
  std::vector<uint8_t> raw;
  uint32_t sentMs;
  int tries;
};
std::map<uint16_t, Pending> pending;  // events waiting for EVENT_ACK
uint16_t eventSeq = 0;

void write(const std::vector<uint8_t> &raw) { usb.write(raw.data(), raw.size()); }

std::vector<uint8_t> jsonFrame(uint8_t type, uint16_t seq, const JsonDocument &doc) {
  std::string s;
  serializeJson(doc, s);
  return proto::encodeFrame(type, seq, (const uint8_t *)s.data(), s.size());
}

void error(JsonDocument &r, const char *what) {
  r["ok"] = false;
  r["error"] = what;
}

uint16_t parseColor(const char *hex) {
  if (!hex || hex[0] != '#' || strlen(hex) != 7) return 0;
  uint32_t v = strtoul(hex + 1, nullptr, 16);
  uint8_t r = v >> 16, g = v >> 8, b = v;
  return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
}

// "OV1" | 480 | 320 at the start of the zlib stream, without unpacking the rest.
bool looksLikeOverlay(const std::vector<uint8_t> &z) {
  static tinfl_decompressor inflator;
  tinfl_init(&inflator);
  uint8_t head[7];
  size_t in = z.size(), out = sizeof(head);
  tinfl_status st = tinfl_decompress(&inflator, z.data(), &in, head, head, &out,
                                     TINFL_FLAG_PARSE_ZLIB_HEADER | TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF |
                                         TINFL_FLAG_HAS_MORE_INPUT);
  return st >= TINFL_STATUS_DONE && out == sizeof(head) && memcmp(head, "OV1", 3) == 0 &&
         (head[3] | head[4] << 8) == kLandscapeW && (head[5] | head[6] << 8) == kLandscapeH;
}

void inventory(JsonDocument &r) {
  r["ok"] = true;
  r["version"] = proto::kVersion;
  r["firmware"] = kFirmwareVersion;
  r["width"] = kLandscapeW;
  r["height"] = kLandscapeH;
  r["flash_total"] = storage::totalBytes();
  r["flash_free"] = storage::freeBytes();
  JsonObject ov = r["overlays"].to<JsonObject>();
  {
    State::Lock l;
    for (auto &[id, o] : state.overlays) ov[id] = o.crc;
    if (state.playing && (int32_t)(state.play.untilMs - millis()) > 0) {
      r["playing"] = state.play.file;
    } else {
      r["playing"] = nullptr;
    }
  }
  JsonObject fs = r["files"].to<JsonObject>();
  for (auto &[id, f] : storage::list()) {
    JsonObject o = fs[id].to<JsonObject>();
    o["crc"] = f.crc;
    o["size"] = f.size;
    o["format"] = f.format;
  }
}

void setPages(JsonArrayConst list, JsonDocument &r) {
  std::vector<Page> pages;
  for (JsonObjectConst pg : list) {
    const char *id = pg["id"];
    if (!id || !*id) continue;
    Page p;
    p.id = id;
    JsonObjectConst bg = pg["bg"];
    p.bgColor = parseColor(bg["color"] | "#000000");
    p.bgFile = bg["file"] | "";
    for (JsonObjectConst z : pg["zones"].as<JsonArrayConst>()) {
      Zone zone;
      zone.x = z["x"] | 0;
      zone.y = z["y"] | 0;
      zone.w = z["w"] | 0;
      zone.h = z["h"] | 0;
      zone.action = z["action"] | "";
      zone.tap = strcmp(z["gesture"] | "hold", "tap") == 0;
      p.zones.push_back(zone);
    }
    pages.push_back(std::move(p));
  }
  State::Lock l;
  std::string currentId = state.pages.empty() ? "" : state.pages[state.current].id;
  state.pages = std::move(pages);
  for (auto it = state.overlays.begin(); it != state.overlays.end();) {
    bool keep = it->first[0] == '@';
    for (auto &p : state.pages) keep = keep || p.id == it->first;
    it = keep ? std::next(it) : state.overlays.erase(it);
  }
  state.current = 0;
  for (size_t i = 0; i < state.pages.size(); ++i) {
    if (state.pages[i].id == currentId) state.current = i;
  }
  ++state.version;
  r["ok"] = true;
}

void begin(uint16_t xferId, JsonObjectConst msg, JsonDocument &r) {
  std::string kind = msg["kind"] | "";
  uint32_t size = msg["size"] | 0u;
  Xfer x;
  x.kind = kind;
  x.id = msg["id"] | "";
  x.crc = msg["crc"] | "";
  x.format = msg["format"] | "jpeg";
  x.size = size;
  x.seconds = msg["seconds"] | 2.0f;
  if (kind == "file") {
    storage::FileInfo old;
    size_t replaced = storage::info(x.id, old) ? old.size : 0;
    size_t room = storage::freeBytes() + replaced;
    room = room > kFlashMargin ? room - kFlashMargin : 0;
    if (size > room) {
      error(r, "no_space");
      r["flash_free"] = storage::freeBytes();
      return;
    }
    x.file.reset(new storage::Writer());
    if (!x.file->open(xferId, x.id, size, x.crc, x.format)) return error(r, "flash");
  } else if (kind == "overlay" || kind == "toast") {
    if (size > kMaxOverlay) return error(r, "too_big");
    x.buf = std::make_shared<std::vector<uint8_t>>();
    x.buf->reserve(size);
  } else {
    return error(r, "kind");
  }
  xfers[xferId] = std::move(x);
  r["ok"] = true;
}

void chunk(const proto::Frame &f, JsonDocument &r) {
  uint16_t id;
  uint32_t offset;
  const uint8_t *data;
  size_t len;
  if (!proto::parseChunk(f.payload, id, offset, data, len)) return error(r, "short chunk");
  auto it = xfers.find(id);
  if (it == xfers.end()) return error(r, "xfer");
  Xfer &x = it->second;
  if (offset != x.have()) {
    error(r, "offset");
    r["have"] = x.have();
    return;
  }
  if (offset + len > x.size) return error(r, "too_long");
  if (x.buf) {
    x.buf->insert(x.buf->end(), data, data + len);
  } else if (!x.file->append(data, len)) {
    return error(r, "flash");
  }
  r["ok"] = true;
}

void end(uint16_t id, JsonDocument &r) {
  auto it = xfers.find(id);
  if (it == xfers.end()) return error(r, "xfer");
  Xfer x = std::move(it->second);
  xfers.erase(it);
  if (x.file) {
    if (!x.file->finish()) return error(r, "crc");
    r["ok"] = true;
    r["flash_free"] = storage::freeBytes();
    State::Lock l;
    if (state.idleSprite == x.id) ++state.idleSerial;  // a new cat under the same id
    ++state.version;  // a background may have arrived
    return;
  }
  char hex[9];
  snprintf(hex, sizeof(hex), "%08x", (unsigned)proto::crc32(x.buf->data(), x.buf->size()));
  if (x.buf->size() != x.size || x.crc != hex) return error(r, "crc");
  if (!looksLikeOverlay(*x.buf)) return error(r, "not an overlay");
  State::Lock l;
  state.overlays[x.id] = Overlay{x.crc, x.buf};
  if (x.kind == "toast") {
    state.toast = x.id;
    state.toastUntilMs = millis() + (uint32_t)(x.seconds * 1000);
  }
  ++state.version;
  r["ok"] = true;
}

void apply(const proto::Frame &f, JsonDocument &r) {
  if (f.type == proto::kChunk) return chunk(f, r);
  JsonDocument msg;
  if (!f.payload.empty() && deserializeJson(msg, f.payload.data(), f.payload.size())) return error(r, "bad json");
  switch (f.type) {
    case proto::kHello: {
      xfers.clear();  // half-finished transfers are dropped (their temp files with them)
      State::Lock l;
      state.idleSprite.clear();  // a new connection starts on the pages
      ++state.version;
      return inventory(r);
    }
    case proto::kPing:
      r["ok"] = true;
      return;
    case proto::kPages:
      return setPages(msg["pages"].as<JsonArrayConst>(), r);
    case proto::kBegin:
      return begin(msg["xfer"] | 0, msg.as<JsonObjectConst>(), r);
    case proto::kEnd:
      return end(msg["xfer"] | 0, r);
    case proto::kDelete: {
      std::string id = msg["id"] | "";
      storage::remove(id);
      r["ok"] = true;
      r["flash_free"] = storage::freeBytes();
      State::Lock l;
      if (state.idleSprite == id) state.idleSprite.clear();
      ++state.version;
      return;
    }
    case proto::kIdle: {
      std::string id = msg["sprite"] | "";
      storage::FileInfo f;
      if (!id.empty() && (!storage::info(id, f) || f.format != "sprite")) return error(r, "no_file");
      State::Lock l;
      if (state.idleSprite != id) {  // the same sprite again: it carries on from where it is
        state.idleSprite = id;
        ++state.idleSerial;
      }
      ++state.version;
      r["ok"] = true;
      return;
    }
    case proto::kPlay: {
      State::Lock l;
      uint32_t now = millis();
      state.play = Play{msg["file"] | "", msg["overlay"] | "", now, now + (uint32_t)((msg["seconds"] | 4.0f) * 1000),
                        msg["over_page"] | false};
      state.playing = true;
      ++state.version;
      r["ok"] = true;
      return;
    }
    default:
      return error(r, "unknown_type");
  }
}

void handle(const proto::Frame &f) {
  {
    State::Lock l;
    if (!state.everHeard || !state.online(millis())) ++state.version;  // back from offline
    state.everHeard = true;
    state.lastRxMs = millis();
  }
  if (f.type == proto::kEventAck) {
    pending.erase(f.seq);
    return;
  }
  if (lastReply.valid && lastReply.type == f.type && lastReply.seq == f.seq) {
    write(lastReply.raw);  // the PC missed our ACK: the same answer again
    return;
  }
  JsonDocument r;
  apply(f, r);
  lastReply.raw = jsonFrame(proto::kAck, f.seq, r);
  lastReply.type = f.type;
  lastReply.seq = f.seq;
  lastReply.valid = true;
  write(lastReply.raw);
}

void service() {
  uint32_t now = millis();
  bool online;
  {
    State::Lock l;
    online = state.online(now);
  }
  std::string *msg;
  while (xQueueReceive(outbox, &msg, 0)) {
    if (msg->compare(0, 2, "E:") == 0) {
      // Offline: dropped. Nobody is there to answer a tap or a reset.
      if (online) {
        eventSeq++;
        auto raw = proto::encodeFrame(proto::kEvent, eventSeq, (const uint8_t *)msg->data() + 2, msg->size() - 2);
        pending[eventSeq] = Pending{raw, now, 1};
        write(raw);
      }
    } else {
      write(proto::encodeFrame(proto::kLog, 0, (const uint8_t *)msg->data() + 2, msg->size() - 2));
    }
    delete msg;
  }
  for (auto it = pending.begin(); it != pending.end();) {
    Pending &p = it->second;
    if (now - p.sentMs >= proto::kAckTimeoutMs) {
      if (p.tries >= proto::kRetries || !online) {
        it = pending.erase(it);
        continue;
      }
      p.sentMs = now;
      p.tries++;
      write(p.raw);
    }
    ++it;
  }
}

void task(void *) {
  usb.beginWaiting();
  proto::FrameReader reader;
  proto::Frame frame;
  static uint8_t buf[512];
  for (;;) {
    size_t n = usb.read(buf, sizeof(buf));
    for (size_t i = 0; i < n; ++i) {
      if (reader.push(buf[i], frame)) handle(frame);
    }
    service();
    if (!n) usb.waitForData(20);
  }
}

void enqueue(std::string *msg) {
  if (!outbox || xQueueSend(outbox, &msg, 0) != pdTRUE) delete msg;
}

}  // namespace

void start() {
  outbox = xQueueCreate(32, sizeof(std::string *));
  xTaskCreatePinnedToCore(task, "link", 16384, nullptr, 5, nullptr, 0);
}

void sendEvent(const std::string &json) { enqueue(new std::string("E:" + json)); }

void log(const char *fmt, ...) {
  char text[200];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(text, sizeof(text), fmt, ap);
  va_end(ap);
  JsonDocument doc;
  doc["text"] = text;
  std::string json;
  serializeJson(doc, json);  // replaces the string's content, so not straight into "L:"
  enqueue(new std::string("L:" + json));
}

}  // namespace pclink
