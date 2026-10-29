// The screen firmware (docs/SCOPE.md §8b). Core 0: the USB link task. Core 1 (this loop): the display.
#include <Arduino.h>

#include "display.h"
#include "pclink.h"
#include "screen.h"
#include "state.h"
#include "storage.h"

void setup() {
  display::begin();
  stateBegin();
  bool fs = storage::begin();
  screen::begin();
  pclink::start();
  if (!fs) pclink::log("LittleFS: mount failed");
}

void loop() {
  screen::tick();
  delay(5);
}
