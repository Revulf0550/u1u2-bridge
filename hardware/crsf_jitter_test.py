"""CRSF jitter / throughput test для 74HC14N инвертора.

Расширенная версия smoke-теста с измерением jitter (stddev интервалов),
throughput (B/s, % от 420k baud) и min/max интервалов между пакетами.
Полезно для диагностики UART driver и scheduler проблем.

Норма на u2-pi:
    rate: 249.5 - 250.5 Hz
    interval: 4.00 ± < 0.2 ms
    min/max: 3.8 - 4.2 ms
    throughput: ~6500 B/s

Запуск на u2-pi:
    sudo python3 ~/hardware/crsf_jitter_test.py
    # Ctrl+C через 30+ секунд для итоговой статистики

Деплой с ноута (из корня репо):
    scp hardware/crsf_jitter_test.py ubuntu@192.168.31.100:~/hardware/
"""

import logging
import signal
import statistics
import time
from types import FrameType

import serial

CRSF_BAUD = 420_000
CRSF_PERIOD = 0.004  # 250 Hz target
CRSF_PACKET_SIZE = 26  # bytes per RC frame
SERIAL_DEV = "/dev/ttyS7"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("crsf-jitter")


def crc8(data: bytes, poly: int = 0xD5) -> int:
    """CRSF CRC8, polynomial 0xD5, init 0x00, no reflection."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crsf_rc_packet(roll: int = 992) -> bytes:
    """Собрать CRSF RC frame. `roll` задаёт значение канала 1 (центр = 992)."""
    channels = [roll] + [992] * 15
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
    """Основной цикл с измерением интервалов между пакетами."""
    stop = {"flag": False}

    def on_sig(_signum: int, _frame: FrameType | None) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_sig)
    signal.signal(signal.SIGINT, on_sig)

    ser = serial.Serial(SERIAL_DEV, CRSF_BAUD)
    log.info(
        ">>> CRSF %d baud, target 250 Hz, pkt %d bytes",
        CRSF_BAUD,
        CRSF_PACKET_SIZE,
    )
    log.info(
        ">>> bandwidth target = %d B/s = %d bits/s",
        CRSF_PACKET_SIZE * 250,
        CRSF_PACKET_SIZE * 250 * 8,
    )

    n = 0
    start = time.perf_counter()
    next_tick = start + CRSF_PERIOD
    intervals: list[float] = []
    prev_t = start

    try:
        while not stop["flag"]:
            pkt = crsf_rc_packet()
            ser.write(pkt)
            n += 1
            now = time.perf_counter()
            intervals.append((now - prev_t) * 1000)  # ms
            prev_t = now
            while time.perf_counter() < next_tick and not stop["flag"]:
                pass
            next_tick += CRSF_PERIOD
            if n % 250 == 0:
                elapsed = now - start
                recent = intervals[-250:]
                avg_ms = sum(recent) / len(recent)
                jitter_ms = statistics.stdev(recent)
                min_ms = min(recent)
                max_ms = max(recent)
                bytes_per_sec = (n * CRSF_PACKET_SIZE) / elapsed
                log.info(
                    "t=%5.1fs pkts=%d rate=%.1fHz "
                    "interval=%.2f±%.2fms [%.2f..%.2f] thru=%.0fB/s",
                    elapsed,
                    n,
                    n / elapsed,
                    avg_ms,
                    jitter_ms,
                    min_ms,
                    max_ms,
                    bytes_per_sec,
                )
    finally:
        elapsed = time.perf_counter() - start
        if intervals:
            log.info(">>> FINAL: %d packets in %.1fs", n, elapsed)
            log.info(">>> rate avg: %.1f Hz", n / elapsed)
            log.info(
                ">>> interval: %.3fms avg, %.3fms stddev, min %.3f, max %.3f",
                sum(intervals) / len(intervals),
                statistics.stdev(intervals),
                min(intervals),
                max(intervals),
            )
            log.info(
                ">>> throughput: %.0f B/s = %.0f bits/s (%.1f%% of %d baud)",
                (n * CRSF_PACKET_SIZE) / elapsed,
                (n * CRSF_PACKET_SIZE * 8) / elapsed,
                (n * CRSF_PACKET_SIZE * 10) / elapsed / CRSF_BAUD * 100,
                CRSF_BAUD,
            )
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
