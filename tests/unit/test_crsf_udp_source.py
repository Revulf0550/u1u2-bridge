"""Тесты bench.crsf_udp_source — только режимы sweep и arm-toggle.

CRC, pack_channels, build_rc_frame уже покрыты в tests/unit/test_crsf.py.
"""

from __future__ import annotations

from bench.crsf_udp_source import channels_arm_toggle, channels_sweep
from common.channel_map import CRSF_CH_HIGH, CRSF_CH_LOW, CRSF_CH_MID

_CH_COUNT = 16


class TestChannelsSweep:
    def test_returns_16_channels(self) -> None:
        assert len(channels_sweep(0.0)) == _CH_COUNT

    def test_aux1_always_low(self) -> None:
        for t in (0.0, 1.3, 4.7, 13.9, 99.5):
            assert channels_sweep(t)[4] == CRSF_CH_LOW

    def test_values_in_valid_range(self) -> None:
        for t in (0.0, 0.5, 1.0, 2.5, 5.0, 10.0):
            for i, v in enumerate(channels_sweep(t)):
                assert CRSF_CH_LOW <= v <= CRSF_CH_HIGH, f"ch{i} out of range at t={t}: {v}"

    def test_aetr_actually_moves(self) -> None:
        samples = [channels_sweep(t) for t in (0.3, 0.8, 1.4, 2.1, 2.9, 3.6)]
        for i in range(4):
            assert any(s[i] != CRSF_CH_MID for s in samples), f"ch{i} stuck at center"

    def test_aux2_and_above_centered(self) -> None:
        ch = channels_sweep(2.5)
        for i in range(5, _CH_COUNT):
            assert ch[i] == CRSF_CH_MID


class TestChannelsArmToggle:
    def test_returns_16_channels(self) -> None:
        assert len(channels_arm_toggle(0.0)) == _CH_COUNT

    def test_aux1_low_first_window(self) -> None:
        assert channels_arm_toggle(0.0)[4] == CRSF_CH_LOW
        assert channels_arm_toggle(4.9)[4] == CRSF_CH_LOW

    def test_aux1_high_second_window(self) -> None:
        assert channels_arm_toggle(5.0)[4] == CRSF_CH_HIGH
        assert channels_arm_toggle(9.9)[4] == CRSF_CH_HIGH

    def test_aux1_low_third_window(self) -> None:
        assert channels_arm_toggle(10.0)[4] == CRSF_CH_LOW

    def test_other_channels_centered(self) -> None:
        ch = channels_arm_toggle(7.5)
        for i in range(_CH_COUNT):
            if i == 4:
                continue
            assert ch[i] == CRSF_CH_MID
