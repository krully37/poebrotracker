// What the PC told the screen, shared between the link task (core 0, writes) and the display
// (core 1, reads). Take `State::Lock` for every access; the display copies what it needs and
// lets go before drawing.
#pragma once

#include <Arduino.h>

#include <map>
#include <memory>
#include <string>
#include <vector>

#include "gestures.h"
#include "protocol.h"

using Blob = std::shared_ptr<const std::vector<uint8_t>>;

using Zone = gestures::Zone;

struct Page {
  std::string id;
  uint16_t bgColor = 0;  // RGB565
  std::string bgFile;    // empty: colour only
  std::vector<Zone> zones;
};

struct Overlay {
  std::string crc;
  Blob data;  // zlib, as sent
};

struct Play {
  std::string file;     // empty: black
  std::string overlay;  // empty: none
  uint32_t startMs, untilMs;
  bool overPage;
};

struct State {
  struct Lock {
    Lock();
    ~Lock();
  };

  std::vector<Page> pages;
  size_t current = 0;
  std::map<std::string, Overlay> overlays;  // page ids, plus "@event" and "@toast"
  std::string toast;                        // overlay id while a toast shows
  uint32_t toastUntilMs = 0;
  bool playing = false;
  Play play;
  // The idle cat: the sprite file bouncing instead of the pages, or empty. idleSerial changes each
  // time the cat has to start over (a new sprite, or a new file under the same id).
  std::string idleSprite;
  uint32_t idleSerial = 0;

  bool everHeard = false;
  uint32_t lastRxMs = 0;
  // Bumped on every change the display should redraw for.
  uint32_t version = 0;

  bool online(uint32_t now) const { return everHeard && now - lastRxMs < proto::kOfflineAfterMs; }
};

extern State state;
void stateBegin();
