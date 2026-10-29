#include "touch.h"

#include <Arduino.h>
#include <Wire.h>

#include "board.h"

namespace touch {

bool begin() {
  if (!Wire.begin(pins::kTouchSda, pins::kTouchScl, 400000)) return false;
  Wire.beginTransmission(pins::kTouchAddr);
  return Wire.endTransmission() == 0;
}

Point read() {
  // The controller's "read touch data" command, then 8 bytes back.
  static const uint8_t kCmd[11] = {0xb5, 0xab, 0xa5, 0x5a, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00};
  Point p = {false, 0, 0};
  Wire.beginTransmission(pins::kTouchAddr);
  Wire.write(kCmd, sizeof(kCmd));
  if (Wire.endTransmission() != 0) return p;
  uint8_t buf[8] = {};
  if (Wire.requestFrom(pins::kTouchAddr, 8) != 8) return p;
  Wire.readBytes(buf, 8);
  uint8_t fingers = buf[1];
  if (fingers == 0 || fingers > 2) return p;
  p.down = true;
  p.x = ((buf[2] & 0x0F) << 8) | buf[3];
  p.y = ((buf[4] & 0x0F) << 8) | buf[5];
  return p;
}

}  // namespace touch
