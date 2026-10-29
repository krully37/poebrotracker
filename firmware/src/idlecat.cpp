#include "idlecat.h"

#include <Arduino.h>
#include <math.h>

#include <vector>

#include "storage.h"

namespace idlecat {
namespace {

constexpr float kSpeed = 100;    // px/s
constexpr float kTurnS = 0.25f;  // time constant of the turn towards the new direction

std::vector<uint8_t> source;   // the sprite, unpacked: "OV1" | w | h | alpha | colour
std::vector<uint8_t> turned;   // the same, turned, in a square that fits any angle
int sw = 0, sh = 0, side = 0;  // source size, turned square size
int turnedAngle = 1000;        // whole degrees `turned` holds

float x, y, vx, vy, angle;  // centre, velocity (px/s), current angle (degrees)
uint32_t lastMs;
int left, top, right, bottom;  // how far the visible cat reaches from its centre, as turned

float facing(float vx, float vy) { return -atan2f(vy, vx) * 180 / (float)M_PI; }

int nibble(const uint8_t *alpha, int i) { return (i & 1) ? alpha[i >> 1] & 15 : alpha[i >> 1] >> 4; }

// Turns the source counter-clockwise by `deg` (as PIL's rotate does), bilinear, into `turned`, and
// measures the visible extents.
void turn(int deg) {
  turnedAngle = deg;
  float a = deg * (float)M_PI / 180, c = cosf(a), s = sinf(a);
  const uint8_t *sa = source.data() + 7;
  const uint8_t *sc = sa + (size_t)sw * sh / 2;
  uint8_t *ta = turned.data() + 7;
  uint8_t *tc = ta + (size_t)side * side / 2;
  memset(ta, 0, (size_t)side * side / 2);
  float half = side / 2.0f, scx = sw / 2.0f, scy = sh / 2.0f;
  int x0 = side, y0 = side, x1 = -1, y1 = -1;
  for (int ty = 0; ty < side; ++ty) {
    for (int tx = 0; tx < side; ++tx) {
      float dx = tx + 0.5f - half, dy = ty + 0.5f - half;
      float fx = dx * c - dy * s + scx - 0.5f, fy = dx * s + dy * c + scy - 0.5f;
      int ix = (int)floorf(fx), iy = (int)floorf(fy);
      if (ix < -1 || iy < -1 || ix >= sw || iy >= sh) continue;
      float wx = fx - ix, wy = fy - iy;
      float acc = 0, r = 0, g = 0, b = 0;
      for (int k = 0; k < 4; ++k) {
        int px = ix + (k & 1), py = iy + (k >> 1);
        if (px < 0 || py < 0 || px >= sw || py >= sh) continue;
        int i = py * sw + px;
        float w = ((k & 1) ? wx : 1 - wx) * ((k >> 1) ? wy : 1 - wy) * nibble(sa, i);
        if (w <= 0) continue;
        uint16_t col = sc[2 * i] | sc[2 * i + 1] << 8;
        acc += w;
        r += w * (col >> 11);
        g += w * ((col >> 5) & 63);
        b += w * (col & 31);
      }
      int n = lroundf(acc);  // the weights sum to 1, so this is the blended alpha (0–15)
      if (n <= 0) continue;
      int i = ty * side + tx;
      ta[i >> 1] |= (i & 1) ? n : n << 4;
      uint16_t col = ((int)lroundf(r / acc) << 11) | ((int)lroundf(g / acc) << 5) | (int)lroundf(b / acc);
      tc[2 * i] = col & 0xFF;
      tc[2 * i + 1] = col >> 8;
      x0 = min(x0, tx), y0 = min(y0, ty), x1 = max(x1, tx), y1 = max(y1, ty);
    }
  }
  if (x1 < 0) x0 = y0 = 0, x1 = y1 = side - 1;
  left = side / 2 - x0;
  top = side / 2 - y0;
  right = x1 + 1 - side / 2;
  bottom = y1 + 1 - side / 2;
}

}  // namespace

bool start(const std::string &file) {
  storage::FileInfo f;
  if (!storage::info(file, f) || f.format != "sprite") return false;
  auto z = storage::read(file);
  if (!z || !compositor::inflateSprite(z->data(), z->size(), source)) return false;
  sw = source[3] | source[4] << 8;
  sh = source[5] | source[6] << 8;
  side = ((int)ceilf(sqrtf((float)sw * sw + (float)sh * sh)) + 1) & ~1;  // even, as the format wants
  turned.assign(7 + (size_t)side * side / 2 + (size_t)side * side * 2, 0);
  memcpy(turned.data(), "OV1", 3);
  turned[3] = turned[5] = side & 0xFF;
  turned[4] = turned[6] = side >> 8;
  // From the middle, in a random diagonal direction, already facing it.
  float heading = (20 + esp_random() % 51 + 90 * (esp_random() % 4)) * (float)M_PI / 180;
  vx = kSpeed * cosf(heading);
  vy = kSpeed * sinf(heading);
  angle = facing(vx, vy);
  x = kLandscapeW / 2.0f;
  y = kLandscapeH / 2.0f;
  lastMs = millis();
  turn(((int)lroundf(angle) % 360 + 360) % 360);
  return true;
}

void step(uint32_t now) {
  float dt = fminf(0.1f, (now - lastMs) / 1000.0f);
  lastMs = now;
  if (dt <= 0) return;
  float diff = fmodf(facing(vx, vy) - angle + 540, 360) - 180;
  angle += diff * (1 - expf(-dt / kTurnS));
  int deg = ((int)lroundf(angle) % 360 + 360) % 360;
  if (deg != turnedAngle) turn(deg);
  x += vx * dt;
  y += vy * dt;
  if ((x - left < 0 && vx < 0) || (x + right > kLandscapeW && vx > 0)) vx = -vx;
  if ((y - top < 0 && vy < 0) || (y + bottom > kLandscapeH && vy > 0)) vy = -vy;
  // Turning changes its outline: keep all of it on the screen.
  x = fminf(fmaxf(x, left), kLandscapeW - right);
  y = fminf(fmaxf(y, top), kLandscapeH - bottom);
}

compositor::Sprite sprite() {
  return compositor::Sprite{turned.data(), (int)lroundf(x - side / 2.0f), (int)lroundf(y - side / 2.0f)};
}

}  // namespace idlecat
