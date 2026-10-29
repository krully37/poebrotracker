"""USB speed to the screen, with the step 5 bench firmware on it (firmware env `bench`).

Run from pc/:

    .venv/Scripts/python tools/usb_bench.py COM4 [--size 1000000]

Two runs: raw (bytes sent as fast as they go) and acked (4 kB at a time, waiting for the
screen's answer before the next, as the protocol does with its chunks).
"""

import argparse
import os
import re
import time
import zlib

import serial


def run(port: serial.Serial, size: int, ack: bool) -> None:
    data = os.urandom(size)
    port.reset_input_buffer()
    port.write(f"{'usback' if ack else 'usb'} {size}\n".encode())
    line = b""
    t0 = time.time()
    while b"ready" not in line:
        line += port.read(64)
        if time.time() - t0 > 5:
            raise SystemExit(f"no answer from the bench firmware: {line!r}")
    t = time.perf_counter()
    if ack:
        for i in range(0, size, 4096):
            port.write(data[i:i + 4096])
            if port.read(1) != b"k":
                raise SystemExit(f"no ack after {i} bytes")
    else:
        port.write(data)
    port.flush()
    sent = time.perf_counter() - t
    report = b""
    while b"crc" not in report or not report.endswith(b"\n"):
        chunk = port.read(256)
        if not chunk:
            break
        report += chunk
    text = report.decode(errors="replace").strip()
    m = re.search(r"crc ([0-9a-f]{8})", text)
    crc_ok = m and int(m.group(1), 16) == zlib.crc32(data)
    print(f"{'acked' if ack else 'raw  '}: PC sent {size} bytes in {sent * 1000:.0f} ms "
          f"({size / 1024 / sent:.0f} kB/s); screen says: {text}; crc {'ok' if crc_ok else 'MISMATCH'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("port")
    ap.add_argument("--size", type=int, default=1_000_000)
    args = ap.parse_args()
    with serial.Serial(args.port, 921600, timeout=2) as port:
        # The bench may be running its start-up measurements: wait until the line is quiet.
        port.timeout = 1.5
        while port.read(4096):
            pass
        port.timeout = 2
        run(port, args.size, ack=False)
        run(port, args.size, ack=True)


if __name__ == "__main__":
    main()
