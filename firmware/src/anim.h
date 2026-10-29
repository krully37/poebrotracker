// Event animations and the start animation (PLAY, docs/PROTOCOL.md): a GIF or JPEG file from
// storage, decoded frame by frame into a landscape canvas. Run from the display loop (core 1).
#pragma once

#include <stdint.h>

#include <string>

namespace anim {

void begin();
// Keeps the event animations and `boot` loaded in PSRAM so they start at once (docs/SCOPE.md
// §8b). Loads at most one file per call; false when there was nothing to do.
bool preloadOne();
// How long a file plays at power-on: a GIF once, at least 3 s and at most 10 s; an image 4 s.
uint32_t bootLength(const std::string &file);

// Starts `file` ("" or missing: black). With `seeThrough`, pixels the GIF leaves see-through
// are marked in mask() so the page can show there.
void start(const std::string &file, bool seeThrough);
// Decodes the next frame once the current one has had its time. True when the canvas changed.
bool advance(uint32_t now);

const uint16_t *canvas();  // landscape RGB565
const uint8_t *mask();     // 1 where the GIF drew, with seeThrough; else nullptr

}  // namespace anim
