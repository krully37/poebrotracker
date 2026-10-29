#include "gifplayer.h"

#include <AnimatedGIF.h>
#include <Arduino.h>
#include <esp_heap_caps.h>

#include <new>

#include "firmware.h"

// The decoder's ~24 kB of tables stay in internal RAM: big allocations would otherwise go to
// PSRAM, which makes decoding slower.
GifPlayer::GifPlayer()
    : gif_(new (heap_caps_malloc(sizeof(AnimatedGIF), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)) AnimatedGIF()) {
  gif_->begin(GIF_PALETTE_RGB565_LE);
}

GifPlayer::~GifPlayer() {
  close();
  gif_->~AnimatedGIF();
  heap_caps_free(gif_);
}

bool GifPlayer::open(std::shared_ptr<std::vector<uint8_t>> data, uint16_t *canvas, uint8_t *mask) {
  close();
  canvas_ = canvas;
  mask_ = mask;
  for (size_t i = 0; i < (size_t)kLandscapeW * kLandscapeH; ++i) canvas_[i] = 0;
  if (mask_) memset(mask_, 0, (size_t)kLandscapeW * kLandscapeH);
  lastW_ = lastH_ = lastDisposal_ = 0;
  if (!data || !gif_->open(data->data(), data->size(), draw)) return false;
  data_ = data;
  open_ = true;
  dueMs_ = millis();
  return true;
}

void GifPlayer::close() {
  if (open_) gif_->close();
  open_ = false;
  data_.reset();
}

bool GifPlayer::advance(uint32_t now) {
  if (!due(now)) return false;
  if (lastDisposal_ == 2) clearLast();
  int delay = 100;
  int more = gif_->playFrame(false, &delay, this);
  if (more < 0) {
    close();
    return false;
  }
  if (more == 0) gif_->reset();  // that was the last frame: loop
  dueMs_ = now + max(20, delay);
  return true;
}

uint32_t GifPlayer::length(const std::vector<uint8_t> &data) {
  static AnimatedGIF probe;  // only reads the frame headers
  GIFINFO info = {};
  if (!probe.open(const_cast<uint8_t *>(data.data()), data.size(), draw)) return 0;
  probe.getInfo(&info);
  probe.close();
  return info.iDuration;
}

void GifPlayer::draw(GIFDRAW *d) {
  auto *self = static_cast<GifPlayer *>(d->pUser);
  if (!self) return;
  int y = d->iY + d->y;
  if (y < 0 || y >= kLandscapeH) return;
  self->lastX_ = d->iX;
  self->lastY_ = d->iY;
  self->lastW_ = d->iWidth;
  self->lastH_ = d->iHeight;
  self->lastDisposal_ = d->ucDisposalMethod;
  int w = min(d->iWidth, kLandscapeW - d->iX);
  uint16_t *line = self->canvas_ + y * kLandscapeW + d->iX;
  uint8_t *m = self->mask_ ? self->mask_ + y * kLandscapeW + d->iX : nullptr;
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

void GifPlayer::clearLast() {
  int x0 = max(0, lastX_), x1 = min(kLandscapeW, lastX_ + lastW_);
  if (x1 <= x0) return;
  for (int y = max(0, lastY_); y < min(kLandscapeH, lastY_ + lastH_); ++y) {
    memset(canvas_ + y * kLandscapeW + x0, 0, (x1 - x0) * 2);
    if (mask_) memset(mask_ + y * kLandscapeW + x0, 0, x1 - x0);
  }
}
