// What the panel shows, run from the Arduino loop on core 1: the current page, or the offline
// screen at 30 % backlight ("Waiting for the PC" before the first frame, "PC disconnected" after).
#pragma once

namespace screen {

void begin();
void tick();

}  // namespace screen
