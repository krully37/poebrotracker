// Plays a video background (the MJ1 format, docs/PROTOCOL.md) into a landscape canvas, reading one
// JPEG frame at a time from flash: a video does not fit in PSRAM (docs/SCOPE.md §5).
#pragma once

#include <stdint.h>

#include <string>
#include <vector>

#include "storage.h"

class VideoPlayer {
 public:
  // Starts the file from its first frame. False when it cannot be read.
  bool open(const std::string &id, uint16_t *canvas);
  void close();
  bool isOpen() const { return open_; }
  bool due(uint32_t now) const { return open_ && (int32_t)(now - dueMs_) >= 0; }
  // Decodes the next frame once the current one has had its time; true when the canvas changed.
  // Late frames show at once: the video slows down rather than skipping.
  bool advance(uint32_t now);
  // Only the first frame, into `canvas` (for the pages beside the one shown).
  static bool firstFrame(const std::string &id, uint16_t *canvas);

 private:
  bool decode(size_t i);

  storage::Reader file_;
  std::vector<uint32_t> offsets_;
  std::vector<uint8_t> frame_;
  uint16_t *canvas_ = nullptr;
  uint32_t frameMs_ = 83, dueMs_ = 0;
  size_t next_ = 0;
  bool open_ = false;
  // Timings over the first loop, sent to the PC log once (flash read and JPEG decode).
  uint32_t readUs_ = 0, decodeUs_ = 0, timed_ = 0;
  std::string id_;
};
