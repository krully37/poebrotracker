#include "protocol.h"

namespace proto {

namespace {

struct CrcTable {
  uint32_t v[256];
  CrcTable() {
    for (uint32_t i = 0; i < 256; ++i) {
      uint32_t c = i;
      for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
      v[i] = c;
    }
  }
};

const CrcTable kCrc;

}  // namespace

uint32_t crc32(const uint8_t *data, size_t len, uint32_t crc) {
  crc = ~crc;
  for (size_t i = 0; i < len; ++i) crc = kCrc.v[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
  return ~crc;
}

std::vector<uint8_t> cobsEncode(const uint8_t *data, size_t len) {
  std::vector<uint8_t> out;
  out.reserve(len + len / 254 + 2);
  out.push_back(0);
  size_t codePos = 0;
  uint8_t code = 1;
  for (size_t i = 0; i < len; ++i) {
    if (data[i] == 0) {
      out[codePos] = code;
      codePos = out.size();
      code = 1;
      out.push_back(0);
      continue;
    }
    out.push_back(data[i]);
    if (++code == 0xFF) {
      out[codePos] = code;
      codePos = out.size();
      code = 1;
      out.push_back(0);
    }
  }
  out[codePos] = code;
  return out;
}

bool cobsDecode(const uint8_t *data, size_t len, std::vector<uint8_t> &out) {
  out.clear();
  size_t i = 0;
  while (i < len) {
    uint8_t code = data[i];
    if (code == 0 || i + code > len) return false;
    out.insert(out.end(), data + i + 1, data + i + code);
    i += code;
    if (code < 0xFF && i < len) out.push_back(0);
  }
  return true;
}

std::vector<uint8_t> encodeFrame(uint8_t type, uint16_t seq, const uint8_t *payload, size_t len) {
  std::vector<uint8_t> body;
  body.reserve(len + 7);
  body.push_back(type);
  body.push_back(seq & 0xFF);
  body.push_back(seq >> 8);
  body.insert(body.end(), payload, payload + len);
  uint32_t crc = crc32(body.data(), body.size());
  for (int k = 0; k < 4; ++k) body.push_back((crc >> (8 * k)) & 0xFF);
  std::vector<uint8_t> out = cobsEncode(body.data(), body.size());
  out.push_back(0);
  return out;
}

bool FrameReader::push(uint8_t byte, Frame &out) {
  if (byte != 0) {
    if (skipping_) return false;
    buf_.push_back(byte);
    if (buf_.size() > kMaxFrame * 2) {  // no delimiter in sight: garbage
      buf_.clear();
      skipping_ = true;
      ++dropped_;
    }
    return false;
  }
  skipping_ = false;
  if (buf_.empty()) return false;
  bool ok = decode(out);
  buf_.clear();
  if (!ok) ++dropped_;
  return ok;
}

bool FrameReader::decode(Frame &out) {
  if (buf_.size() > kMaxFrame + kMaxFrame / 254 + 2) return false;
  if (!cobsDecode(buf_.data(), buf_.size(), body_) || body_.size() < 7) return false;
  size_t n = body_.size() - 4;
  uint32_t crc = body_[n] | (body_[n + 1] << 8) | (body_[n + 2] << 16) | ((uint32_t)body_[n + 3] << 24);
  if (crc32(body_.data(), n) != crc) return false;
  out.type = body_[0];
  out.seq = body_[1] | (body_[2] << 8);
  out.payload.assign(body_.begin() + 3, body_.begin() + n);
  return true;
}

bool parseChunk(const std::vector<uint8_t> &payload, uint16_t &xfer, uint32_t &offset, const uint8_t *&data,
                size_t &len) {
  if (payload.size() < 6) return false;
  const uint8_t *p = payload.data();
  xfer = p[0] | (p[1] << 8);
  offset = p[2] | (p[3] << 8) | (p[4] << 16) | ((uint32_t)p[5] << 24);
  data = p + 6;
  len = payload.size() - 6;
  return true;
}

}  // namespace proto
