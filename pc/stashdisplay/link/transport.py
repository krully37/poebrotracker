"""Byte pipes to the screen: a real serial port, or an in-process pair for the simulator and tests."""

import queue
import threading
from typing import Protocol

from . import protocol as p

# What the screen shows up as: the ESP32-S3's own USB-Serial/JTAG (docs/SCOPE.md §9). Only that
# one is opened when looking for the screen. Opening a serial port can restart what is behind it
# (an Arduino, a 3D printer), and the search runs every 2 s, so other USB-serial bridges (CH340,
# CP210x) are left alone; a screen behind one of those needs its port set in `serial.port`.
SCREEN_USB_ID = (0x303A, 0x1001)


class Port(Protocol):
    name: str

    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float) -> bytes: ...  # b"" on timeout; raises OSError when unplugged
    def close(self) -> None: ...


class SerialPort:
    def __init__(self, device: str):
        import serial

        self.name = device
        self.serial = serial.Serial(device, p.BAUD, timeout=0, write_timeout=2)

    def write(self, data: bytes) -> None:
        import serial

        try:
            self.serial.write(data)
        except serial.SerialException as e:
            raise OSError(str(e)) from e

    def read(self, timeout: float) -> bytes:
        import serial

        try:
            self.serial.timeout = timeout
            first = self.serial.read(1)
            if not first:
                return b""
            return first + self.serial.read(self.serial.in_waiting)
        except serial.SerialException as e:
            raise OSError(str(e)) from e

    def close(self) -> None:
        try:
            # The ESP32-S3's native USB resets the board when DTR drops while RTS is still up,
            # which a plain close does. RTS first, then DTR, leaves the screen running.
            self.serial.rts = False
            self.serial.dtr = False
            self.serial.close()
        except Exception:
            pass


def candidate_ports(configured: str = "") -> list[str]:
    """Serial ports that may be the screen: the configured one, else those with the screen's USB id."""
    if configured:
        return [configured]
    from serial.tools import list_ports

    return [port.device for port in list_ports.comports() if (port.vid, port.pid) == SCREEN_USB_ID]


class _End:
    def __init__(self, pair: "LoopbackPair", inbox: queue.Queue, outbox: queue.Queue, name: str):
        self.pair, self.inbox, self.outbox, self.name = pair, inbox, outbox, name

    def write(self, data: bytes) -> None:
        if not self.pair.plugged:
            raise OSError("unplugged")
        self.outbox.put(bytes(data))

    def read(self, timeout: float) -> bytes:
        if not self.pair.plugged:
            raise OSError("unplugged")
        try:
            data = self.inbox.get(timeout=timeout)
        except queue.Empty:
            return b""
        while not self.inbox.empty():
            data += self.inbox.get_nowait()
        return data

    def close(self) -> None:
        pass


class LoopbackPair:
    """Two connected ends, like a USB cable. `unplug()` makes both ends fail like a pulled cable."""

    def __init__(self):
        a, b = queue.Queue(), queue.Queue()
        self.plugged = True
        self.lock = threading.Lock()
        self.pc = _End(self, a, b, "simulator")
        self.screen = _End(self, b, a, "pc")

    def unplug(self) -> None:
        self.plugged = False
        for q in (self.pc.inbox, self.screen.inbox):
            while not q.empty():
                q.get_nowait()

    def plug(self) -> None:
        self.plugged = True
