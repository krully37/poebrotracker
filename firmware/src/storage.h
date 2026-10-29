// Files from the PC (backgrounds, animations, `boot`) in LittleFS, which survives power cuts.
// Written by the link task, read by the display; every call is safe from both.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace storage {

struct FileInfo {
  std::string crc;  // 8 hex digits, as the PC sent it
  uint32_t size = 0;
  std::string format;  // "jpeg", "gif", "mjpeg"
};

bool begin();
size_t totalBytes();
size_t freeBytes();
std::map<std::string, FileInfo> list();
bool info(const std::string &id, FileInfo &out);
// The whole file in PSRAM, or nullptr when missing.
std::shared_ptr<std::vector<uint8_t>> read(const std::string &id);
bool remove(const std::string &id);

// One file arriving in chunks; it replaces any file of the same id only once it is complete
// and its CRC matches.
class Writer {
 public:
  ~Writer();
  bool open(uint16_t xfer, const std::string &id, uint32_t size, const std::string &crc, const std::string &format);
  bool append(const uint8_t *data, size_t len);
  // Checks size and CRC, then puts the file in place. False (and nothing changed) otherwise.
  bool finish();
  void abort();
  uint32_t written() const { return written_; }

 private:
  std::string tmp_, id_, crc_, format_;
  uint32_t size_ = 0, written_ = 0, crcRun_ = 0;
  void *file_ = nullptr;
};

}  // namespace storage
