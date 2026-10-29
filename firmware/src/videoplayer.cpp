#include "videoplayer.h"

#include <Arduino.h>

#include "compositor.h"
#include "pclink.h"

bool VideoPlayer::open(const std::string &id, uint16_t *canvas) {
  close();
  uint8_t head[7];
  if (!file_.open(id) || !file_.read(0, head, sizeof(head)) || memcmp(head, "MJ1", 3) != 0) return false;
  frameMs_ = head[3] | head[4] << 8;
  size_t count = head[5] | head[6] << 8;
  offsets_.resize(count + 1);
  if (!count || !file_.read(7, reinterpret_cast<uint8_t *>(offsets_.data()), offsets_.size() * 4)) return false;
  for (size_t i = 0; i < count; ++i) {
    if (offsets_[i + 1] < offsets_[i]) return false;
  }
  canvas_ = canvas;
  id_ = id;
  next_ = 0;
  readUs_ = decodeUs_ = timed_ = 0;
  open_ = true;
  dueMs_ = millis();
  return true;
}

void VideoPlayer::close() {
  file_.close();
  open_ = false;
}

bool VideoPlayer::decode(size_t i) {
  uint32_t t0 = micros();
  frame_.resize(offsets_[i + 1] - offsets_[i]);
  if (!file_.read(offsets_[i], frame_.data(), frame_.size())) return false;
  uint32_t t1 = micros();
  bool ok = compositor::decodeJpeg(frame_, canvas_);
  uint32_t t2 = micros();
  if (timed_ < offsets_.size() - 1) {
    readUs_ += t1 - t0;
    decodeUs_ += t2 - t1;
    if (++timed_ == offsets_.size() - 1) {
      pclink::log("video %s: %u frames, read %u ms, decode %u ms a frame", id_.c_str(), (unsigned)timed_,
                  (unsigned)(readUs_ / timed_ / 1000), (unsigned)(decodeUs_ / timed_ / 1000));
    }
  }
  return ok;
}

bool VideoPlayer::advance(uint32_t now) {
  if (!due(now)) return false;
  if (!decode(next_)) {
    pclink::log("video %s: cannot read frame %u", id_.c_str(), (unsigned)next_);
    close();
    return false;
  }
  next_ = (next_ + 1) % (offsets_.size() - 1);
  dueMs_ = now + frameMs_;
  return true;
}

bool VideoPlayer::firstFrame(const std::string &id, uint16_t *canvas) {
  VideoPlayer v;
  return v.open(id, canvas) && v.decode(0);
}
