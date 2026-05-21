"""Periodic snapshot of TelemetryState → structured journald logging.

Раз в ``interval_s`` (default 1.0) выкидывает один INFO-лог с полной
выжимкой ``TelemetryState`` в ``extra={"telemetry": {...}}``. Под systemd
это превращается в structured JSON в journald — ``journalctl -o json``
вытаскивает ``TELEMETRY_*`` поля для grafana-loki, jq-фильтрации и т.д.

Stale-маркировка по полям: если данных нет (``ts is None``) или они
старше ``stale_s`` секунд, поле в snapshot → ``None`` целиком (не
"наполовину устаревшая батарея"). ``age_s`` остаётся для тех полей,
которые хотя бы раз приходили, — позволяет видеть "вчерашняя батарея,
не получаем 47 секунд".

Rate-limit на ``time.monotonic``, инжектируемый через аргумент — для
тестов без ``mocker.patch`` глобального time.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from common.crsf_telemetry import (
    DEFAULT_STALE_SEC,
    Attitude,
    BatterySensor,
    FlightMode,
    Gps,
    LinkStatistics,
    TelemetryState,
)

DEFAULT_LOG_INTERVAL_SEC: float = 1.0


class TelemetryLogger:
    """Periodic snapshot dumper. Не имеет внутреннего таймера — вызывающий
    периодически зовёт ``maybe_log(now)`` из своего main-loop. Это даёт
    тестам полный контроль над временем без monkey-patch'инга.
    """

    def __init__(
        self,
        state: TelemetryState,
        log_: logging.Logger,
        *,
        interval_s: float = DEFAULT_LOG_INTERVAL_SEC,
        stale_s: float = DEFAULT_STALE_SEC,
    ) -> None:
        self._state = state
        self._log = log_
        self._interval_s = interval_s
        self._stale_s = stale_s
        # -inf чтобы первый maybe_log сработал сразу при любом now ≥ 0.
        self._last_emit_ts: float = float("-inf")

    @property
    def interval_s(self) -> float:
        return self._interval_s

    @property
    def stale_s(self) -> float:
        return self._stale_s

    def maybe_log(self, now: float) -> bool:
        """Вернёт True и эмитнет snapshot если прошло >= interval с последнего."""
        if now - self._last_emit_ts < self._interval_s:
            return False
        self._last_emit_ts = now
        extras = self.snapshot_extras(now)
        # Под systemd "telemetry" станет JOURNAL field TELEMETRY (uppercase, no nesting).
        # Это нормально — `journalctl -o json` выдаёт JSON-encoded dict.
        self._log.info("telemetry snapshot", extra={"telemetry": extras})
        return True

    def snapshot_extras(self, now: float) -> dict[str, Any]:
        """Собрать dict для extras без эмита (для тестов и сторонних вызовов)."""
        return {
            "link": self._field_extras(self._state.link, self._state.link_ts, now),
            "battery": self._field_extras(self._state.battery, self._state.battery_ts, now),
            "flight_mode": self._field_extras(
                self._state.flight_mode, self._state.flight_mode_ts, now
            ),
            "gps": self._field_extras(self._state.gps, self._state.gps_ts, now),
            "attitude": self._field_extras(self._state.attitude, self._state.attitude_ts, now),
        }

    def _field_extras(
        self,
        data: LinkStatistics | BatterySensor | FlightMode | Gps | Attitude | None,
        ts: float | None,
        now: float,
    ) -> dict[str, Any] | None:
        """Собрать под-extras для одного frame type.

        - ``ts is None``: ни разу не приходило → ``None`` целиком.
        - stale (``now - ts > stale_s``): ``{"stale": True, "age_s": ...}`` без полей
          (старые данные могут быть опаснее, чем их отсутствие — лучше явный gap).
        - fresh: полный набор полей + ``stale: False`` + ``age_s``.
        """
        if data is None or ts is None:
            return None
        age_s = round(now - ts, 3)
        if TelemetryState.is_stale(ts, now, self._stale_s):
            return {"stale": True, "age_s": age_s}
        return {"stale": False, "age_s": age_s, **asdict(data)}
