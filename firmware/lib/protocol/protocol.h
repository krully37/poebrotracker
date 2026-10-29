// The PC <-> screen framing (docs/PROTOCOL.md), mirroring pc/stashdisplay/link/protocol.py.
// Plain C++ with no Arduino code, so it is unit-tested on the PC (test/test_protocol).
//
// Frame on the wire: COBS( type:u8 | seq:u16 LE | payload | crc32:u32 LE ) 0x00
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <vector>

namespace proto {

constexpr int kVersion = 1;
constexpr size_t kMaxChunk = 4096;          // data bytes per CHUNK frame
constexpr size_t kMaxFrame = kMaxChunk + 64;  // larger frames are dropped as garbage
constexpr uint32_t kAckTimeoutMs = 1000;
constexpr int kRetries = 4;
constexpr uint32_t kOfflineAfterMs = 90000;

// PC -> screen
constexpr uint8_t kHello = 0x01;
constexpr uint8_t kPages = 0x02;
constexpr uint8_t kBegin = 0x03;
constexpr uint8_t kChunk = 0x04;
constexpr uint8_t kEnd = 0x05;
constexpr uint8_t kDelete = 0x06;
constexpr uint8_t kPlay = 0x07;
constexpr uint8_t kPing = 0x08;
constexpr uint8_t kEventAck = 0x09;
// Screen -> PC
constexpr uint8_t kAck = 0x81;
constexpr uint8_t kEvent = 0x82;
constexpr uint8_t kLog = 0x83;

// zlib's CRC-32. Chain it by passing the previous result.
uint32_t crc32(const uint8_t *data, size_t len, uint32_t crc = 0);

std::vector<uint8_t> cobsEncode(const uint8_t *data, size_t len);
// False on a malformed block.
bool cobsDecode(const uint8_t *data, size_t len, std::vector<uint8_t> &out);

// A whole frame, COBS-encoded and ended by 0x00, ready to write.
std::vector<uint8_t> encodeFrame(uint8_t type, uint16_t seq, const uint8_t *payload, size_t len);

struct Frame {
  uint8_t type = 0;
  uint16_t seq = 0;
  std::vector<uint8_t> payload;
};

// Collects bytes from the wire and hands out whole, checked frames. Bad frames are dropped,
// and the reader picks up again at the next 0x00.
class FrameReader {
 public:
  // True when this byte completed a good frame, now in `out`.
  bool push(uint8_t byte, Frame &out);
  uint32_t dropped() const { return dropped_; }

 private:
  bool decode(Frame &out);
  std::vector<uint8_t> buf_;
  std::vector<uint8_t> body_;
  bool skipping_ = false;  // too long: drop bytes until the next 0x00
  uint32_t dropped_ = 0;
};

// CHUNK payload: xfer:u16 LE, offset:u32 LE, then data. False when too short.
bool parseChunk(const std::vector<uint8_t> &payload, uint16_t &xfer, uint32_t &offset, const uint8_t *&data,
                size_t &len);

}  // namespace proto
