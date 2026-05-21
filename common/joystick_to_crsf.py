#!/usr/bin/env python3
"""Joystick (HID/evdev) → CRSF UDP отправитель для u1-drone.

Читает события джойстика с ``/dev/input/eventN`` через python3-evdev,
маппит оси на 16 CRSF-каналов, упаковывает в кадр ``RC_CHANNELS_PACKED``
и шлёт UDP-пакетами на u2-pi с заданной частотой (default 250 Hz).

Главный цикл — select-based с deadline-математикой на ``time.monotonic()``
(тот же паттерн, что в ``common.crsf_bridge``). При отвале устройства
(USB unplug → OSError на read) — закрываем device, перестаём слать
CRSF (FC сам уходит в failsafe по timeout), раз в секунду пробуем
переоткрыть; при успехе — каналы сбрасываются в центр (992),
чтобы не «вылетел» с устаревшим положением стика.

Маппинг осей → CRSF-каналов:

    ABS_X        → ch0   ABS_RY       → ch4
    ABS_Y        → ch1   ABS_RZ       → ch5
    ABS_Z        → ch2   ABS_THROTTLE → ch6
    ABS_RX       → ch3   ABS_RUDDER   → ch7

Каналы 8..15 фиксируются в 992 (центр) — переключатели/AUX не маппятся в v1.

Диапазон каждой оси берётся из ``device.capabilities()[EV_ABS]`` при
открытии устройства. Значение нормализуется в ELRS-диапазон 172..1811.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import select
import signal
import socket
import sys
import time
from dataclasses import dataclass, field
from types import FrameType
from typing import TYPE_CHECKING, Any

from common.crsf import build_rc_frame

if TYPE_CHECKING:
    from evdev import InputDevice

# Linux input-event-codes (стабильные, см. <linux/input-event-codes.h>).
# Дублируем здесь, чтобы модуль импортировался без evdev (Windows dev-машина).
EV_ABS: int = 0x03
ABS_X: int = 0x00
ABS_Y: int = 0x01
ABS_Z: int = 0x02
ABS_RX: int = 0x03
ABS_RY: int = 0x04
ABS_RZ: int = 0x05
ABS_THROTTLE: int = 0x06
ABS_RUDDER: int = 0x07

AXIS_TO_CHANNEL: dict[int, int] = {
    ABS_X: 0,
    ABS_Y: 1,
    ABS_Z: 2,
    ABS_RX: 3,
    ABS_RY: 4,
    ABS_RZ: 5,
    ABS_THROTTLE: 6,
    ABS_RUDDER: 7,
}

ELRS_MIN: int = 172
ELRS_MAX: int = 1811
ELRS_CENTER: int = 992

RECONNECT_BACKOFF_S: float = 1.0
STAT_PERIOD_S: float = 10.0
UDP_SNDBUF: int = 65_536


@dataclass
class JoystickState:
    """Состояние отправителя. Передаётся в ``_tick`` для тестируемости."""

    channels: list[int] = field(default_factory=lambda: [ELRS_CENTER] * 16)
    device: InputDevice | None = None
    axis_ranges: dict[int, tuple[int, int]] = field(default_factory=dict)
    last_reopen_ts: float = 0.0


def normalize_axis(value: int, axis_min: int, axis_max: int) -> int:
    """Линейно отобразить raw-значение оси в ELRS-диапазон [172, 1811].

    Если ``axis_min == axis_max`` (вырожденный случай / битые caps) — отдаём
    центр (992): отказ от управления через эту ось, но не падение.
    Клиппинг финального значения делает ``pack_channels`` — здесь не дублируем.
    """
    span = axis_max - axis_min
    if span <= 0:
        return ELRS_CENTER
    return ELRS_MIN + (value - axis_min) * (ELRS_MAX - ELRS_MIN) // span


def _apply_event(state: JoystickState, ev: Any) -> None:
    """Применить один evdev-event к state.channels (если это знакомая EV_ABS ось)."""
    if ev.type != EV_ABS:
        return
    ch_idx = AXIS_TO_CHANNEL.get(ev.code)
    if ch_idx is None:
        return
    rng = state.axis_ranges.get(ev.code)
    if rng is None:
        return
    state.channels[ch_idx] = normalize_axis(ev.value, rng[0], rng[1])


def _tick(
    state: JoystickState,
    sock: socket.socket,
    peer: tuple[str, int],
    log: logging.Logger,
) -> int:
    """Один тик отправки: сдренировать pending events + отослать CRSF-кадр.

    Возвращает количество отправленных байт (0 если устройство закрыто
    или send упал). При OSError на ``device.read()`` (USB отвал) — закрывает
    device и ставит ``state.device = None``; CRSF не шлём, FC уходит в failsafe.
    """
    if state.device is not None:
        try:
            for ev in state.device.read():
                _apply_event(state, ev)
        except BlockingIOError:
            pass
        except OSError as e:
            log.warning("evdev read failed: %s — closing device", e)
            with contextlib.suppress(OSError, AttributeError):
                state.device.close()
            state.device = None

    if state.device is None:
        return 0

    frame = build_rc_frame(state.channels)
    try:
        sock.sendto(frame, peer)
    except (BlockingIOError, OSError) as e:
        log.warning("udp send failed: %s", e)
        return 0
    return len(frame)


def open_device(path: str) -> tuple[InputDevice | None, dict[int, tuple[int, int]]]:
    """Открыть evdev-устройство и собрать диапазоны его EV_ABS осей.

    Возвращает ``(device, axis_ranges)``. Если открыть не удалось — ``(None, {})``.
    Локальный импорт ``evdev`` — пакет ставится только на Linux (``python3-evdev``).
    """
    import evdev  # noqa: PLC0415 — local import: Windows dev-машина не имеет evdev

    try:
        device = evdev.InputDevice(path)
    except (OSError, FileNotFoundError):
        return None, {}
    axis_ranges: dict[int, tuple[int, int]] = {}
    caps = device.capabilities()
    for code, info in caps.get(EV_ABS, []):
        axis_ranges[code] = (info.min, info.max)
    return device, axis_ranges


def _try_reopen(state: JoystickState, path: str, log: logging.Logger, now: float) -> None:
    """Попытаться переоткрыть device, если он закрыт и прошёл backoff.

    При успехе — сбрасывает channels в центр (992). Это safety-выбор: после
    реконнекта стика последняя его позиция могла устареть (за время отвала
    оператор мог дёрнуть ручку), безопаснее стартовать от центра.
    """
    if state.device is not None:
        return
    if now - state.last_reopen_ts < RECONNECT_BACKOFF_S:
        return
    state.last_reopen_ts = now
    dev, ranges = open_device(path)
    if dev is None:
        return
    state.device = dev
    state.axis_ranges = ranges
    state.channels = [ELRS_CENTER] * 16
    log.info("evdev opened: %s (axes=%s)", path, sorted(ranges.keys()))


def open_udp_send() -> socket.socket:
    """UDP send-only сокет: AF_INET/DGRAM, REUSEADDR, SNDBUF=64K, non-blocking.

    Не bind'имся на listen-адрес — telemetry-канала пока нет, шлём в одну сторону.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, UDP_SNDBUF)
    sock.setblocking(False)
    return sock


def parse_addr(s: str) -> tuple[str, int]:
    """'host:port' → (host, port). rsplit для совместимости с IPv6 в '[::1]:port'."""
    host, port = s.rsplit(":", 1)
    return host, int(port)


def main() -> int:
    """CLI + главный цикл: select по device.fd с timeout до следующего tick'а."""
    p = argparse.ArgumentParser()
    p.add_argument(
        "--device",
        default=os.environ.get("DEVICE", "/dev/input/event0"),
        help="evdev-устройство джойстика (default: $DEVICE или /dev/input/event0)",
    )
    p.add_argument("--peer", required=True, help="host:port u2-pi для CRSF-кадров")
    p.add_argument("--rate", type=int, default=250, help="частота отправки CRSF, Hz")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("joystick-to-crsf")

    try:
        peer = parse_addr(args.peer)
    except ValueError as e:
        log.error("invalid --peer %r: %s", args.peer, e)
        return 1

    period = 1.0 / args.rate
    log.info(
        "device=%s peer=%s:%d rate=%d Hz (period=%.4f s)",
        args.device,
        peer[0],
        peer[1],
        args.rate,
        period,
    )

    sock = open_udp_send()
    state = JoystickState()

    stop = {"flag": False}

    def on_sig(_signum: int, _frame: FrameType | None) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_sig)
    signal.signal(signal.SIGINT, on_sig)

    tx_bytes = 0
    last_stat = time.monotonic()
    next_tick = time.monotonic() + period

    while not stop["flag"]:
        now = time.monotonic()
        _try_reopen(state, args.device, log, now)

        timeout = max(0.0, next_tick - now)
        fds = [state.device.fd] if state.device is not None else []
        try:
            select.select(fds, [], [], timeout)
        except (InterruptedError, OSError):
            continue

        now = time.monotonic()
        if now >= next_tick:
            tx_bytes += _tick(state, sock, peer, log)
            next_tick += period
            # Если отстали (например, заснули) — не копим долг, ресинкаемся.
            if next_tick < now:
                next_tick = now + period

        if now - last_stat >= STAT_PERIOD_S:
            log.info("udp tx=%d B/s", int(tx_bytes / STAT_PERIOD_S))
            tx_bytes = 0
            last_stat = now

    log.info("shutting down")
    if state.device is not None:
        with contextlib.suppress(OSError):
            state.device.close()
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
