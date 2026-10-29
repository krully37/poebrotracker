// The USB link to the PC (docs/PROTOCOL.md), mirroring SimScreen in
// pc/stashdisplay/link/simulator.py. Runs as its own task on core 0: reads frames, applies them
// to `state` and storage, answers each with an ACK, and sends the screen's events.
#pragma once

#include <string>

// Not `link`: that is a POSIX function.
namespace pclink {

void start();
// From any task. `json` is the EVENT payload; it is dropped while the PC is away.
void sendEvent(const std::string &json);
// Debug text to the PC (a LOG frame), from any task.
void log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

}  // namespace pclink
