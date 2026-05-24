"""CRSF smoke-test для 74HC14N инвертора.

Шлёт CRSF RC frames @ 250 Hz, baud 420000 на /dev/ttyS7.
Критерий успеха: 2+ минуты стрима, ESP32 не уходит в config mode
(WiFi сеть 'ExpressLRS TX' не появляется).

Запуск на u2-pi:
    sudo python3 ~/hardware/crsf_smoke_test.py

Деплой с ноута (из корня репо):
    scp hardware/crsf_smoke_test.py ubuntu@192.168.31.100:~/hardware/
"""

import logging
import signal
import time
from types import FrameType

import serial

CRSF_BAUD = 420_000
CRSF_PERIOD = 0.004  # 250 Hz target
SERIAL_DEV = "/dev/ttyS7"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("crsf-smoke")


def crc8(data: bytes, poly: int = 0xD5) -> int:
    """CRSF CRC8, polynomial 0xD5, init 0x00, no reflection."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crsf_rc_packet() -> bytes:
    """Собрать CRSF RC frame с 16 каналами фиксированного значения 992 (центр)."""
    channels = [992] * 16
    payload = bytearray(22)
    bit_idx = 0
    for ch in channels:
        for b in range(11):
            if ch & (1 << b):
                payload[bit_idx // 8] |= (1 << (bit_idx % 8))
            bit_idx += 1
    body = bytes([0x16]) + bytes(payload)
    return bytes([0xC8, 24]) + body + bytes([crc8(body)])


def main() -> int:
    """Основной цикл: открыть UART, гнать CRSF на 250 Hz через busy-wait."""
    stop = {"flag": False}

    def on_sig(_signum: int, _frame: FrameType | None) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_sig)
    signal.signal(signal.SIGINT, on_sig)

    ser = serial.Serial(SERIAL_DEV, CRSF_BAUD)
    pkt = crsf_rc_packet()
    log.info(
        ">>> Sending CRSF %d baud, pkt=%s, target 250 Hz",
        CRSF_BAUD,
        pkt.hex(),
    )

    n = 0
    start = time.perf_counter()
    next_tick = start + CRSF_PERIOD
    try:
        while not stop["flag"]:
            ser.write(pkt)
            n += 1
            while time.perf_counter() < next_tick and not stop["flag"]:
                pass
            next_tick += CRSF_PERIOD
            if n % 250 == 0:
                elapsed = time.perf_counter() - start
                log.info(
                    ">>> t=%5.1fs packets=%d rate=%.0f Hz",
                    elapsed,
                    n,
                    n / elapsed,
                )
    finally:
        elapsed = time.perf_counter() - start
        log.info(
            ">>> Stopped after %d packets, %.1fs, avg %.0f Hz",
            n,
            elapsed,
            n / elapsed if elapsed > 0 else 0,
        )
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
