// Firmware-wide constants.
#pragma once

constexpr const char *kFirmwareVersion = "0.6a";
// What the PC sends: landscape (docs/PROTOCOL.md). The panel itself is portrait (display.h).
constexpr int kLandscapeW = 480;
constexpr int kLandscapeH = 320;
