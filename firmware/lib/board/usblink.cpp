#include "usblink.h"

#include <Arduino.h>
#include <hal/usb_serial_jtag_ll.h>

UsbLink usb;

size_t UsbLink::read(uint8_t *buf, size_t len) {
  size_t got = 0;
  while (got < len && usb_serial_jtag_ll_rxfifo_data_available()) {
    got += usb_serial_jtag_ll_read_rxfifo(buf + got, len - got);
  }
  return got;
}

int UsbLink::read() {
  uint8_t c;
  return read(&c, 1) ? c : -1;
}

size_t UsbLink::write(uint8_t c) { return write(&c, 1); }

size_t UsbLink::write(const uint8_t *buf, size_t len) {
  size_t sent = 0;
  uint32_t waitingSince = 0;
  while (sent < len) {
    if (usb_serial_jtag_ll_txfifo_writable()) {
      sent += usb_serial_jtag_ll_write_txfifo(buf + sent, len - sent);
      waitingSince = 0;
      continue;
    }
    // FIFO full: send what is in it and wait for the host to take it.
    usb_serial_jtag_ll_txfifo_flush();
    if (!waitingSince) waitingSince = millis();
    if (millis() - waitingSince > 50) break;
  }
  usb_serial_jtag_ll_txfifo_flush();
  return sent;
}

void UsbLink::flush() { usb_serial_jtag_ll_txfifo_flush(); }
