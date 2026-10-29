// Framing tests, run on the PC: pio test -e native
// The expected bytes and CRCs come from pc/stashdisplay/link/protocol.py, so both sides agree.
#include <unity.h>

#include <vector>

#include "protocol.h"

using namespace proto;

static std::vector<uint8_t> ones(size_t n) { return std::vector<uint8_t>(n, 1); }

static std::vector<uint8_t> chunkFrame() {
  std::vector<uint8_t> payload = {7, 0, 0x70, 0x11, 0x01, 0x00};  // xfer 7, offset 70000
  for (int r = 0; r < 2; ++r) {
    for (int i = 0; i < 256; ++i) payload.push_back(i);
  }
  return encodeFrame(kChunk, 0x1234, payload.data(), payload.size());
}

void setUp() {}
void tearDown() {}

void test_crc32_matches_zlib() {
  const uint8_t s[] = "123456789";
  TEST_ASSERT_EQUAL_HEX32(0xcbf43926, crc32(s, 9));
  // Chained in two parts, as file transfers do.
  TEST_ASSERT_EQUAL_HEX32(0xcbf43926, crc32(s + 4, 5, crc32(s, 4)));
}

void test_cobs_matches_python() {
  struct Case {
    size_t n, len;
    uint32_t crc;
  } cases[] = {{0, 1, 0xa505df1b}, {1, 2, 0x04e840eb}, {253, 254, 0xb631d275},
               {254, 256, 0xdb63ea99}, {255, 257, 0x0720c4d2}, {508, 511, 0x0e22c318}};
  for (auto &c : cases) {
    auto raw = ones(c.n);
    auto enc = cobsEncode(raw.data(), raw.size());
    TEST_ASSERT_EQUAL(c.len, enc.size());
    TEST_ASSERT_EQUAL_HEX32(c.crc, crc32(enc.data(), enc.size()));
    std::vector<uint8_t> back;
    TEST_ASSERT_TRUE(cobsDecode(enc.data(), enc.size(), back));
    TEST_ASSERT_TRUE(back == raw);
  }
}

void test_hello_frame_matches_python() {
  const uint8_t expected[] = {0x03, 0x01, 0x01, 0x12, 0x7b, 0x22, 0x76, 0x65, 0x72, 0x73, 0x69,
                              0x6f, 0x6e, 0x22, 0x3a, 0x31, 0x7d, 0x9d, 0xdd, 0x6c, 0x85, 0x00};
  const char json[] = "{\"version\":1}";
  auto f = encodeFrame(kHello, 1, (const uint8_t *)json, sizeof(json) - 1);
  TEST_ASSERT_EQUAL(sizeof(expected), f.size());
  TEST_ASSERT_EQUAL_HEX8_ARRAY(expected, f.data(), sizeof(expected));
}

void test_chunk_frame_matches_python_and_reads_back() {
  auto f = chunkFrame();
  TEST_ASSERT_EQUAL(529, f.size());
  TEST_ASSERT_EQUAL_HEX32(0xe9ed8f36, crc32(f.data(), f.size()));
  FrameReader r;
  Frame out;
  int got = 0;
  for (uint8_t b : f) got += r.push(b, out);
  TEST_ASSERT_EQUAL(1, got);
  TEST_ASSERT_EQUAL(kChunk, out.type);
  TEST_ASSERT_EQUAL(0x1234, out.seq);
  uint16_t xfer;
  uint32_t offset;
  const uint8_t *data;
  size_t len;
  TEST_ASSERT_TRUE(parseChunk(out.payload, xfer, offset, data, len));
  TEST_ASSERT_EQUAL(7, xfer);
  TEST_ASSERT_EQUAL(70000, offset);
  TEST_ASSERT_EQUAL(512, len);
  TEST_ASSERT_EQUAL(255, data[255]);
}

void test_reader_drops_bad_frames_and_resyncs() {
  auto good = chunkFrame();
  std::vector<uint8_t> wire = {'b', 'o', 'o', 't', ' ', 'l', 'o', 'g', 0};  // garbage before
  auto bad = good;
  bad[10] ^= 0x40;  // corrupt one byte: the CRC fails
  wire.insert(wire.end(), bad.begin(), bad.end());
  wire.insert(wire.end(), good.begin(), good.end());
  FrameReader r;
  Frame out;
  int got = 0;
  for (uint8_t b : wire) got += r.push(b, out);
  TEST_ASSERT_EQUAL(1, got);
  TEST_ASSERT_EQUAL(2, r.dropped());
  TEST_ASSERT_EQUAL(0x1234, out.seq);
}

void test_reader_drops_an_endless_frame() {
  FrameReader r;
  Frame out;
  for (size_t i = 0; i < kMaxFrame * 3; ++i) r.push(0x55, out);
  TEST_ASSERT_EQUAL(1, r.dropped());
  int got = 0;
  for (uint8_t b : chunkFrame()) got += r.push(b, out);
  TEST_ASSERT_EQUAL(0, got);  // still skipping: the first 0x00 only ends the garbage
  for (uint8_t b : chunkFrame()) got += r.push(b, out);
  TEST_ASSERT_EQUAL(1, got);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_crc32_matches_zlib);
  RUN_TEST(test_cobs_matches_python);
  RUN_TEST(test_hello_frame_matches_python);
  RUN_TEST(test_chunk_frame_matches_python_and_reads_back);
  RUN_TEST(test_reader_drops_bad_frames_and_resyncs);
  RUN_TEST(test_reader_drops_an_endless_frame);
  return UNITY_END();
}
