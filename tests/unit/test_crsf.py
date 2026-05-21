"""Unit-тесты для `common.crsf` — упаковка RC каналов и CRC8."""

from __future__ import annotations

import pytest
from common.crsf import (
    CRSF_SYNC_FC,
    CRSF_TYPE_RC_CHANNELS_PACKED,
    build_rc_frame,
    crc8,
    pack_channels,
)


def _unpack_channels(payload: bytes) -> list[int]:
    """Обратное `pack_channels`: 22 байта → 16 каналов по 11 бит.

    Test-helper: в production нужна только упаковка (мы шлём, не получаем).
    """
    if len(payload) != 22:
        raise ValueError("payload must be 22 bytes")
    bits = int.from_bytes(payload, "little")
    mask = (1 << 11) - 1
    return [(bits >> (i * 11)) & mask for i in range(16)]


class TestCrc8:
    def test_empty(self) -> None:
        assert crc8(b"") == 0

    def test_known_vector_123456789(self) -> None:
        # Канонический test-vector для CRC-8/DVB-S2 (poly=0xD5, init=0x00).
        # Источник: reveng CRC catalogue, проверка `check=0xBC`.
        assert crc8(b"123456789") == 0xBC


class TestPackChannels:
    def test_length(self) -> None:
        assert len(pack_channels([992] * 16)) == 22

    def test_wrong_count_raises(self) -> None:
        with pytest.raises(ValueError):
            pack_channels([992] * 15)

    def test_clipping_low(self) -> None:
        out = pack_channels([-1] + [0] * 15)
        assert _unpack_channels(out)[0] == 0

    def test_clipping_high(self) -> None:
        out = pack_channels([99999] + [0] * 15)
        assert _unpack_channels(out)[0] == 2047

    def test_round_trip(self) -> None:
        pattern = [
            172,
            992,
            1811,
            172,
            992,
            1811,
            172,
            992,
            1811,
            172,
            992,
            1811,
            172,
            992,
            1811,
            992,
        ]
        assert len(pattern) == 16
        out = pack_channels(pattern)
        assert _unpack_channels(out) == pattern


class TestBuildRcFrame:
    def test_length(self) -> None:
        assert len(build_rc_frame([992] * 16)) == 26

    def test_structure(self) -> None:
        frame = build_rc_frame([992] * 16)
        assert frame[0] == CRSF_SYNC_FC
        assert frame[1] == 0x18
        assert frame[2] == CRSF_TYPE_RC_CHANNELS_PACKED

    def test_crc_validates(self) -> None:
        frame = build_rc_frame([992] * 16)
        # CRC считается от [type + payload] = frame[2:-1].
        assert crc8(frame[2:-1]) == frame[-1]
