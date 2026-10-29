#include "gestures.h"

#include <math.h>

namespace gestures {

void Tracker::down(float x, float y, uint32_t ms, const Zone *zone) {
  touching_ = true;
  moved_ = done_ = false;
  x0_ = x;
  y0_ = y;
  t0_ = ms;
  hasZone_ = zone != nullptr;
  zone_ = zone ? *zone : Zone();
}

void Tracker::move(float x, float y) {
  if (!touching_) return;
  if (fabsf(x - x0_) > kSlop || fabsf(y - y0_) > kSlop) moved_ = true;  // also cancels a hold
}

Result Tracker::up(float x, float y, uint32_t ms, int pages) {
  Result r;
  if (!touching_) return r;
  move(x, y);
  touching_ = false;
  if (done_ || pages <= 0) return r;
  float dx = x - x0_, dy = y - y0_;
  if (moved_) {
    if (fabsf(dx) >= kSwipeMin && fabsf(dx) > fabsf(dy) && pages > 1) {
      r.kind = Result::Page;
      r.step = dx < 0 ? 1 : -1;
    }
  } else if (ms - t0_ < kPressDelay) {
    r.kind = Result::Tap;
    if (hasZone_ && zone_.tap) r.action = zone_.action;
  }
  // Held without a zone, or let go before the bar filled: nothing.
  return r;
}

Result Tracker::tick(uint32_t ms) {
  Result r;
  if (holding() && ms - t0_ >= kPressDelay + kHoldFill) {
    done_ = true;
    r.kind = Result::Reset;
    r.action = zone_.action;
  }
  return r;
}

bool Tracker::hold(uint32_t ms, float &progress, std::string &action) const {
  if (!holding() || ms - t0_ < kPressDelay) return false;
  progress = fminf(1.0f, (float)(ms - t0_ - kPressDelay) / kHoldFill);
  action = zone_.action;
  return true;
}

}  // namespace gestures
