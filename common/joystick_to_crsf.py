#!/usr/bin/env python3
"""Joystick (HID/evdev) → CRSF UDP отправитель для u1-drone.

Читает события джойстика с ``/dev/input/eventN`` через python3-evdev,
маппит оси/свичи на 16 CRSF-каналов через TOML-конфиг ``CHANNEL_MAP_PATH``
(см. :mod:`common.channel_map`), упаковывает в кадр ``RC_CHANNELS_PACKED``
и шлёт UDP-пакетами на u2-pi с заданной частотой (default 250 Hz).

Главный цикл — select-based с deadline-математикой на ``time.monotonic()``
(тот же паттерн, что в :mod:`common.crsf_bridge`). При отвале устройства
(USB unplug → OSError на read) — закрываем device, перестаём слать CRSF
(FC сам уходит в failsafe по timeout), раз в секунду пробуем переоткрыть;
при успехе — raw_state сбрасывается в пустое, каналы пересчитываются
через ``apply_mapping({}, config)`` (центрированные оси → 992, throttle и
свичи → 172 = disarm-safe), чтобы не выстрелить устаревшим положением стика.

Два режима маппинга:

1. **Config (production)**: ``CHANNEL_MAP_PATH`` указывает на валидный TOML
   из :mod:`common.channel_map`. Полная калибровка + 3 свича (arm/mode/beeper).
2. **Legacy fallback**: если конфиг не найден / не парсится — WARNING в лог
   и используется линейный 1:1 маппинг осей 0..7 → CRSF-каналов 0..7,
   диапазон осей берётся из ``device.capabilities()[EV_ABS]``. Свичи не
   маппятся (каналы 8..15 = 992). Этот режим — для разработки и smoke-теста
   без конфига; полётов с ним избегать.

В обоих режимах ``state.channels`` — единственный источник истины для
сериализатора, обновляется внутри ``_apply_event`` сразу при поступлении
event'а (per-config-path) или per-event scale (legacy path).
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
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Any

from common.channel_map import (
    CRSF_CH_HIGH,
    CRSF_CH_LOW,
    CRSF_CH_MID,
    ChannelMapConfig,
    ChannelMapError,
    apply_mapping,
    load_config,
)
from common.crsf import build_rc_frame

if TYPE_CHECKING:
    from evdev import InputDevice

# Linux input-event-codes (стабильные, см. <linux/input-event-codes.h>).
# Дублируем здесь, чтобы модуль импортировался без evdev (Windows dev-машина).
EV_KEY: int = 0x01
EV_ABS: int = 0x03

# Оси (EV_ABS)
ABS_X: int = 0x00
ABS_Y: int = 0x01
ABS_Z: int = 0x02
ABS_RX: int = 0x03
ABS_RY: int = 0x04
ABS_RZ: int = 0x05
ABS_THROTTLE: int = 0x06
ABS_RUDDER: int = 0x07
ABS_HAT0X: int = 0x10
ABS_HAT0Y: int = 0x11
ABS_HAT1X: int = 0x12
ABS_HAT1Y: int = 0x13
ABS_HAT2X: int = 0x14
ABS_HAT2Y: int = 0x15
ABS_HAT3X: int = 0x16
ABS_HAT3Y: int = 0x17

# Кнопки/свичи (EV_KEY) — стандартный USB-joystick HID set
BTN_TRIGGER: int = 0x120
BTN_THUMB: int = 0x121
BTN_THUMB2: int = 0x122
BTN_TOP: int = 0x123
BTN_TOP2: int = 0x124
BTN_PINKIE: int = 0x125
BTN_BASE: int = 0x126
BTN_BASE2: int = 0x127
BTN_BASE3: int = 0x128
BTN_BASE4: int = 0x129
BTN_BASE5: int = 0x12A
BTN_BASE6: int = 0x12B
BTN_DEAD: int = 0x12F

# Legacy-path: какие EV_ABS оси автоматически маппятся в CRSF-каналы 0..7,
# когда channel-map config отсутствует. Сохранено ради smoke-теста без TOML.
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

# (EV_TYPE, code) → имя для использования в channel_map config (`source` поле).
# Список покрывает стандартный USB-joystick HID profile EdgeTX joystick mode.
EVENT_CODE_NAMES: dict[tuple[int, int], str] = {
    (EV_ABS, ABS_X): "ABS_X",
    (EV_ABS, ABS_Y): "ABS_Y",
    (EV_ABS, ABS_Z): "ABS_Z",
    (EV_ABS, ABS_RX): "ABS_RX",
    (EV_ABS, ABS_RY): "ABS_RY",
    (EV_ABS, ABS_RZ): "ABS_RZ",
    (EV_ABS, ABS_THROTTLE): "ABS_THROTTLE",
    (EV_ABS, ABS_RUDDER): "ABS_RUDDER",
    (EV_ABS, ABS_HAT0X): "ABS_HAT0X",
    (EV_ABS, ABS_HAT0Y): "ABS_HAT0Y",
    (EV_ABS, ABS_HAT1X): "ABS_HAT1X",
    (EV_ABS, ABS_HAT1Y): "ABS_HAT1Y",
    (EV_ABS, ABS_HAT2X): "ABS_HAT2X",
    (EV_ABS, ABS_HAT2Y): "ABS_HAT2Y",
    (EV_ABS, ABS_HAT3X): "ABS_HAT3X",
    (EV_ABS, ABS_HAT3Y): "ABS_HAT3Y",
    (EV_KEY, BTN_TRIGGER): "BTN_TRIGGER",
    (EV_KEY, BTN_THUMB): "BTN_THUMB",
    (EV_KEY, BTN_THUMB2): "BTN_THUMB2",
    (EV_KEY, BTN_TOP): "BTN_TOP",
    (EV_KEY, BTN_TOP2): "BTN_TOP2",
    (EV_KEY, BTN_PINKIE): "BTN_PINKIE",
    (EV_KEY, BTN_BASE): "BTN_BASE",
    (EV_KEY, BTN_BASE2): "BTN_BASE2",
    (EV_KEY, BTN_BASE3): "BTN_BASE3",
    (EV_KEY, BTN_BASE4): "BTN_BASE4",
    (EV_KEY, BTN_BASE5): "BTN_BASE5",
    (EV_KEY, BTN_BASE6): "BTN_BASE6",
    (EV_KEY, BTN_DEAD): "BTN_DEAD",
}

# Сохранены ради backward-compat с существующими тестами и внешними скриптами.
ELRS_MIN: int = CRSF_CH_LOW
ELRS_MAX: int = CRSF_CH_HIGH
ELRS_CENTER: int = CRSF_CH_MID

RECONNECT_BACKOFF_S: float = 1.0
STAT_PERIOD_S: float = 10.0
UDP_SNDBUF: int = 65_536

DEFAULT_CHANNEL_MAP_PATH: str = "/etc/u1u2-bridge/channels.toml"


@dataclass
class JoystickState:
    """Состояние отправителя. Передаётся в ``_tick`` для тестируемости.

    - ``channels``: текущие 16 CRSF-значений (источник истины для отправки).
    - ``raw_state``: последние сырые значения по имени источника (config-path).
    - ``axis_ranges``: caps устройства {code → (min, max)} (legacy fallback).
    - ``config``: ``None`` — legacy mode, иначе apply_mapping per-event.
    """

    channels: list[int] = field(default_factory=lambda: [ELRS_CENTER] * 16)
    device: InputDevice | None = None
    axis_ranges: dict[int, tuple[int, int]] = field(default_factory=dict)
    raw_state: dict[str, int] = field(default_factory=dict)
    config: ChannelMapConfig | None = None
    last_reopen_ts: float = 0.0


def normalize_axis(value: int, axis_min: int, axis_max: int) -> int:
    """Legacy линейный скейл оси → ELRS [172, 1811] (fallback без TOML).

    Если ``axis_min == axis_max`` (битые caps) — отдаём центр (992), но не
    падаем. Клиппинг финального значения делает ``pack_channels`` — здесь
    не дублируем.
    """
    span = axis_max - axis_min
    if span <= 0:
        return ELRS_CENTER
    return ELRS_MIN + (value - axis_min) * (ELRS_MAX - ELRS_MIN) // span


def _recompute_channels(state: JoystickState) -> None:
    """Пересчитать ``state.channels`` через apply_mapping (только config-path)."""
    if state.config is None:
        return
    state.channels = list(apply_mapping(state.raw_state, state.config))


def _apply_event(state: JoystickState, ev: Any) -> None:  # noqa: ANN401 — evdev.InputEvent
    """Применить один evdev-event к state.

    Config-path: записывает event.value в ``state.raw_state`` под именем
    из ``EVENT_CODE_NAMES``; затем пересчитывает channels через apply_mapping.
    Legacy-path: при EV_ABS-событии для знакомой оси (AXIS_TO_CHANNEL) и
    известным диапазоном — линейный скейл напрямую в ``state.channels``.
    """
    if state.config is not None:
        name = EVENT_CODE_NAMES.get((ev.type, ev.code))
        if name is None:
            return
        state.raw_state[name] = ev.value
        _recompute_channels(state)
        return

    # Legacy fallback (config is None).
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


def _failsafe_channels(config: ChannelMapConfig | None) -> list[int]:
    """Безопасные стартовые/сброс-значения каналов.

    Config-path: ``apply_mapping({}, config)`` — каждый mapping сам решает,
    что безопасно (центр для стиков, low для throttle и свичей).
    Legacy-path: все 16 каналов = 992 (как было до Step 3.2.5).
    """
    if config is None:
        return [ELRS_CENTER] * 16
    return list(apply_mapping({}, config))


def _try_reopen(state: JoystickState, path: str, log: logging.Logger, now: float) -> None:
    """Попытаться переоткрыть device, если он закрыт и прошёл backoff.

    При успехе — сбрасывает raw_state и channels в failsafe-состояние (см.
    :func:`_failsafe_channels`). Это safety-выбор: после реконнекта стика
    последняя его позиция могла устареть (за время отвала оператор мог
    дёрнуть ручку), безопаснее стартовать от центра / disarm.
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
    state.raw_state = {}
    state.channels = _failsafe_channels(state.config)
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


def _load_channel_map(path_str: str, log: logging.Logger) -> ChannelMapConfig | None:
    """Прочитать channel-map config. При любой ошибке — WARNING и None.

    None означает "включить legacy-маппинг". Не падаем, чтобы один битый
    конфиг не убивал сервис и operator мог хотя бы загрузиться и поправить.
    """
    try:
        return load_config(Path(path_str))
    except ChannelMapError as e:
        log.warning(
            "channel map disabled (%s) — falling back to LEGACY linear axis mapping. "
            "Production flights require a valid channel map: fix and restart.",
            e,
        )
        return None


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
    p.add_argument(
        "--channel-map",
        default=os.environ.get("CHANNEL_MAP_PATH", DEFAULT_CHANNEL_MAP_PATH),
        help="путь к TOML channel-map (default: $CHANNEL_MAP_PATH или %(default)s)",
    )
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

    config = _load_channel_map(args.channel_map, log)

    period = 1.0 / args.rate
    log.info(
        "device=%s peer=%s:%d rate=%d Hz (period=%.4f s) channel_map=%s",
        args.device,
        peer[0],
        peer[1],
        args.rate,
        period,
        args.channel_map if config is not None else "(legacy linear)",
    )

    sock = open_udp_send()
    state = JoystickState(config=config, channels=_failsafe_channels(config))

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
