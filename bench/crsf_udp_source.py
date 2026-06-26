"""Синтетический CRSF UDP source — эмуляция пульта без реального джойстика.

Запускается на u1 (где НЕТ TX12), шлёт UDP-пакеты на u2,
где crsf_bridge.py пишет их в /dev/ttyS7 → 74HC14N → ELRS Ranger Micro → дрон.

Два режима (--mode):
  sweep       — каналы AETR (ch1..ch4) синусоидой с периодами 3..7 сек,
                AUX1 (ch5) ПРИНУДИТЕЛЬНО в low (CRSF_CH_LOW) — дрон не армится.
  arm-toggle  — всё в центре, AUX1 переключается low↔high каждые 5 сек.
                ВНИМАНИЕ: дрон будет армиться, винты снять обязательно.

Пример::

    python -m bench.crsf_udp_source --peer 10.8.0.7:14552 --mode sweep
    python -m bench.crsf_udp_source --peer 10.8.0.7:14552 --mode arm-toggle --rate 250
"""

from __future__ import annotations

import argparse
import logging
import math
import signal
import socket
import sys
import time
from collections.abc import Callable
from types import FrameType

from common.channel_map import CRSF_CH_HIGH, CRSF_CH_LOW, CRSF_CH_MID
from common.crsf import build_rc_frame

_CHANNEL_COUNT = 16
_STAT_PERIOD = 5.0

log = logging.getLogger("crsf-udp-source")


def parse_addr(s: str) -> tuple[str, int]:
    """``'host:port'`` → ``(host, port)``.  rsplit для совместимости с IPv6."""
    host, port_s = s.rsplit(":", 1)
    return host, int(port_s)


def channels_sweep(t: float) -> list[int]:
    """AETR качаются синусоидой с разными периодами; AUX1 в low (НЕ армить)."""
    amplitude = (CRSF_CH_HIGH - CRSF_CH_LOW) / 2 * 0.7
    periods = (4.0, 5.0, 7.0, 3.5)
    ch = [CRSF_CH_MID] * _CHANNEL_COUNT
    for i, period in enumerate(periods):
        ch[i] = int(CRSF_CH_MID + amplitude * math.sin(2 * math.pi * t / period))
    ch[4] = CRSF_CH_LOW
    return ch


def channels_arm_toggle(t: float) -> list[int]:
    """Всё в центре, AUX1 (ch5, индекс 4) переключается каждые 5 сек."""
    ch = [CRSF_CH_MID] * _CHANNEL_COUNT
    ch[4] = CRSF_CH_HIGH if int(t / 5.0) % 2 == 1 else CRSF_CH_LOW
    return ch


_MODES: dict[str, Callable[[float], list[int]]] = {
    "sweep": channels_sweep,
    "arm-toggle": channels_arm_toggle,
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--peer",
        required=True,
        help="ip:port моста на u2, например 10.8.0.7:14552",
    )
    p.add_argument("--mode", choices=sorted(_MODES), default="sweep")
    p.add_argument("--rate", type=float, default=250.0, help="частота кадров, Hz")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")

    peer = parse_addr(args.peer)
    period = 1.0 / args.rate
    gen = _MODES[args.mode]

    log.info("peer=%s:%d  mode=%s  rate=%.0f Hz", *peer, args.mode, args.rate)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    stop = {"flag": False}

    def on_sig(_signum: int, _frame: FrameType | None) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_sig)
    signal.signal(signal.SIGINT, on_sig)

    frames_sent = 0
    bytes_sent = 0
    t0 = time.monotonic()
    next_send = t0
    last_stat = t0

    while not stop["flag"]:
        now = time.monotonic()
        if now < next_send:
            time.sleep(min(next_send - now, 0.05))
            continue

        channels = gen(now - t0)
        frame = build_rc_frame(channels)
        try:
            sock.sendto(frame, peer)
            frames_sent += 1
            bytes_sent += len(frame)
        except OSError as e:
            log.warning("udp send failed: %s", e)

        next_send += period
        if now - next_send > 0.1:
            next_send = now + period

        if now - last_stat >= _STAT_PERIOD:
            elapsed = now - last_stat
            log.info(
                "sent=%d frames  (%d B/s, %.0f fps)",
                frames_sent,
                int(bytes_sent / elapsed),
                frames_sent / elapsed,
            )
            frames_sent = 0
            bytes_sent = 0
            last_stat = now

    log.info("shutting down")
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
