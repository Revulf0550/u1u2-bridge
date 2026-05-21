"""CRSF (Crossfire / ExpressLRS) — упаковка RC каналов в кадр + CRC8.

Реализует подмножество протокола CRSF, необходимое для отправки RC каналов
от u1-drone (joystick) к ELRS-передатчику на u2-pi через UART (после UDP-моста).

Кадр RC_CHANNELS_PACKED::

    [0xC8][0x18][0x16][22-byte payload][CRC8] = 26 байт

- ``0xC8`` — CRSF-адрес "Flight Controller" (sync byte).
- ``0x18`` (=24) — длина оставшейся части кадра: type(1) + payload(22) + crc(1).
- ``0x16`` — тип ``RC_CHANNELS_PACKED``.
- payload — 16 каналов по 11 бит, little-endian bit-stream → ровно 22 байта.
- CRC8 — полином ``0xD5`` (DVB-S2), init 0x00, считается от ``[type + payload]``
  (НЕ включает sync и length).

ELRS-диапазон значений канала (см. ExpressLRS ``src/lib/CrsfProtocol/crsf_protocol.h``)::

    172   — нижний край канала (PWM ≈ 988  µs)
    992   — центр              (PWM   1500 µs)
    1811  — верхний край        (PWM ≈ 2012 µs)

Reference:
    https://github.com/ExpressLRS/ExpressLRS — ``src/lib/CrsfProtocol/crsf_protocol.h``
    и ``src/lib/CrsfProtocol/crc.cpp``.
"""

from __future__ import annotations

from collections.abc import Sequence

CRSF_SYNC_FC: int = 0xC8
CRSF_TYPE_RC_CHANNELS_PACKED: int = 0x16

_CHANNEL_COUNT: int = 16
_CHANNEL_BITS: int = 11
_CHANNEL_MASK: int = (1 << _CHANNEL_BITS) - 1  # 0x7FF = 2047
_PAYLOAD_LEN: int = (_CHANNEL_COUNT * _CHANNEL_BITS) // 8  # 22

# Длина-байт кадра: type(1) + payload(22) + crc(1) = 24 = 0x18.
_FRAME_LEN_BYTE: int = 1 + _PAYLOAD_LEN + 1

_CRC8_POLY: int = 0xD5


def crc8(data: bytes) -> int:
    """CRC8-DVB-S2: полином 0xD5, init 0x00, без финального XOR.

    Совместим с ExpressLRS ``CrsfProtocol/crc.cpp``. Используется для
    контрольной суммы всех CRSF-кадров.
    """
    crc: int = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ _CRC8_POLY) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def pack_channels(channels: Sequence[int]) -> bytes:
    """Упаковать 16 каналов (11 бит каждый) в 22-байтный little-endian bitstream.

    Каждый канал клипуется в диапазон ``[0, 2047]`` — это **runtime-устойчивость**:
    если в управление проскочит выброс (-1 на джойстике, переполнение), мы не
    падаем, а отдаём ближайший легальный код. **Количество каналов ≠ 16** —
    это контрактная ошибка в вызывающем коде, ``ValueError``.

    Layout: канал 0 занимает биты 0..10, канал 1 — биты 11..21 и т.д.,
    итог сериализуется младшим байтом вперёд.
    """
    if len(channels) != _CHANNEL_COUNT:
        raise ValueError(f"expected exactly {_CHANNEL_COUNT} channels, got {len(channels)}")
    bits: int = 0
    for i, ch in enumerate(channels):
        clipped = max(0, min(_CHANNEL_MASK, ch))
        bits |= clipped << (i * _CHANNEL_BITS)
    return bits.to_bytes(_PAYLOAD_LEN, "little")


def build_rc_frame(channels: Sequence[int]) -> bytes:
    """Собрать полный CRSF-кадр ``RC_CHANNELS_PACKED`` (26 байт).

    Структура: ``sync(0xC8) | len(0x18) | type(0x16) | payload(22) | crc8``.
    CRC считается от ``[type + payload]``, НЕ включает sync и length.
    """
    payload = pack_channels(channels)
    body = bytes([CRSF_TYPE_RC_CHANNELS_PACKED]) + payload
    crc = crc8(body)
    return bytes([CRSF_SYNC_FC, _FRAME_LEN_BYTE]) + body + bytes([crc])
