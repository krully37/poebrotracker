// The board's native USB serial (USB-Serial/JTAG), read and written straight from its 64-byte
// FIFOs, with Arduino's USB Serial turned off (ARDUINO_USB_CDC_ON_BOOT=0).
//
// Arduino's Serial pushes every received byte through a FreeRTOS queue from its interrupt and
// drops bytes when the queue is full (step 5: 143 kB of 200 kB arrived). Here nothing is taken
// from the FIFO until the caller asks, so the host simply waits: no byte is ever lost.
#pragma once

#include <Print.h>
#include <stddef.h>
#include <stdint.h>

class UsbLink : public Print {
 public:
  // Whatever has arrived, up to len bytes. Never blocks.
  size_t read(uint8_t *buf, size_t len);
  int read();  // one byte, or -1
  size_t write(uint8_t c) override;
  // Gives up after about 50 ms without room, when the PC is not reading (port closed).
  size_t write(const uint8_t *buf, size_t len) override;
  void flush() override;
};

extern UsbLink usb;
