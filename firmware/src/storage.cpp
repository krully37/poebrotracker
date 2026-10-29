#include "storage.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <LittleFS.h>

#include "protocol.h"

namespace storage {
namespace {

constexpr const char *kIndex = "/index.json";
constexpr const char *kIndexTmp = "/index.tmp";

SemaphoreHandle_t lock;
std::map<std::string, FileInfo> files;  // the index, kept in RAM

struct Lock {
  Lock() { xSemaphoreTakeRecursive(lock, portMAX_DELAY); }
  ~Lock() { xSemaphoreGiveRecursive(lock); }
};

std::string path(const std::string &id) { return "/f/" + id; }

void saveIndex() {
  JsonDocument doc;
  for (auto &[id, f] : files) {
    JsonObject o = doc[id].to<JsonObject>();
    o["crc"] = f.crc;
    o["size"] = f.size;
    o["format"] = f.format;
  }
  File out = LittleFS.open(kIndexTmp, "w");
  serializeJson(doc, out);
  out.close();
  LittleFS.rename(kIndexTmp, kIndex);  // atomic in LittleFS
}

void loadIndex() {
  files.clear();
  File in = LittleFS.open(kIndex, "r");
  if (!in) return;
  JsonDocument doc;
  if (deserializeJson(doc, in)) return;
  for (JsonPairConst kv : doc.as<JsonObjectConst>()) {
    FileInfo f;
    f.crc = kv.value()["crc"] | "";
    f.size = kv.value()["size"] | 0;
    f.format = kv.value()["format"] | "jpeg";
    File data = LittleFS.open(path(kv.key().c_str()).c_str(), "r");
    // A file cut short by a power loss is forgotten; the PC sends it again.
    if (data && data.size() == f.size) files[kv.key().c_str()] = f;
  }
}

}  // namespace

bool begin() {
  lock = xSemaphoreCreateRecursiveMutex();
  if (!LittleFS.begin(true, "/fs", 10, "littlefs")) return false;
  LittleFS.mkdir("/f");
  Lock l;
  loadIndex();
  // Drop leftovers: half-received files and data no longer in the index.
  File dir = LittleFS.open("/f");
  std::vector<std::string> stale;
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    std::string name = f.name();
    if (!files.count(name)) stale.push_back(name);
  }
  dir.close();
  for (auto &name : stale) LittleFS.remove(path(name).c_str());
  saveIndex();
  return true;
}

size_t totalBytes() { return LittleFS.totalBytes(); }

size_t freeBytes() { return LittleFS.totalBytes() - LittleFS.usedBytes(); }

std::map<std::string, FileInfo> list() {
  Lock l;
  return files;
}

bool info(const std::string &id, FileInfo &out) {
  Lock l;
  auto it = files.find(id);
  if (it == files.end()) return false;
  out = it->second;
  return true;
}

std::shared_ptr<std::vector<uint8_t>> read(const std::string &id) {
  File in;
  {
    Lock l;
    if (!files.count(id)) return nullptr;
    in = LittleFS.open(path(id).c_str(), "r");
  }
  if (!in) return nullptr;
  auto data = std::make_shared<std::vector<uint8_t>>(in.size());
  size_t got = in.read(data->data(), data->size());
  return got == data->size() ? data : nullptr;
}

bool remove(const std::string &id) {
  Lock l;
  files.erase(id);
  saveIndex();
  return LittleFS.remove(path(id).c_str());
}

Writer::~Writer() { abort(); }

bool Writer::open(uint16_t xfer, const std::string &id, uint32_t size, const std::string &crc,
                  const std::string &format) {
  abort();
  tmp_ = "/f/.x" + std::to_string(xfer);
  id_ = id;
  size_ = size;
  crc_ = crc;
  format_ = format;
  written_ = crcRun_ = 0;
  File *f = new File(LittleFS.open(tmp_.c_str(), "w"));
  if (!*f) {
    delete f;
    return false;
  }
  file_ = f;
  return true;
}

bool Writer::append(const uint8_t *data, size_t len) {
  auto *f = static_cast<File *>(file_);
  if (!f || f->write(data, len) != len) return false;
  crcRun_ = proto::crc32(data, len, crcRun_);
  written_ += len;
  return true;
}

bool Writer::finish() {
  auto *f = static_cast<File *>(file_);
  if (!f) return false;
  f->close();
  delete f;
  file_ = nullptr;
  char hex[9];
  snprintf(hex, sizeof(hex), "%08x", (unsigned)crcRun_);
  if (written_ != size_ || crc_ != hex) {
    LittleFS.remove(tmp_.c_str());
    return false;
  }
  Lock l;
  LittleFS.remove(path(id_).c_str());
  LittleFS.rename(tmp_.c_str(), path(id_).c_str());
  files[id_] = FileInfo{crc_, size_, format_};
  saveIndex();
  return true;
}

void Writer::abort() {
  auto *f = static_cast<File *>(file_);
  if (!f) return;
  f->close();
  delete f;
  file_ = nullptr;
  LittleFS.remove(tmp_.c_str());
}

}  // namespace storage
