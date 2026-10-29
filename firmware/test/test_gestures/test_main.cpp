// Gesture tests, run on the PC: pio test -e native
// The same cases as the simulator's touch handling (pc/stashdisplay/link/simulator.py).
#include <unity.h>

#include "gestures.h"

using namespace gestures;

static Zone hold(const char *action) {
  Zone z;
  z.x = 0;
  z.y = 0;
  z.w = 200;
  z.h = 100;
  z.action = action;
  return z;
}

void setUp() {}
void tearDown() {}

void test_quick_touch_is_a_tap() {
  Tracker t;
  t.down(100, 100, 0, nullptr);
  t.move(105, 103);  // within the slop
  Result r = t.up(105, 103, 200, 3);
  TEST_ASSERT_EQUAL(Result::Tap, r.kind);
  TEST_ASSERT_TRUE(r.action.empty());
}

void test_tap_in_a_tap_zone_carries_its_action() {
  Zone z = hold("media_next");
  z.tap = true;
  Tracker t;
  t.down(50, 50, 0, &z);
  Result r = t.up(50, 50, 100, 3);
  TEST_ASSERT_EQUAL(Result::Tap, r.kind);
  TEST_ASSERT_EQUAL_STRING("media_next", r.action.c_str());
}

void test_slow_touch_outside_zones_does_nothing() {
  Tracker t;
  t.down(300, 200, 0, nullptr);
  TEST_ASSERT_EQUAL(Result::None, t.up(300, 200, 450, 3).kind);
}

void test_swipe_left_goes_to_the_next_page() {
  Tracker t;
  t.down(300, 150, 0, nullptr);
  t.move(250, 155);
  Result r = t.up(230, 160, 250, 3);
  TEST_ASSERT_EQUAL(Result::Page, r.kind);
  TEST_ASSERT_EQUAL(1, r.step);
}

void test_swipe_right_goes_back() {
  Tracker t;
  t.down(100, 150, 0, nullptr);
  Result r = t.up(200, 150, 250, 3);
  TEST_ASSERT_EQUAL(Result::Page, r.kind);
  TEST_ASSERT_EQUAL(-1, r.step);
}

void test_short_or_vertical_drags_and_single_pages_do_not_swipe() {
  Tracker t;
  t.down(100, 100, 0, nullptr);
  TEST_ASSERT_EQUAL(Result::None, t.up(150, 100, 200, 3).kind);  // under 60 px
  t.down(100, 100, 0, nullptr);
  TEST_ASSERT_EQUAL(Result::None, t.up(170, 190, 200, 3).kind);  // more vertical than horizontal
  t.down(100, 100, 0, nullptr);
  TEST_ASSERT_EQUAL(Result::None, t.up(200, 100, 200, 1).kind);  // one page only
}

void test_hold_in_a_zone_fills_the_bar_then_resets_once() {
  Zone z = hold("reset_session");
  Tracker t;
  float p;
  std::string action;
  t.down(40, 30, 0, &z);
  TEST_ASSERT_FALSE(t.hold(300, p, action));  // not before the press delay
  TEST_ASSERT_TRUE(t.hold(1150, p, action));
  TEST_ASSERT_FLOAT_WITHIN(0.01, 0.5, p);
  TEST_ASSERT_EQUAL_STRING("reset_session", action.c_str());
  TEST_ASSERT_EQUAL(Result::None, t.tick(1800).kind);
  Result r = t.tick(1900);
  TEST_ASSERT_EQUAL(Result::Reset, r.kind);
  TEST_ASSERT_EQUAL_STRING("reset_session", r.action.c_str());
  TEST_ASSERT_EQUAL(Result::None, t.tick(2000).kind);
  TEST_ASSERT_FALSE(t.hold(2000, p, action));
  TEST_ASSERT_EQUAL(Result::None, t.up(40, 30, 2100, 3).kind);  // the release does nothing more
}

void test_moving_or_lifting_early_cancels_the_hold() {
  Zone z = hold("reset_rate");
  Tracker t;
  float p;
  std::string action;
  t.down(40, 30, 0, &z);
  t.move(60, 30);
  TEST_ASSERT_FALSE(t.hold(1000, p, action));
  TEST_ASSERT_EQUAL(Result::None, t.tick(2000).kind);
  t.down(40, 30, 0, &z);
  TEST_ASSERT_EQUAL(Result::None, t.up(40, 30, 1200, 3).kind);
}

void test_tap_zones_show_no_banner() {
  Zone z = hold("media_toggle");
  z.tap = true;
  Tracker t;
  float p;
  std::string action;
  t.down(40, 30, 0, &z);
  TEST_ASSERT_FALSE(t.hold(1000, p, action));
  TEST_ASSERT_EQUAL(Result::None, t.tick(3000).kind);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_quick_touch_is_a_tap);
  RUN_TEST(test_tap_in_a_tap_zone_carries_its_action);
  RUN_TEST(test_slow_touch_outside_zones_does_nothing);
  RUN_TEST(test_swipe_left_goes_to_the_next_page);
  RUN_TEST(test_swipe_right_goes_back);
  RUN_TEST(test_short_or_vertical_drags_and_single_pages_do_not_swipe);
  RUN_TEST(test_hold_in_a_zone_fills_the_bar_then_resets_once);
  RUN_TEST(test_moving_or_lifting_early_cancels_the_hold);
  RUN_TEST(test_tap_zones_show_no_banner);
  return UNITY_END();
}
