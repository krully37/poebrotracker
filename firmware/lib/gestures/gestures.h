// Touch gestures (docs/PROTOCOL.md, "Screen behaviour"), mirroring SimScreen.touch_* in
// pc/stashdisplay/link/simulator.py. Plain C++, tested on the PC (test/test_gestures).
// Coordinates are landscape screen pixels; times are milliseconds.
#pragma once

#include <stdint.h>

#include <string>

namespace gestures {

constexpr float kSlop = 12;          // px a finger may move and still count as still
constexpr float kSwipeMin = 60;      // px of horizontal travel for a page change
constexpr uint32_t kPressDelay = 400;  // ms of holding still before the reset banner appears
constexpr uint32_t kHoldFill = 1500;   // ms for its bar to fill

struct Zone {
  int16_t x = 0, y = 0, w = 0, h = 0;
  std::string action;
  bool tap = false;  // "gesture": "tap"; otherwise a long press ("hold")

  bool contains(float px, float py) const { return x <= px && px < x + w && y <= py && py < y + h; }
};

struct Result {
  enum Kind { None, Tap, Page, Reset } kind = None;
  int step = 0;        // Page: +1 next (finger moved left), -1 previous
  std::string action;  // Tap in a tap zone, or Reset
};

class Tracker {
 public:
  // `zone`: the zone under the finger at touch-down, or nullptr.
  void down(float x, float y, uint32_t ms, const Zone *zone);
  void move(float x, float y);
  // `pages`: how many pages there are (a swipe needs two).
  Result up(float x, float y, uint32_t ms, int pages);
  // Once the bar has filled: Reset, once.
  Result tick(uint32_t ms);
  // The reset banner to show: its progress 0..1 and the zone's action, or false when none.
  bool hold(uint32_t ms, float &progress, std::string &action) const;
  bool touching() const { return touching_; }

 private:
  bool holding() const { return touching_ && hasZone_ && !zone_.tap && !moved_ && !done_; }

  bool touching_ = false, moved_ = false, done_ = false, hasZone_ = false;
  float x0_ = 0, y0_ = 0;
  uint32_t t0_ = 0;
  Zone zone_;
};

}  // namespace gestures
