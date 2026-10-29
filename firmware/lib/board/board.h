// Guition JC3248W535 pins (checked on the real board in step 5).
#pragma once

namespace pins {
// AXS15231B panel, QSPI
constexpr int kLcdCs = 45;
constexpr int kLcdSck = 47;
constexpr int kLcdD0 = 21;
constexpr int kLcdD1 = 48;
constexpr int kLcdD2 = 40;
constexpr int kLcdD3 = 39;
constexpr int kBacklight = 1;
// AXS15231B touch, I2C
constexpr int kTouchSda = 4;
constexpr int kTouchScl = 8;
constexpr int kTouchAddr = 0x3B;
}  // namespace pins
