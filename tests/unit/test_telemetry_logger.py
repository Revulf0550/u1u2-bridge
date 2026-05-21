"""Unit-тесты для `common.telemetry_logger`.

Без monkey-patch'инга `time.monotonic` — `maybe_log(now)` принимает время
явно, что и делает логгер легко тестируемым.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from common.crsf_telemetry import (
    CRSF_FT_BATTERY_SENSOR,
    CRSF_FT_LINK_STATISTICS,
    BatterySensor,
    FlightMode,
    LinkStatistics,
    ParsedFrame,
    TelemetryState,
)
from common.telemetry_logger import TelemetryLogger

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _make_state_with_link_and_battery() -> TelemetryState:
    state = TelemetryState()
    link = LinkStatistics(
        uplink_rssi_1_dbm=-80,
        uplink_rssi_2_dbm=-85,
        uplink_lq=99,
        uplink_snr_db=-3,
        diversity_antenna=0,
        rf_mode=2,
        uplink_tx_power_mw=100,
        downlink_rssi_dbm=-90,
        downlink_lq=95,
        downlink_snr_db=-4,
    )
    battery = BatterySensor(
        voltage_v=16.8, current_a=15.2, used_capacity_mah=1234, remaining_percent=87
    )
    state.apply(ParsedFrame(frame_type=CRSF_FT_LINK_STATISTICS, payload=link), now=10.0)
    state.apply(ParsedFrame(frame_type=CRSF_FT_BATTERY_SENSOR, payload=battery), now=10.0)
    return state


# --- Rate limiting --------------------------------------------------------


class TestMaybeLog:
    def test_first_call_emits(self, mocker: MockerFixture) -> None:
        log_ = mocker.MagicMock(spec=logging.Logger)
        state = TelemetryState()
        logger = TelemetryLogger(state, log_, interval_s=1.0)
        assert logger.maybe_log(now=0.0) is True
        log_.info.assert_called_once()

    def test_repeated_call_within_interval_skipped(self, mocker: MockerFixture) -> None:
        log_ = mocker.MagicMock(spec=logging.Logger)
        logger = TelemetryLogger(TelemetryState(), log_, interval_s=1.0)
        assert logger.maybe_log(now=0.0) is True
        # Через 0.5s — ещё рано.
        assert logger.maybe_log(now=0.5) is False
        assert log_.info.call_count == 1

    def test_after_interval_emits_again(self, mocker: MockerFixture) -> None:
        log_ = mocker.MagicMock(spec=logging.Logger)
        logger = TelemetryLogger(TelemetryState(), log_, interval_s=1.0)
        logger.maybe_log(now=0.0)
        assert logger.maybe_log(now=1.0) is True  # ровно interval — эмитим
        assert logger.maybe_log(now=2.5) is True
        assert log_.info.call_count == 3

    def test_extras_passed_via_extra_kwarg(self, mocker: MockerFixture) -> None:
        log_ = mocker.MagicMock(spec=logging.Logger)
        state = _make_state_with_link_and_battery()
        logger = TelemetryLogger(state, log_, interval_s=1.0, stale_s=5.0)
        logger.maybe_log(now=11.0)  # 1s после updates, ещё fresh
        call = log_.info.call_args
        assert "extra" in call.kwargs
        assert "telemetry" in call.kwargs["extra"]
        extras = call.kwargs["extra"]["telemetry"]
        assert extras["link"] is not None
        assert extras["battery"] is not None
        assert extras["flight_mode"] is None  # ни разу не приходило


# --- snapshot_extras structure --------------------------------------------


class TestSnapshotExtras:
    def test_no_data_yields_all_none(self) -> None:
        logger = TelemetryLogger(TelemetryState(), logging.getLogger("t"))
        extras = logger.snapshot_extras(now=100.0)
        assert extras == {
            "link": None,
            "battery": None,
            "flight_mode": None,
            "gps": None,
            "attitude": None,
        }

    def test_fresh_data_has_full_payload_and_age(self) -> None:
        state = _make_state_with_link_and_battery()
        logger = TelemetryLogger(state, logging.getLogger("t"), stale_s=5.0)
        extras = logger.snapshot_extras(now=12.0)  # 2s после updates
        link = extras["link"]
        assert link is not None
        assert link["stale"] is False
        assert link["age_s"] == pytest.approx(2.0)
        assert link["uplink_lq"] == 99
        assert link["uplink_rssi_1_dbm"] == -80
        battery = extras["battery"]
        assert battery is not None
        assert battery["voltage_v"] == pytest.approx(16.8)

    def test_stale_data_marked_without_payload_fields(self) -> None:
        # Данные пришли в t=10, stale через 5s → t=20 уже stale.
        state = _make_state_with_link_and_battery()
        logger = TelemetryLogger(state, logging.getLogger("t"), stale_s=5.0)
        extras = logger.snapshot_extras(now=20.0)
        link = extras["link"]
        assert link is not None
        assert link["stale"] is True
        assert link["age_s"] == pytest.approx(10.0)
        # Поля payload не дублируются (они устарели, опаснее их вернуть как fresh).
        assert "uplink_lq" not in link
        assert "uplink_rssi_1_dbm" not in link

    def test_mixed_fresh_and_stale(self) -> None:
        state = TelemetryState()
        state.apply(
            ParsedFrame(
                frame_type=CRSF_FT_LINK_STATISTICS,
                payload=LinkStatistics(
                    uplink_rssi_1_dbm=-80,
                    uplink_rssi_2_dbm=-85,
                    uplink_lq=99,
                    uplink_snr_db=-3,
                    diversity_antenna=0,
                    rf_mode=2,
                    uplink_tx_power_mw=100,
                    downlink_rssi_dbm=-90,
                    downlink_lq=95,
                    downlink_snr_db=-4,
                ),
            ),
            now=10.0,
        )
        state.apply(
            ParsedFrame(
                frame_type=CRSF_FT_LINK_STATISTICS,
                payload=LinkStatistics(
                    uplink_rssi_1_dbm=-70,
                    uplink_rssi_2_dbm=-75,
                    uplink_lq=100,
                    uplink_snr_db=-2,
                    diversity_antenna=1,
                    rf_mode=2,
                    uplink_tx_power_mw=100,
                    downlink_rssi_dbm=-80,
                    downlink_lq=98,
                    downlink_snr_db=-3,
                ),
            ),
            now=50.0,
        )
        state.flight_mode = FlightMode(mode="ANGLE")
        state.flight_mode_ts = 10.0
        logger = TelemetryLogger(state, logging.getLogger("t"), stale_s=5.0)
        extras = logger.snapshot_extras(now=51.0)
        # link обновился в t=50, fresh
        assert extras["link"]["stale"] is False
        # flight_mode из t=10 — stale.
        assert extras["flight_mode"]["stale"] is True
