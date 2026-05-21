"""Channel mapping config: raw input (evdev codes) → 16 CRSF RC channels.

Принимает TOML-конфиг, описывающий:
- до 4 аналоговых осей (throttle, yaw, pitch, roll) с линейной калибровкой
  (`min_raw`, `max_raw`, опциональный `center_raw` для центрированных стиков,
  `invert`, `deadband` вокруг центра).
- любое число свичей трёх видов: 2-pos, 3-pos, momentary.

Зачем TOML, а не env-переменные / Python:
- структура per-axis с под-полями — env с этим возиться неудобно;
- редактируется человеком на Pi без передеплоя кода и переживает `apt upgrade`;
- `tomllib` — stdlib с 3.11, никаких новых зависимостей.

Конвенция CRSF channel value (Betaflight / ExpressLRS)::

    172   = ~1000 µs PWM (low / off / disarm)
    992   = ~1500 µs PWM (center / mid)
    1811  = ~2000 µs PWM (high / on / arm)

В TOML каналы 1-indexed (`channel = 5` = AUX1) — как привык оператор смотреть
в Betaflight Configurator. Внутри храним 0-indexed tuple длины 16.

Failsafe-правило для ``apply_mapping(empty_state, config)``:
- ось с ``center_raw`` (центрированный стик) → 992;
- ось без ``center_raw`` (throttle) → 172 (idle, безопасно);
- свич → 172 (off).

Это значит, что после reconnect джойстика (raw_state сброшен) выдаётся
безопасное состояние: газ в 0, оружие в disarm, режимы в low.

Reference:
    Betaflight RC channel ranges: src/main/rx/rx.c (PWM_PULSE_MIN/MID/MAX).
    ELRS: src/lib/CrsfProtocol/crsf_protocol.h (CRSF_CHANNEL_VALUE_*).
"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CRSF_CH_LOW: int = 172
CRSF_CH_MID: int = 992
CRSF_CH_HIGH: int = 1811

CHANNEL_COUNT: int = 16

_VALID_SWITCH_KINDS: frozenset[str] = frozenset({"2pos", "3pos", "momentary"})
_AXIS_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"source", "channel", "min_raw", "max_raw", "center_raw", "invert", "deadband"}
)
_SWITCH_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"source", "channel", "kind", "low_raw", "high_raw"}
)

log = logging.getLogger(__name__)


class ChannelMapError(ValueError):
    """Невалидный channel-map config — отдельный тип, чтобы вызывающий мог
    отличить ошибку конфига от любого другого ValueError в pipeline."""


@dataclass(kw_only=True, slots=True, frozen=True)
class AxisMapping:
    """Одна аналоговая ось → один CRSF-канал.

    - ``source``: имя evdev-кода (например ``"ABS_X"``) — ключ в ``raw_state``.
    - ``channel``: целевой CRSF-канал, 1-indexed (1..16).
    - ``min_raw``/``max_raw``: диапазон сырых значений от драйвера, в который
      кламп; вне него raw обрезается до границы (стик за калибровкой не выдаёт
      выбросы в CRSF). Должно быть ``min_raw < max_raw``.
    - ``center_raw``: если задано — ось трактуется как центрированная (стик
      с возвратной пружиной): значения ниже центра скэйлируются в [172, 992],
      выше — в [992, 1811], в окрестности center_raw ± deadband отдаётся 992.
      Если ``None`` — ось унидирекциональная (throttle): линейно [172..1811],
      deadband не применяется.
    - ``invert``: при ``True`` финальный CRSF-результат отзеркаливается вокруг
      992 (стик-вверх → CRSF-low вместо CRSF-high).
    - ``deadband``: окно вокруг ``center_raw`` в сырых единицах, в котором
      возвращается ровно 992 (борьба с дрейфом гимбала). Игнорируется, если
      ``center_raw is None``. Должен быть ``>= 0``.
    """

    name: str
    source: str
    channel: int
    min_raw: int
    max_raw: int
    center_raw: int | None = None
    invert: bool = False
    deadband: int = 0


@dataclass(kw_only=True, slots=True, frozen=True)
class SwitchMapping:
    """Один свич → один CRSF-канал.

    - ``kind``:
        - ``"2pos"`` — raw=0 → 172, raw!=0 → 1811.
        - ``"momentary"`` — то же, что 2pos (отдельный kind для семантики).
        - ``"3pos"`` — пороги ``low_raw``/``high_raw``: raw<=low_raw → 172,
          raw>=high_raw → 1811, иначе 992. Дефолты 0/2 покрывают сценарий
          paired-buttons multi-state (0=off, 1=mid, 2=high). Для ABS_HAT
          (-1/0/1) переопределите ``low_raw=-1``, ``high_raw=1``.
    - ``low_raw``/``high_raw``: только для 3pos, для 2pos/momentary
      игнорируются.
    """

    name: str
    source: str
    channel: int
    kind: str
    low_raw: int = 0
    high_raw: int = 2


@dataclass(kw_only=True, slots=True, frozen=True)
class ChannelMapConfig:
    """Корневой контейнер. Tuple (не list) — конфиг immutable после load."""

    axes: tuple[AxisMapping, ...]
    switches: tuple[SwitchMapping, ...]


# ---- scaling primitives ----------------------------------------------------


def _scale_axis(raw: int, axis: AxisMapping) -> int:
    """Сырое значение оси → CRSF [172, 1811] с учётом калибровки и invert.

    Алгоритм:
    1. Кламп raw в ``[min_raw, max_raw]``.
    2. Если ``invert`` — flip raw вокруг pivot (``center_raw`` для центрированной
       оси, ``(min+max)//2`` для унидирекциональной), затем перекламп. Делаем
       до scaling, а не зеркалим итоговый CRSF: иначе ``(172+1811)-992 = 991``
       давал бы джиттер на ±1 у центрированных осей при invert.
    3. Если ``center_raw is None``: линейная карта (min→172, max→1811).
    4. Если ``center_raw`` задан: двухсегментная карта с deadband. В сегменте
       ниже центра линейно [min..center-deadband] → [172..992], выше центра
       линейно [center+deadband..max] → [992..1811], внутри ± deadband — 992.

    Целочисленная арифметика — без float, чтобы результат был детерминированным
    (важно для тестов и отладки протокола).
    """
    clamped = max(axis.min_raw, min(axis.max_raw, raw))

    if axis.invert:
        pivot = (
            axis.center_raw if axis.center_raw is not None else (axis.min_raw + axis.max_raw) // 2
        )
        clamped = 2 * pivot - clamped
        # 2*pivot-clamped может выскочить за [min, max] на ±1 при нечётном
        # размахе для унидирекциональных — перекламп возвращает в диапазон.
        clamped = max(axis.min_raw, min(axis.max_raw, clamped))

    if axis.center_raw is None:
        span = axis.max_raw - axis.min_raw
        if span <= 0:
            crsf = CRSF_CH_MID
        else:
            crsf = CRSF_CH_LOW + (clamped - axis.min_raw) * (CRSF_CH_HIGH - CRSF_CH_LOW) // span
    else:
        center = axis.center_raw
        if abs(clamped - center) <= axis.deadband:
            crsf = CRSF_CH_MID
        elif clamped < center:
            lo_end = axis.min_raw
            hi_end = center - axis.deadband
            span = hi_end - lo_end
            crsf = (
                CRSF_CH_MID
                if span <= 0
                else CRSF_CH_LOW + (clamped - lo_end) * (CRSF_CH_MID - CRSF_CH_LOW) // span
            )
        else:
            lo_end = center + axis.deadband
            hi_end = axis.max_raw
            span = hi_end - lo_end
            crsf = (
                CRSF_CH_MID
                if span <= 0
                else CRSF_CH_MID + (clamped - lo_end) * (CRSF_CH_HIGH - CRSF_CH_MID) // span
            )

    return crsf


def _scale_switch(raw: int, switch: SwitchMapping) -> int:
    """Сырое значение свича → один из трёх CRSF-уровней."""
    if switch.kind == "3pos":
        if raw <= switch.low_raw:
            return CRSF_CH_LOW
        if raw >= switch.high_raw:
            return CRSF_CH_HIGH
        return CRSF_CH_MID
    # 2pos и momentary — одинаковая логика, разделены для семантики читателя.
    return CRSF_CH_HIGH if raw else CRSF_CH_LOW


def _axis_failsafe(axis: AxisMapping) -> int:
    """Значение оси при отсутствии raw-сигнала (USB unplug, до первого event).

    Центрированные оси → 992. Унидирекциональные (throttle) → 172 (idle).
    """
    return CRSF_CH_MID if axis.center_raw is not None else CRSF_CH_LOW


# ---- apply ----------------------------------------------------------------


def apply_mapping(
    raw_state: Mapping[str, int],
    config: ChannelMapConfig,
) -> tuple[int, ...]:
    """``raw_state`` (источник → последнее наблюдённое сырое значение) → 16 CRSF.

    Каналы 1..16 в конфиге — 0..15 в результирующем tuple. Незамаппленные
    слоты остаются ``CRSF_CH_MID`` (992). Свич без записи в raw_state —
    ``CRSF_CH_LOW`` (failsafe-off, важно для arm).

    Контракт: длина результата всегда ``CHANNEL_COUNT`` (16).
    """
    channels = [CRSF_CH_MID] * CHANNEL_COUNT

    for axis in config.axes:
        raw = raw_state.get(axis.source)
        channels[axis.channel - 1] = _axis_failsafe(axis) if raw is None else _scale_axis(raw, axis)

    for switch in config.switches:
        raw = raw_state.get(switch.source)
        channels[switch.channel - 1] = CRSF_CH_LOW if raw is None else _scale_switch(raw, switch)

    return tuple(channels)


# ---- TOML loader + validation ---------------------------------------------


def _require_int(value: object, what: str) -> int:
    # `bool` — подкласс `int` в Python; в TOML это разные типы, но tomllib
    # может вернуть python-bool из неаккуратного конфига; отвергаем явно,
    # иначе ``channel = true`` молча станет ``channel = 1``.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ChannelMapError(f"{what}: expected int, got {type(value).__name__}")
    return value


def _check_unknown_keys(body: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    extra = set(body) - allowed
    if extra:
        raise ChannelMapError(f"{where}: unknown fields {sorted(extra)} (typo?)")


def _parse_axis(name: str, body: Any) -> AxisMapping:  # noqa: ANN401 — tomllib gives Any
    if not isinstance(body, dict):
        raise ChannelMapError(f"axis.{name}: must be a table")
    _check_unknown_keys(body, _AXIS_ALLOWED_KEYS, f"axis.{name}")

    for required in ("source", "channel", "min_raw", "max_raw"):
        if required not in body:
            raise ChannelMapError(f"axis.{name}: missing required field {required!r}")

    source = body["source"]
    if not isinstance(source, str):
        raise ChannelMapError(f"axis.{name}: 'source' must be string")

    channel = _require_int(body["channel"], f"axis.{name}.channel")
    if not 1 <= channel <= CHANNEL_COUNT:
        raise ChannelMapError(f"axis.{name}: channel {channel} out of [1, {CHANNEL_COUNT}]")

    min_raw = _require_int(body["min_raw"], f"axis.{name}.min_raw")
    max_raw = _require_int(body["max_raw"], f"axis.{name}.max_raw")
    if min_raw >= max_raw:
        raise ChannelMapError(f"axis.{name}: min_raw ({min_raw}) must be < max_raw ({max_raw})")

    center_obj = body.get("center_raw")
    center_raw: int | None
    if center_obj is None:
        center_raw = None
    else:
        center_raw = _require_int(center_obj, f"axis.{name}.center_raw")
        if not min_raw <= center_raw <= max_raw:
            raise ChannelMapError(
                f"axis.{name}: center_raw ({center_raw}) must be within [{min_raw}, {max_raw}]"
            )

    invert_obj = body.get("invert", False)
    if not isinstance(invert_obj, bool):
        raise ChannelMapError(f"axis.{name}: 'invert' must be bool")

    deadband = _require_int(body.get("deadband", 0), f"axis.{name}.deadband")
    if deadband < 0:
        raise ChannelMapError(f"axis.{name}: deadband ({deadband}) must be >= 0")

    return AxisMapping(
        name=name,
        source=source,
        channel=channel,
        min_raw=min_raw,
        max_raw=max_raw,
        center_raw=center_raw,
        invert=invert_obj,
        deadband=deadband,
    )


def _parse_switch(name: str, body: Any) -> SwitchMapping:  # noqa: ANN401
    if not isinstance(body, dict):
        raise ChannelMapError(f"switch.{name}: must be a table")
    _check_unknown_keys(body, _SWITCH_ALLOWED_KEYS, f"switch.{name}")

    for required in ("source", "channel", "kind"):
        if required not in body:
            raise ChannelMapError(f"switch.{name}: missing required field {required!r}")

    source = body["source"]
    if not isinstance(source, str):
        raise ChannelMapError(f"switch.{name}: 'source' must be string")

    channel = _require_int(body["channel"], f"switch.{name}.channel")
    if not 1 <= channel <= CHANNEL_COUNT:
        raise ChannelMapError(f"switch.{name}: channel {channel} out of [1, {CHANNEL_COUNT}]")

    kind = body["kind"]
    if kind not in _VALID_SWITCH_KINDS:
        raise ChannelMapError(f"switch.{name}: kind {kind!r} not in {sorted(_VALID_SWITCH_KINDS)}")

    low_raw = _require_int(body.get("low_raw", 0), f"switch.{name}.low_raw")
    high_raw = _require_int(body.get("high_raw", 2), f"switch.{name}.high_raw")
    if kind == "3pos" and low_raw >= high_raw:
        raise ChannelMapError(
            f"switch.{name}: low_raw ({low_raw}) must be < high_raw ({high_raw}) for 3pos"
        )

    return SwitchMapping(
        name=name,
        source=source,
        channel=channel,
        kind=kind,
        low_raw=low_raw,
        high_raw=high_raw,
    )


def load_config(path: Path) -> ChannelMapConfig:
    """Прочитать и провалидировать TOML-конфиг маппинга.

    Ошибки IO/TOML/валидации — всё ``ChannelMapError`` с человекочитаемым
    сообщением. Это даёт вызывающему один тип для try/except и одну
    точку для лога.
    """
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError as e:
        raise ChannelMapError(f"channel map not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ChannelMapError(f"invalid TOML in {path}: {e}") from e

    axis_table = data.get("axis", {})
    if not isinstance(axis_table, dict):
        raise ChannelMapError(f"'axis' must be a table, got {type(axis_table).__name__}")

    switch_table = data.get("switch", {})
    if not isinstance(switch_table, dict):
        raise ChannelMapError(f"'switch' must be a table, got {type(switch_table).__name__}")

    used_channels: dict[int, str] = {}
    axes: list[AxisMapping] = []
    for name, body in axis_table.items():
        axis = _parse_axis(name, body)
        if axis.channel in used_channels:
            raise ChannelMapError(
                f"channel {axis.channel} already used by {used_channels[axis.channel]!r}; "
                f"cannot also assign to axis.{name!r}"
            )
        used_channels[axis.channel] = f"axis.{name}"
        axes.append(axis)

    switches: list[SwitchMapping] = []
    for name, body in switch_table.items():
        switch = _parse_switch(name, body)
        if switch.channel in used_channels:
            raise ChannelMapError(
                f"channel {switch.channel} already used by {used_channels[switch.channel]!r}; "
                f"cannot also assign to switch.{name!r}"
            )
        used_channels[switch.channel] = f"switch.{name}"
        switches.append(switch)

    log.info("channel map loaded from %s: %d axes, %d switches", path, len(axes), len(switches))
    return ChannelMapConfig(axes=tuple(axes), switches=tuple(switches))
