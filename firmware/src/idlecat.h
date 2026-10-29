// The idle cat (IDLE, docs/PROTOCOL.md "Idle"), mirroring SimScreen._idle_* in
// pc/stashdisplay/link/simulator.py: a sprite bouncing on black at 100 px/s, turning to face where
// it goes, kept whole on the screen. Run from the display loop (core 1), at 30 fps.
#pragma once

#include <stdint.h>

#include <string>

#include "compositor.h"

namespace idlecat {

constexpr uint32_t kFrameMs = 33;  // 30 fps (docs/SCOPE.md §8b)

// Loads the sprite file and starts from the middle in a random diagonal direction. False when the
// file is missing or is not a sprite.
bool start(const std::string &file);
// Moves the cat to `now`. Then sprite() is the cat as turned, at its place on the screen.
void step(uint32_t now);
compositor::Sprite sprite();

}  // namespace idlecat
