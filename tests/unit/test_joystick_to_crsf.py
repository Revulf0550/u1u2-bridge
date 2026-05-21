"""Unit-тесты для `common.joystick_to_crsf`.

Тестируем без реальной evdev-зависимости (на Windows dev-машине её нет):
- события — `SimpleNamespace`, эмулирующий `evdev.InputEvent` (.type/.code/.value)
- device — `MagicMock`, имитирующий `evdev.InputDevice` (.read/.fd/.close)
- socket — `MagicMock` через pytest-mock

Главный цикл `main()` НЕ тестируется (он бесконечный). Тестируем `_tick`,
`_apply_event`, `_try_reopen`, `normalize_axis` — они вынесены именно для этого.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from common.channel_map import (
    CRSF_CH_HIGH,
    CRSF_CH_LOW,
    AxisMapping,
    ChannelMapConfig,
    SwitchMapping,
)
from common.joystick_to_crsf import (
    ABS_X,
    ABS_Y,
    BTN_TRIGGER,
    ELRS_CENTER,
    EV_ABS,
    EV_KEY,
    JoystickState,
    _apply_event,
    _failsafe_channels,
    _load_channel_map,
    _tick,
    _try_reopen,
    normalize_axis,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _make_log() -> logging.Logger:
    return logging.getLogger("test-joystick")


class TestDefaultState:
    def test_channels_centered(self) -> None:
        state = JoystickState()
        assert state.channels == [ELRS_CENTER] * 16
        assert state.device is None
        assert state.axis_ranges == {}


class TestNormalizeAxis:
    def test_min_maps_to_172(self) -> None:
        assert normalize_axis(0, 0, 1639) == 172

    def test_max_maps_to_1811(self) -> None:
        assert normalize_axis(1639, 0, 1639) == 1811

    def test_midpoint_maps_to_992(self) -> None:
        # Range [0, 1639]: half-point at 820 maps exactly to 992 (= 172 + 820).
        assert normalize_axis(820, 0, 1639) == 992

    def test_degenerate_range_returns_center(self) -> None:
        # axis_min == axis_max → не падаем, отдаём центр.
        assert normalize_axis(100, 500, 500) == ELRS_CENTER


class TestApplyEvent:
    def test_axis_event_updates_channel(self) -> None:
        state = JoystickState(axis_ranges={ABS_X: (0, 1639)})
        _apply_event(state, SimpleNamespace(type=EV_ABS, code=ABS_X, value=1639))
        assert state.channels[0] == 1811
        # Other channels untouched.
        assert state.channels[1] == ELRS_CENTER

    def test_unknown_axis_code_ignored(self) -> None:
        state = JoystickState(axis_ranges={})
        # ABS code that's not in AXIS_TO_CHANNEL (e.g. ABS_HAT0X=0x10).
        _apply_event(state, SimpleNamespace(type=EV_ABS, code=0x10, value=1))
        assert state.channels == [ELRS_CENTER] * 16

    def test_non_abs_event_ignored(self) -> None:
        state = JoystickState(axis_ranges={ABS_X: (0, 1639)})
        # EV_KEY = 1 (кнопки), не EV_ABS.
        _apply_event(state, SimpleNamespace(type=0x01, code=ABS_X, value=1))
        assert state.channels[0] == ELRS_CENTER

    def test_axis_without_known_range_ignored(self) -> None:
        # ABS_X mapped to ch0, но axis_ranges пуст → не делим на ноль / не угадываем.
        state = JoystickState(axis_ranges={})
        _apply_event(state, SimpleNamespace(type=EV_ABS, code=ABS_X, value=500))
        assert state.channels[0] == ELRS_CENTER


class TestTick:
    def test_send_loop_packs_frame(self, mocker: MockerFixture) -> None:
        device = mocker.MagicMock()
        device.read.return_value = []  # no pending events
        state = JoystickState(device=device, axis_ranges={ABS_X: (0, 1639)})
        sock = mocker.MagicMock()
        peer = ("10.8.0.6", 14550)

        sent = _tick(state, sock, peer, _make_log())

        assert sent == 26
        assert sock.sendto.call_count == 1
        frame, addr = sock.sendto.call_args.args
        assert addr == peer
        assert len(frame) == 26
        assert frame[0] == 0xC8
        assert frame[1] == 0x18
        assert frame[2] == 0x16

    def test_tick_drains_events_before_sending(self, mocker: MockerFixture) -> None:
        device = mocker.MagicMock()
        device.read.return_value = [
            SimpleNamespace(type=EV_ABS, code=ABS_X, value=1639),
            SimpleNamespace(type=EV_ABS, code=ABS_Y, value=0),
        ]
        state = JoystickState(
            device=device,
            axis_ranges={ABS_X: (0, 1639), ABS_Y: (0, 1639)},
        )
        sock = mocker.MagicMock()

        _tick(state, sock, ("h", 1), _make_log())

        assert state.channels[0] == 1811
        assert state.channels[1] == 172
        assert sock.sendto.call_count == 1

    def test_disconnect_stops_sending(self, mocker: MockerFixture) -> None:
        device = mocker.MagicMock()
        device.read.side_effect = OSError("ENODEV: device disconnected")
        state = JoystickState(device=device)
        sock = mocker.MagicMock()

        sent = _tick(state, sock, ("h", 1), _make_log())

        assert sent == 0
        assert sock.sendto.call_count == 0
        assert state.device is None
        device.close.assert_called_once()

    def test_no_device_returns_zero_no_send(self, mocker: MockerFixture) -> None:
        # Failsafe: device == None → CRSF не шлём (FC сам уйдёт в failsafe).
        state = JoystickState(device=None)
        sock = mocker.MagicMock()

        sent = _tick(state, sock, ("h", 1), _make_log())

        assert sent == 0
        assert sock.sendto.call_count == 0

    def test_blocking_io_on_read_is_non_fatal(self, mocker: MockerFixture) -> None:
        # BlockingIOError = "нет событий прямо сейчас", это норма для non-blocking fd.
        device = mocker.MagicMock()
        device.read.side_effect = BlockingIOError()
        state = JoystickState(device=device)
        sock = mocker.MagicMock()

        sent = _tick(state, sock, ("h", 1), _make_log())

        assert sent == 26  # send всё равно произошёл — устройство живо
        assert state.device is device  # не закрылось


class TestTryReopen:
    def test_reconnect_resets_channels(self, mocker: MockerFixture) -> None:
        state = JoystickState(
            channels=[100] * 16,
            device=None,
            axis_ranges={},
            last_reopen_ts=0.0,
        )
        mock_dev = mocker.MagicMock()
        mock_dev.fd = 42
        mocker.patch(
            "common.joystick_to_crsf.open_device",
            return_value=(mock_dev, {ABS_X: (0, 1000)}),
        )

        _try_reopen(state, "/dev/input/event0", _make_log(), now=100.0)

        assert state.device is mock_dev
        assert state.channels == [ELRS_CENTER] * 16
        assert state.axis_ranges == {ABS_X: (0, 1000)}

    def test_open_failure_keeps_device_none(self, mocker: MockerFixture) -> None:
        state = JoystickState(device=None, last_reopen_ts=0.0)
        mocker.patch(
            "common.joystick_to_crsf.open_device",
            return_value=(None, {}),
        )

        _try_reopen(state, "/dev/input/event0", _make_log(), now=100.0)

        assert state.device is None

    def test_backoff_prevents_hot_loop(self, mocker: MockerFixture) -> None:
        # Сразу после неудачной попытки повтор не делается (защита от busy-loop).
        state = JoystickState(device=None, last_reopen_ts=100.0)
        open_mock = mocker.patch("common.joystick_to_crsf.open_device")

        _try_reopen(state, "/dev/input/event0", _make_log(), now=100.3)

        assert open_mock.call_count == 0

    def test_skip_when_device_already_open(self, mocker: MockerFixture) -> None:
        existing = mocker.MagicMock()
        state = JoystickState(device=existing)
        open_mock = mocker.patch("common.joystick_to_crsf.open_device")

        _try_reopen(state, "/dev/input/event0", _make_log(), now=100.0)

        assert open_mock.call_count == 0
        assert state.device is existing


# --- channel-map (config-path) integration --------------------------------


def _tiny_config() -> ChannelMapConfig:
    """Минимальный config: 1 ось + 1 свич, остальное по дефолту → 992."""
    return ChannelMapConfig(
        axes=(
            AxisMapping(
                name="roll",
                source="ABS_X",
                channel=1,
                min_raw=0,
                max_raw=1000,
                center_raw=500,
            ),
        ),
        switches=(SwitchMapping(name="arm", source="BTN_TRIGGER", channel=5, kind="2pos"),),
    )


class TestApplyEventConfigPath:
    def test_axis_event_routed_through_apply_mapping(self) -> None:
        state = JoystickState(config=_tiny_config())
        _apply_event(state, SimpleNamespace(type=EV_ABS, code=ABS_X, value=1000))
        # 1000 = max_raw → CRSF_CH_HIGH (1811) на канале 1 (index 0).
        assert state.channels[0] == CRSF_CH_HIGH
        assert state.raw_state["ABS_X"] == 1000

    def test_button_event_routed_through_apply_mapping(self) -> None:
        state = JoystickState(config=_tiny_config())
        _apply_event(state, SimpleNamespace(type=EV_KEY, code=BTN_TRIGGER, value=1))
        # BTN_TRIGGER pressed → arm = HIGH (1811) на канале 5 (index 4).
        assert state.channels[4] == CRSF_CH_HIGH

    def test_unknown_evdev_code_ignored_in_config_path(self) -> None:
        state = JoystickState(config=_tiny_config())
        _apply_event(state, SimpleNamespace(type=EV_ABS, code=0xFF, value=100))
        # ABS_? = 0xFF не в EVENT_CODE_NAMES → raw_state не меняется.
        assert state.raw_state == {}


class TestFailsafeChannels:
    def test_legacy_failsafe_is_all_center(self) -> None:
        assert _failsafe_channels(None) == [ELRS_CENTER] * 16

    def test_config_failsafe_low_for_switches(self) -> None:
        # apply_mapping({}, _tiny_config()): roll=MID (центрированная),
        # arm=LOW (свич без сигнала). Остальные слоты = MID.
        channels = _failsafe_channels(_tiny_config())
        assert channels[4] == CRSF_CH_LOW  # arm disarmed by default
        assert channels[0] == ELRS_CENTER  # roll centered


class TestLoadChannelMap:
    def test_missing_file_returns_none_with_warning(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        log = mocker.MagicMock()
        config = _load_channel_map(str(tmp_path / "nope.toml"), log)
        assert config is None
        assert log.warning.call_count == 1

    def test_valid_file_returns_config(self, tmp_path: Path) -> None:
        toml = tmp_path / "ch.toml"
        toml.write_text(
            '[axis.roll]\nsource = "ABS_X"\nchannel = 1\nmin_raw = 0\nmax_raw = 100\n',
            encoding="utf-8",
        )
        config = _load_channel_map(str(toml), _make_log())
        assert config is not None
        assert len(config.axes) == 1
        assert config.axes[0].name == "roll"
