#include "usblink.h"

#include <Arduino.h>
#include <esp_intr_alloc.h>
#include <soc/interrupts.h>
#include <hal/usb_serial_jtag_ll.h>

UsbLink usb;

namespace {

TaskHandle_t waiter;

// Only wakes the reading task: the data stays in the FIFO, so the host waits until it is read.
void IRAM_ATTR onPacket(void *) {
  usb_serial_jtag_ll_disable_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT);
  usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT);
  BaseType_t woken = pdFALSE;
  if (waiter) vTaskNotifyGiveFromISR(waiter, &woken);
  portYIELD_FROM_ISR(woken);
}

}  // namespace

bool UsbLink::beginWaiting() {
  waiter = xTaskGetCurrentTaskHandle();
  usb_serial_jtag_ll_disable_intr_mask(USB_SERIAL_JTAG_LL_INTR_MASK);
  return esp_intr_alloc(ETS_USB_SERIAL_JTAG_INTR_SOURCE, 0, onPacket, nullptr, nullptr) == ESP_OK;
}

void UsbLink::waitForData(uint32_t timeoutMs) {
  // Clear first, then look: a packet landing in between sets the status again and fires at once.
  usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT);
  if (usb_serial_jtag_ll_rxfifo_data_available()) return;
  usb_serial_jtag_ll_ena_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT);
  ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(timeoutMs));
  usb_serial_jtag_ll_disable_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT);
}

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
