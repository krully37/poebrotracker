// Plays a GIF from memory into a landscape canvas, frame by frame, the way the PC encodes them
// (docs/PROTOCOL.md): later frames are deltas (see-through = unchanged), disposal 2 honoured. With
// a mask, see-through pixels are marked as such instead (a GIF played over the page).
#pragma once

#include <stdint.h>

#include <memory>
#include <vector>

class AnimatedGIF;

class GifPlayer {
 public:
  GifPlayer();
  ~GifPlayer();
  // Starts `data` from its first frame into `canvas` (kLandscapeW × kLandscapeH, cleared to black)
  // and `mask` (1 where the GIF drew, cleared), or no mask. False when it cannot be read.
  bool open(std::shared_ptr<std::vector<uint8_t>> data, uint16_t *canvas, uint8_t *mask);
  void close();
  bool isOpen() const { return open_; }
  // Decodes the next frame once the current one has had its time; true when the canvas changed.
  // Late frames show at once: the animation slows down rather than skipping (docs/SCOPE.md §8b).
  bool advance(uint32_t now);
  bool due(uint32_t now) const { return open_ && (int32_t)(now - dueMs_) >= 0; }
  // Total length in ms, or 0 when it cannot be read.
  static uint32_t length(const std::vector<uint8_t> &data);

 private:
  static void draw(struct gif_draw_tag *d);
  void clearLast();

  AnimatedGIF *gif_;
  std::shared_ptr<std::vector<uint8_t>> data_;
  uint16_t *canvas_ = nullptr;
  uint8_t *mask_ = nullptr;
  bool open_ = false;
  uint32_t dueMs_ = 0;
  // What the last frame drew, for disposal 2 ("restore to background") before the next one.
  int lastX_ = 0, lastY_ = 0, lastW_ = 0, lastH_ = 0, lastDisposal_ = 0;
};
