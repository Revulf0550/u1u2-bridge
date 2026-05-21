"""Unit-тесты для `common.crsf_telemetry` — парсер и TelemetryState.

Все wire-формат байты собираются хелпером ``_build_frame`` поверх
``common.crsf.crc8`` — иначе тест становится зеркалом самого CRC,
а не валидацией парсера на реальных кадрах.
"""

from __future__ import annotations

import logging
import struct
from typing import TYPE_CHECKING

import pytest
from common.crsf import CRSF_SYNC_FC, crc8
from common.crsf_telemetry import (
    CRSF_FT_ATTITUDE,
    CRSF_FT_BATTERY_SENSOR,
    CRSF_FT_FLIGHT_MODE,
    CRSF_FT_GPS,
    CRSF_FT_LINK_STATISTICS,
    TX_POWER_MW,
    TX_POWER_UNKNOWN,
    Attitude,
    BatterySensor,
    CrsfTelemetryParser,
    FlightMode,
    Gps,
    LinkStatistics,
    ParsedFrame,
    TelemetryState,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


# --- Frame builder helper -------------------------------------------------


def _build_frame(frame_type: int, payload: bytes) -> bytes:
    """Собрать валидный CRSF-кадр: sync | len | type | payload | crc."""
    body = bytes([frame_type]) + payload
    length = len(body) + 1  # +1 for crc
    return bytes([CRSF_SYNC_FC, length]) + body + bytes([crc8(body)])


def _make_link_payload(
    *,
    rssi1: int = 80,
    rssi2: int = 85,
    lq: int = 100,
    snr: int = -3,
    antenna: int = 0,
    rf_mode: int = 2,
    tx_power_enum: int = 3,
    drssi: int = 90,
    dlq: int = 95,
    dsnr: int = -4,
) -> bytes:
    return struct.pack(
        ">BBBbBBBBBb", rssi1, rssi2, lq, snr, antenna, rf_mode, tx_power_enum, drssi, dlq, dsnr
    )


def _make_battery_payload(
    *,
    voltage_dv: int = 168,  # 16.8 V (4S full)
    current_da: int = 152,  # 15.2 A
    used_mah: int = 0x123456,
    remaining: int = 87,
) -> bytes:
    return struct.pack(
        ">HHBBBB",
        voltage_dv,
        current_da,
        (used_mah >> 16) & 0xFF,
        (used_mah >> 8) & 0xFF,
        used_mah & 0xFF,
        remaining,
    )


def _make_gps_payload(
    *,
    lat_e7: int = 555512345,
    lon_e7: int = 829987654,
    gs_dkmh: int = 850,  # 85.0 km/h
    hdg_cdeg: int = 12000,  # 120.00 deg
    alt_raw: int = 1525,  # → 525 m
    sats: int = 12,
) -> bytes:
    return struct.pack(">iiHHHB", lat_e7, lon_e7, gs_dkmh, hdg_cdeg, alt_raw, sats)


def _make_attitude_payload(*, pitch: int = 100, roll: int = -200, yaw: int = 31415) -> bytes:
    return struct.pack(">hhh", pitch, roll, yaw)


def _silent_log() -> logging.Logger:
    """Logger, который не выводит WARNING в тестовом stderr."""
    log_ = logging.getLogger("test-telemetry")
    log_.setLevel(logging.CRITICAL)
    return log_


# --- LinkStatistics --------------------------------------------------------


class TestLinkStatistics:
    def test_parse_valid_frame(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frame_bytes = _build_frame(CRSF_FT_LINK_STATISTICS, _make_link_payload())
        frames = parser.feed(frame_bytes)
        assert len(frames) == 1
        assert frames[0].frame_type == CRSF_FT_LINK_STATISTICS
        payload = frames[0].payload
        assert isinstance(payload, LinkStatistics)
        assert payload.uplink_rssi_1_dbm == -80  # wire 80 → actual -80 dBm
        assert payload.uplink_rssi_2_dbm == -85
        assert payload.uplink_lq == 100
        assert payload.uplink_snr_db == -3  # signed
        assert payload.diversity_antenna == 0
        assert payload.rf_mode == 2
        assert payload.uplink_tx_power_mw == TX_POWER_MW[3]  # 100 mW
        assert payload.downlink_rssi_dbm == -90
        assert payload.downlink_lq == 95
        assert payload.downlink_snr_db == -4

    def test_tx_power_unknown_enum_falls_back(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(
            _build_frame(CRSF_FT_LINK_STATISTICS, _make_link_payload(tx_power_enum=99))
        )
        assert len(frames) == 1
        payload = frames[0].payload
        assert isinstance(payload, LinkStatistics)
        assert payload.uplink_tx_power_mw == TX_POWER_UNKNOWN

    def test_tx_power_known_values(self) -> None:
        for enum_idx, expected_mw in TX_POWER_MW.items():
            parser = CrsfTelemetryParser(_silent_log())
            frames = parser.feed(
                _build_frame(CRSF_FT_LINK_STATISTICS, _make_link_payload(tx_power_enum=enum_idx))
            )
            assert len(frames) == 1
            payload = frames[0].payload
            assert isinstance(payload, LinkStatistics)
            assert payload.uplink_tx_power_mw == expected_mw, f"enum {enum_idx}"


# --- BatterySensor --------------------------------------------------------


class TestBatterySensor:
    def test_parse_valid_frame(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(_build_frame(CRSF_FT_BATTERY_SENSOR, _make_battery_payload()))
        assert len(frames) == 1
        payload = frames[0].payload
        assert isinstance(payload, BatterySensor)
        assert payload.voltage_v == pytest.approx(16.8)
        assert payload.current_a == pytest.approx(15.2)
        assert payload.used_capacity_mah == 0x123456
        assert payload.remaining_percent == 87

    def test_zero_battery(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(
            _build_frame(
                CRSF_FT_BATTERY_SENSOR,
                _make_battery_payload(voltage_dv=0, current_da=0, used_mah=0, remaining=0),
            )
        )
        payload = frames[0].payload
        assert isinstance(payload, BatterySensor)
        assert payload.voltage_v == 0.0
        assert payload.remaining_percent == 0


# --- FlightMode -----------------------------------------------------------


class TestFlightMode:
    def test_null_terminated_string(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(_build_frame(CRSF_FT_FLIGHT_MODE, b"ANGLE\x00"))
        payload = frames[0].payload
        assert isinstance(payload, FlightMode)
        assert payload.mode == "ANGLE"

    def test_null_terminator_with_trailing_garbage(self) -> None:
        # Иногда FC шлёт padding после null-байта; парсер должен обрезать.
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(_build_frame(CRSF_FT_FLIGHT_MODE, b"ACRO\x00JUNK"))
        payload = frames[0].payload
        assert isinstance(payload, FlightMode)
        assert payload.mode == "ACRO"

    def test_no_null_terminator_returns_full_string(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(_build_frame(CRSF_FT_FLIGHT_MODE, b"HORIZ"))
        payload = frames[0].payload
        assert isinstance(payload, FlightMode)
        assert payload.mode == "HORIZ"


# --- GPS / Attitude --------------------------------------------------------


class TestGps:
    def test_parse_valid_frame(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(_build_frame(CRSF_FT_GPS, _make_gps_payload()))
        payload = frames[0].payload
        assert isinstance(payload, Gps)
        assert payload.latitude_deg == pytest.approx(55.5512345)
        assert payload.longitude_deg == pytest.approx(82.9987654)
        assert payload.ground_speed_kmh == pytest.approx(85.0)
        assert payload.heading_deg == pytest.approx(120.0)
        assert payload.altitude_m == 525  # 1525 - 1000
        assert payload.satellites == 12

    def test_altitude_offset_decoded(self) -> None:
        # altitude wire = 1000 → actual 0 m (sea level).
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(_build_frame(CRSF_FT_GPS, _make_gps_payload(alt_raw=1000)))
        payload = frames[0].payload
        assert isinstance(payload, Gps)
        assert payload.altitude_m == 0


class TestAttitude:
    def test_parse_valid_frame(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frames = parser.feed(_build_frame(CRSF_FT_ATTITUDE, _make_attitude_payload()))
        payload = frames[0].payload
        assert isinstance(payload, Attitude)
        assert payload.pitch_rad == pytest.approx(0.01)
        assert payload.roll_rad == pytest.approx(-0.02)
        assert payload.yaw_rad == pytest.approx(3.1415)


# --- Stream behaviour: multi-frame, partial, resync, bad CRC --------------


class TestStreamBehaviour:
    def test_empty_feed_returns_no_frames(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        assert parser.feed(b"") == []
        assert parser.feed(b"") == []

    def test_multiple_frames_in_one_feed(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        f1 = _build_frame(CRSF_FT_LINK_STATISTICS, _make_link_payload())
        f2 = _build_frame(CRSF_FT_BATTERY_SENSOR, _make_battery_payload())
        f3 = _build_frame(CRSF_FT_FLIGHT_MODE, b"ACRO\x00")
        frames = parser.feed(f1 + f2 + f3)
        assert len(frames) == 3
        assert [f.frame_type for f in frames] == [
            CRSF_FT_LINK_STATISTICS,
            CRSF_FT_BATTERY_SENSOR,
            CRSF_FT_FLIGHT_MODE,
        ]
        assert parser.buffered == 0

    def test_partial_frame_buffered_until_completed(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        frame = _build_frame(CRSF_FT_LINK_STATISTICS, _make_link_payload())
        split = len(frame) // 2
        frames_part1 = parser.feed(frame[:split])
        assert frames_part1 == []
        assert parser.buffered == split  # ждём остальное
        frames_part2 = parser.feed(frame[split:])
        assert len(frames_part2) == 1
        assert parser.buffered == 0

    def test_partial_frame_split_byte_by_byte(self) -> None:
        # Стресс-кейс: каждый байт — отдельный feed. Имитация UART с маленьким
        # read-chunk-size. Парсер должен дожить до полного кадра без потерь.
        parser = CrsfTelemetryParser(_silent_log())
        frame = _build_frame(CRSF_FT_LINK_STATISTICS, _make_link_payload())
        out: list[ParsedFrame] = []
        for byte in frame:
            out.extend(parser.feed(bytes([byte])))
        assert len(out) == 1

    def test_bad_sync_byte_resyncs_to_next_valid_frame(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        good = _build_frame(CRSF_FT_BATTERY_SENSOR, _make_battery_payload())
        # Мусор перед валидным кадром: пара случайных байт без 0xC8.
        frames = parser.feed(b"\x00\xaa\xbb" + good)
        assert len(frames) == 1
        assert frames[0].frame_type == CRSF_FT_BATTERY_SENSOR

    def test_bad_crc_frame_discarded_with_warning(self, mocker: MockerFixture) -> None:
        mock_log = mocker.MagicMock(spec=logging.Logger)
        parser = CrsfTelemetryParser(mock_log)
        good = _build_frame(CRSF_FT_BATTERY_SENSOR, _make_battery_payload())
        bad = bytearray(good)
        bad[-1] ^= 0xFF  # портим CRC
        # Скармливаем bad затем good — после ресинка парсер должен поймать good.
        frames = parser.feed(bytes(bad) + good)
        # bad дропнут, good должен пройти (sync байт у good — следующий 0xC8).
        assert len(frames) == 1
        assert frames[0].frame_type == CRSF_FT_BATTERY_SENSOR
        # WARNING вызван хотя бы один раз.
        warnings = [c for c in mock_log.method_calls if c[0] == "warning"]
        assert any("CRC" in str(c) for c in warnings), f"no CRC warning in {warnings}"

    def test_invalid_len_byte_resyncs(self, mocker: MockerFixture) -> None:
        mock_log = mocker.MagicMock(spec=logging.Logger)
        parser = CrsfTelemetryParser(mock_log)
        # 0xC8 0xFF (len=255 > MAX) — мусор. Затем валидный кадр.
        good = _build_frame(CRSF_FT_FLIGHT_MODE, b"ACRO\x00")
        frames = parser.feed(bytes([CRSF_SYNC_FC, 0xFF, 0x00, 0x00]) + good)
        assert len(frames) == 1
        assert frames[0].frame_type == CRSF_FT_FLIGHT_MODE
        assert any("len" in str(c).lower() for c in mock_log.method_calls)

    def test_unknown_frame_type_silently_consumed(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        # type=0x99 — нам неизвестен. Кадр валиден по CRC.
        unknown_frame = _build_frame(0x99, b"\x01\x02\x03")
        good = _build_frame(CRSF_FT_BATTERY_SENSOR, _make_battery_payload())
        frames = parser.feed(unknown_frame + good)
        # unknown пропущен, good на месте.
        assert len(frames) == 1
        assert frames[0].frame_type == CRSF_FT_BATTERY_SENSOR

    def test_wrong_size_payload_for_known_type_logged_and_skipped(
        self, mocker: MockerFixture
    ) -> None:
        mock_log = mocker.MagicMock(spec=logging.Logger)
        parser = CrsfTelemetryParser(mock_log)
        # LINK_STATISTICS требует 10 байт payload — даём 5.
        bad_size = _build_frame(CRSF_FT_LINK_STATISTICS, b"\x00\x01\x02\x03\x04")
        frames = parser.feed(bad_size)
        assert frames == []
        assert any("decode failed" in str(c) for c in mock_log.method_calls), (
            f"no decode warning in {mock_log.method_calls}"
        )

    def test_only_sync_byte_buffered_no_crash(self) -> None:
        parser = CrsfTelemetryParser(_silent_log())
        assert parser.feed(bytes([CRSF_SYNC_FC])) == []
        assert parser.buffered == 1  # ждём len и далее


# --- TelemetryState --------------------------------------------------------


class TestTelemetryStateApply:
    def test_apply_link_statistics_updates_link_and_ts(self) -> None:
        state = TelemetryState()
        assert state.link is None and state.link_ts is None
        payload = LinkStatistics(
            uplink_rssi_1_dbm=-80,
            uplink_rssi_2_dbm=-85,
            uplink_lq=100,
            uplink_snr_db=-3,
            diversity_antenna=0,
            rf_mode=2,
            uplink_tx_power_mw=100,
            downlink_rssi_dbm=-90,
            downlink_lq=95,
            downlink_snr_db=-4,
        )
        state.apply(ParsedFrame(frame_type=CRSF_FT_LINK_STATISTICS, payload=payload), now=12.5)
        assert state.link is payload
        assert state.link_ts == 12.5
        # Другие поля не тронуты.
        assert state.battery is None and state.flight_mode is None

    def test_apply_battery_updates_only_battery(self) -> None:
        state = TelemetryState()
        battery = BatterySensor(
            voltage_v=16.8, current_a=15.2, used_capacity_mah=1234, remaining_percent=87
        )
        state.apply(ParsedFrame(frame_type=CRSF_FT_BATTERY_SENSOR, payload=battery), now=100.0)
        assert state.battery is battery
        assert state.battery_ts == 100.0
        assert state.link is None and state.link_ts is None

    def test_apply_flight_mode(self) -> None:
        state = TelemetryState()
        state.apply(
            ParsedFrame(frame_type=CRSF_FT_FLIGHT_MODE, payload=FlightMode(mode="ANGLE")),
            now=42.0,
        )
        assert state.flight_mode is not None
        assert state.flight_mode.mode == "ANGLE"
        assert state.flight_mode_ts == 42.0

    def test_apply_overwrites_previous_value(self) -> None:
        state = TelemetryState()
        b1 = BatterySensor(
            voltage_v=16.8, current_a=15.0, used_capacity_mah=100, remaining_percent=90
        )
        b2 = BatterySensor(
            voltage_v=15.5, current_a=20.0, used_capacity_mah=500, remaining_percent=70
        )
        state.apply(ParsedFrame(frame_type=CRSF_FT_BATTERY_SENSOR, payload=b1), now=10.0)
        state.apply(ParsedFrame(frame_type=CRSF_FT_BATTERY_SENSOR, payload=b2), now=20.0)
        assert state.battery is b2
        assert state.battery_ts == 20.0


class TestTelemetryStateStale:
    def test_none_ts_is_stale(self) -> None:
        assert TelemetryState.is_stale(None, now=100.0, threshold_s=5.0) is True

    def test_recent_ts_is_fresh(self) -> None:
        assert TelemetryState.is_stale(99.0, now=100.0, threshold_s=5.0) is False

    def test_threshold_boundary_is_fresh(self) -> None:
        # diff = exactly threshold → не stale (строгое сравнение >).
        assert TelemetryState.is_stale(95.0, now=100.0, threshold_s=5.0) is False

    def test_old_ts_is_stale(self) -> None:
        assert TelemetryState.is_stale(50.0, now=100.0, threshold_s=5.0) is True
