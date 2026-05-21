"""Unit-тесты для `common.channel_map`.

Покрытие:
- AxisMapping: линейка, центр, deadband, invert, кламп raw вне диапазона.
- SwitchMapping: 2-pos / 3-pos / momentary с дефолтными и кастомными порогами.
- load_config: валидный TOML, отсутствующие обязательные поля, дубликат канала,
  неизвестные поля, невалидный диапазон, поломанный синтаксис TOML.
- apply_mapping: незамаппленные слоты = 992; failsafe-friendly disarm.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from common.channel_map import (
    CHANNEL_COUNT,
    CRSF_CH_HIGH,
    CRSF_CH_LOW,
    CRSF_CH_MID,
    AxisMapping,
    ChannelMapConfig,
    ChannelMapError,
    SwitchMapping,
    _scale_axis,
    _scale_switch,
    apply_mapping,
    load_config,
)


def _make_centered_axis(**overrides: object) -> AxisMapping:
    base: dict[str, object] = {
        "name": "roll",
        "source": "ABS_X",
        "channel": 1,
        "min_raw": 0,
        "max_raw": 1000,
        "center_raw": 500,
        "invert": False,
        "deadband": 0,
    }
    base.update(overrides)
    return AxisMapping(**base)  # type: ignore[arg-type]


def _make_uni_axis(**overrides: object) -> AxisMapping:
    base: dict[str, object] = {
        "name": "throttle",
        "source": "ABS_RZ",
        "channel": 3,
        "min_raw": 0,
        "max_raw": 1000,
        "invert": False,
    }
    base.update(overrides)
    return AxisMapping(**base)  # type: ignore[arg-type]


# --- _scale_axis ----------------------------------------------------------


class TestScaleAxisCentered:
    def test_min_raw_maps_to_low(self) -> None:
        assert _scale_axis(0, _make_centered_axis()) == CRSF_CH_LOW

    def test_center_raw_maps_to_mid(self) -> None:
        assert _scale_axis(500, _make_centered_axis()) == CRSF_CH_MID

    def test_max_raw_maps_to_high(self) -> None:
        assert _scale_axis(1000, _make_centered_axis()) == CRSF_CH_HIGH

    def test_clamp_below_min(self) -> None:
        # raw=-50 ниже min_raw=0 — должен клампнуться до low, не вылетать в отрицательное.
        assert _scale_axis(-50, _make_centered_axis()) == CRSF_CH_LOW

    def test_clamp_above_max(self) -> None:
        assert _scale_axis(99_999, _make_centered_axis()) == CRSF_CH_HIGH

    def test_deadband_returns_mid(self) -> None:
        axis = _make_centered_axis(deadband=50)
        # raw=510 в пределах ±50 от центра 500 → MID.
        assert _scale_axis(510, axis) == CRSF_CH_MID
        assert _scale_axis(450, axis) == CRSF_CH_MID
        assert _scale_axis(550, axis) == CRSF_CH_MID
        # raw=560 уже за пределами deadband → НЕ MID.
        assert _scale_axis(560, axis) != CRSF_CH_MID

    def test_invert_flips_around_mid(self) -> None:
        axis = _make_centered_axis(invert=True)
        # При invert min_raw=0 уходит не в LOW, а в HIGH (зеркало вокруг 992).
        assert _scale_axis(0, axis) == CRSF_CH_HIGH
        assert _scale_axis(1000, axis) == CRSF_CH_LOW
        assert _scale_axis(500, axis) == CRSF_CH_MID  # центр остаётся центром


class TestScaleAxisUnidirectional:
    def test_min_to_low_max_to_high(self) -> None:
        axis = _make_uni_axis()
        assert _scale_axis(0, axis) == CRSF_CH_LOW
        assert _scale_axis(1000, axis) == CRSF_CH_HIGH

    def test_clamp_below_min(self) -> None:
        assert _scale_axis(-100, _make_uni_axis()) == CRSF_CH_LOW

    def test_invert_unidirectional(self) -> None:
        # Инвертированный throttle: raw=0 → HIGH, raw=max → LOW (опасное состояние,
        # но физика "стик вниз = низкое CRSF" встречается у некоторых сборок).
        axis = _make_uni_axis(invert=True)
        assert _scale_axis(0, axis) == CRSF_CH_HIGH
        assert _scale_axis(1000, axis) == CRSF_CH_LOW


# --- _scale_switch ---------------------------------------------------------


class TestScaleSwitch2Pos:
    def test_off_to_low(self) -> None:
        sw = SwitchMapping(name="arm", source="BTN_TRIGGER", channel=5, kind="2pos")
        assert _scale_switch(0, sw) == CRSF_CH_LOW

    def test_on_to_high(self) -> None:
        sw = SwitchMapping(name="arm", source="BTN_TRIGGER", channel=5, kind="2pos")
        assert _scale_switch(1, sw) == CRSF_CH_HIGH


class TestScaleSwitchMomentary:
    def test_released_to_low(self) -> None:
        sw = SwitchMapping(name="beeper", source="BTN_THUMB2", channel=7, kind="momentary")
        assert _scale_switch(0, sw) == CRSF_CH_LOW

    def test_pressed_to_high(self) -> None:
        sw = SwitchMapping(name="beeper", source="BTN_THUMB2", channel=7, kind="momentary")
        assert _scale_switch(1, sw) == CRSF_CH_HIGH


class TestScaleSwitch3Pos:
    def test_default_thresholds_0_1_2(self) -> None:
        sw = SwitchMapping(name="mode", source="BTN_THUMB", channel=6, kind="3pos")
        assert _scale_switch(0, sw) == CRSF_CH_LOW
        assert _scale_switch(1, sw) == CRSF_CH_MID
        assert _scale_switch(2, sw) == CRSF_CH_HIGH

    def test_custom_thresholds_for_abs_hat(self) -> None:
        # ABS_HAT0Y типично шлёт -1 / 0 / 1.
        sw = SwitchMapping(
            name="mode",
            source="ABS_HAT0Y",
            channel=6,
            kind="3pos",
            low_raw=-1,
            high_raw=1,
        )
        assert _scale_switch(-1, sw) == CRSF_CH_LOW
        assert _scale_switch(0, sw) == CRSF_CH_MID
        assert _scale_switch(1, sw) == CRSF_CH_HIGH


# --- apply_mapping ---------------------------------------------------------


def _full_config() -> ChannelMapConfig:
    return ChannelMapConfig(
        axes=(
            _make_centered_axis(name="roll", source="ABS_X", channel=1),
            _make_centered_axis(name="pitch", source="ABS_Y", channel=2),
            _make_uni_axis(name="throttle", source="ABS_RZ", channel=3),
            _make_centered_axis(name="yaw", source="ABS_Z", channel=4),
        ),
        switches=(
            SwitchMapping(name="arm", source="BTN_TRIGGER", channel=5, kind="2pos"),
            SwitchMapping(name="mode", source="BTN_THUMB", channel=6, kind="3pos"),
            SwitchMapping(name="beeper", source="BTN_THUMB2", channel=7, kind="momentary"),
        ),
    )


class TestApplyMapping:
    def test_result_always_length_16(self) -> None:
        channels = apply_mapping({}, _full_config())
        assert len(channels) == CHANNEL_COUNT

    def test_unmapped_slots_default_to_mid(self) -> None:
        channels = apply_mapping({"ABS_X": 500}, _full_config())
        # AUX4..AUX12 (каналы 8..16 = index 7..15) ни во что не маппятся → 992.
        for i in range(7, CHANNEL_COUNT):
            assert channels[i] == CRSF_CH_MID, f"channel {i + 1} expected MID, got {channels[i]}"

    def test_failsafe_state_disarmed(self) -> None:
        # Канонический failsafe-тест: все стики в центре + arm в off → arm-канал=172.
        raw_state = {
            "ABS_X": 500,  # roll center
            "ABS_Y": 500,  # pitch center
            "ABS_RZ": 0,  # throttle idle
            "ABS_Z": 500,  # yaw center
            "BTN_TRIGGER": 0,  # arm OFF
        }
        channels = apply_mapping(raw_state, _full_config())
        assert channels[4] == CRSF_CH_LOW, "arm (ch5) must be 172 when raw=0 (disarmed)"
        assert channels[2] == CRSF_CH_LOW, "throttle (ch3) must be 172 at raw=0"
        assert channels[0] == CRSF_CH_MID, "roll (ch1) must be 992 at center"

    def test_empty_raw_state_failsafe(self) -> None:
        # apply_mapping({}, config) — состояние сразу после reconnect.
        # Это вызов из _try_reopen в joystick_to_crsf.
        channels = apply_mapping({}, _full_config())
        assert channels[0] == CRSF_CH_MID  # roll: центрированный → MID
        assert channels[1] == CRSF_CH_MID  # pitch: центрированный → MID
        assert channels[2] == CRSF_CH_LOW  # throttle: без center_raw → LOW (idle, safe)
        assert channels[3] == CRSF_CH_MID  # yaw: центрированный → MID
        assert channels[4] == CRSF_CH_LOW  # arm: switch без сигнала → LOW (disarmed)
        assert channels[5] == CRSF_CH_LOW  # mode: switch без сигнала → LOW
        assert channels[6] == CRSF_CH_LOW  # beeper: switch без сигнала → LOW

    def test_arm_on_raises_to_high(self) -> None:
        # Симметричный тест: явно установленный arm=1 даёт 1811 на AUX1.
        raw = {"BTN_TRIGGER": 1}
        channels = apply_mapping(raw, _full_config())
        assert channels[4] == CRSF_CH_HIGH

    def test_unknown_source_in_raw_state_ignored(self) -> None:
        # Источники, не упомянутые в config, не должны ломать apply.
        raw = {"ABS_X": 500, "TOTALLY_UNKNOWN": 1234}
        channels = apply_mapping(raw, _full_config())
        assert len(channels) == CHANNEL_COUNT


# --- load_config ----------------------------------------------------------


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "channels.toml"
    p.write_text(text, encoding="utf-8")
    return p


class TestLoadConfigValid:
    def test_minimal_valid(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            """
[axis.roll]
source = "ABS_X"
channel = 1
min_raw = 0
max_raw = 1000
center_raw = 500

[switch.arm]
source = "BTN_TRIGGER"
channel = 5
kind = "2pos"
""",
        )
        cfg = load_config(p)
        assert len(cfg.axes) == 1
        assert cfg.axes[0].name == "roll"
        assert cfg.axes[0].center_raw == 500
        assert len(cfg.switches) == 1
        assert cfg.switches[0].kind == "2pos"

    def test_axis_without_center_raw_is_unidirectional(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            """
[axis.throttle]
source = "ABS_RZ"
channel = 3
min_raw = 0
max_raw = 1000
""",
        )
        cfg = load_config(p)
        assert cfg.axes[0].center_raw is None

    def test_default_toml_file_loads(self) -> None:
        # channels.default.toml в repo должен парситься без ошибок —
        # иначе install.sh выкатит сломанный конфиг в /etc/u1u2-bridge.
        repo_root = Path(__file__).resolve().parent.parent.parent
        default = repo_root / "common" / "channels.default.toml"
        cfg = load_config(default)
        names = {a.name for a in cfg.axes}
        assert {"throttle", "yaw", "pitch", "roll"} <= names, (
            f"default config must define throttle/yaw/pitch/roll, got {names}"
        )
        switch_names = {s.name for s in cfg.switches}
        assert {"arm", "mode", "beeper"} <= switch_names


class TestLoadConfigInvalid:
    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ChannelMapError, match="not found"):
            load_config(tmp_path / "does-not-exist.toml")

    def test_broken_toml_syntax(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "this is not [valid toml")
        with pytest.raises(ChannelMapError, match="invalid TOML"):
            load_config(p)

    def test_missing_required_axis_field(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            """
[axis.roll]
source = "ABS_X"
# channel missing
min_raw = 0
max_raw = 1000
""",
        )
        with pytest.raises(ChannelMapError, match="missing required field 'channel'"):
            load_config(p)

    def test_min_raw_not_less_than_max_raw(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            """
[axis.roll]
source = "ABS_X"
channel = 1
min_raw = 1000
max_raw = 500
""",
        )
        with pytest.raises(ChannelMapError, match="must be <"):
            load_config(p)

    def test_center_raw_out_of_range(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            """
[axis.roll]
source = "ABS_X"
channel = 1
min_raw = 0
max_raw = 1000
center_raw = 5000
""",
        )
        with pytest.raises(ChannelMapError, match="center_raw"):
            load_config(p)

    def test_channel_out_of_range(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            """
[axis.roll]
source = "ABS_X"
channel = 17
min_raw = 0
max_raw = 1000
""",
        )
        with pytest.raises(ChannelMapError, match="out of"):
            load_config(p)

    def test_duplicate_channel_axis_vs_switch(self, tmp_path: Path) -> None:
        # Два маппинга на один и тот же канал — ошибка, иначе один молча затрёт другой.
        p = _write(
            tmp_path,
            """
[axis.roll]
source = "ABS_X"
channel = 5
min_raw = 0
max_raw = 1000

[switch.arm]
source = "BTN_TRIGGER"
channel = 5
kind = "2pos"
""",
        )
        with pytest.raises(ChannelMapError, match="already used"):
            load_config(p)

    def test_unknown_switch_kind(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            """
[switch.weird]
source = "BTN_X"
channel = 5
kind = "5pos"
""",
        )
        with pytest.raises(ChannelMapError, match="kind"):
            load_config(p)

    def test_unknown_field_in_axis(self, tmp_path: Path) -> None:
        # Опечатка в имени поля — частая ошибка, должна ловиться явно.
        p = _write(
            tmp_path,
            """
[axis.roll]
source = "ABS_X"
channel = 1
min_raw = 0
max_raw = 1000
centre_raw = 500
""",
        )
        with pytest.raises(ChannelMapError, match="unknown fields"):
            load_config(p)

    def test_3pos_low_geq_high_raises(self, tmp_path: Path) -> None:
        p = _write(
            tmp_path,
            """
[switch.mode]
source = "ABS_HAT0Y"
channel = 6
kind = "3pos"
low_raw = 5
high_raw = 5
""",
        )
        with pytest.raises(ChannelMapError, match="low_raw"):
            load_config(p)
