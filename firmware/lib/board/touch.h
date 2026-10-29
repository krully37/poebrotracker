// The AXS15231B's touch controller, over I2C. One finger is enough for this screen.
#pragma once

#include <stdint.h>

namespace touch {

struct Point {
  bool down;
  int16_t x, y;  // panel coordinates, like display::kWidth × kHeight
};

bool begin();
Point read();

}  // namespace touch
