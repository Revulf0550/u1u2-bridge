"""CRSF telemetry parser: stream bytes → typed payloads + TelemetryState.

ELRS приёмник на дроне в downlink-направлении шлёт по тому же UART, что мы
TX-им RC, телеметрические кадры с тем же синтаксисом ``RC_CHANNELS_PACKED``
(см. :mod:`common.crsf`): ``sync(0xC8) | len | type | payload | crc8``.

Парсер stream-based: один ``feed(bytes)`` может содержать ноль, один или
много кадров. Хвост (partial frame) буферизуется до следующего ``feed``.
На bad sync байтах ресинкаемся вперёд до следующего ``0xC8``. Bad CRC →
WARNING + дроп sync байта (тоже ресинк, на случай что 0xC8 был внутри
чужого payload). Неизвестный type → молча consume (телеметрия богатая,
не хотим спамить лог при каждой батарее).

Поддержаны (Step 3.3):
    0x14 LINK_STATISTICS  (10 B) — RSSI/LQ/SNR/TX power/antenna/RF mode
    0x08 BATTERY_SENSOR   (8 B)  — voltage / current / used mAh / remaining %
    0x21 FLIGHT_MODE      (var)  — ASCII null-terminated mode string
    0x02 GPS              (15 B) — lat / lon / speed / heading / alt / sats
    0x1E ATTITUDE         (6 B)  — pitch / roll / yaw (radians × 10000)

Reference:
    - TBS Crossfire спецификация (CRSF Protocol Definition).
    - ExpressLRS ``src/lib/CrsfProtocol/crsf_protocol.h``.
    - Betaflight ``src/main/telemetry/crsf.c``.

RSSI хранится как actual dBm (отрицательное число) — wire-формат "uint8
дБм × -1" преобразован при декоде, иначе ``rssi_1 = 85`` сбивает с толку
(в любом OSD это значение видно как ``-85 dBm``).

TX power хранится в милливаттах (``int`` после lookup из enum). Если
устройство шлёт неизвестный enum-индекс — оставляем -1 (отмаркер "unknown")
вместо exception, чтобы не выкидывать целый кадр из-за нового энум-значения.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass

from common.crsf import CRSF_SYNC_FC, crc8

# --- Frame types -----------------------------------------------------------

CRSF_FT_GPS: int = 0x02
CRSF_FT_BATTERY_SENSOR: int = 0x08
CRSF_FT_LINK_STATISTICS: int = 0x14
CRSF_FT_RC_CHANNELS_PACKED: int = 0x16  # uplink, не телеметрия, но мы её можем увидеть
CRSF_FT_ATTITUDE: int = 0x1E
CRSF_FT_FLIGHT_MODE: int = 0x21

# Min / max длина len-байта (включая type+payload+crc). Min=2 → пустой payload
# (heartbeat), max=62 → общий лимит CRSF_MAX_PACKET_SIZE=64 за вычетом sync+len.
_MIN_LEN_BYTE: int = 2
_MAX_LEN_BYTE: int = 62

# CRSF TX power enum → мощность в мВт (CRSF Protocol spec). 7 и 8 идут
# после 6 — это исторический артефакт TBS Crossfire (добавили low-power
# режимы позже без сдвига существующих). Unknown enum → -1 marker.
TX_POWER_MW: dict[int, int] = {
    0: 0,
    1: 10,
    2: 25,
    3: 100,
    4: 500,
    5: 1000,
    6: 2000,
    7: 250,
    8: 50,
}
TX_POWER_UNKNOWN: int = -1

log = logging.getLogger(__name__)


# --- Typed payload dataclasses --------------------------------------------


@dataclass(kw_only=True, slots=True, frozen=True)
class LinkStatistics:
    """0x14 LINK_STATISTICS payload (10 B), уже декодировано в осмысленные единицы.

    RSSI/SNR — в actual dBm (отрицательные). LQ — % (0..100). TX power —
    в мВт (или ``TX_POWER_UNKNOWN = -1`` если enum незнакомый).
    """

    uplink_rssi_1_dbm: int
    uplink_rssi_2_dbm: int
    uplink_lq: int
    uplink_snr_db: int
    diversity_antenna: int
    rf_mode: int
    uplink_tx_power_mw: int
    downlink_rssi_dbm: int
    downlink_lq: int
    downlink_snr_db: int


@dataclass(kw_only=True, slots=True, frozen=True)
class BatterySensor:
    """0x08 BATTERY_SENSOR payload (8 B). Поля в человекочитаемых единицах."""

    voltage_v: float  # raw uint16 × 0.1 V
    current_a: float  # raw uint16 × 0.1 A
    used_capacity_mah: int  # raw uint24
    remaining_percent: int  # raw uint8 (0..100)


@dataclass(kw_only=True, slots=True, frozen=True)
class FlightMode:
    """0x21 FLIGHT_MODE payload (variable, null-terminated ASCII).

    Betaflight шлёт что-то вроде "ANGLE", "ACRO", "*ACRO" (звёздочка =
    failsafe), "!ERR". Длина переменная, ограничена общим лимитом кадра.
    """

    mode: str


@dataclass(kw_only=True, slots=True, frozen=True)
class Gps:
    """0x02 GPS payload (15 B), декодировано."""

    latitude_deg: float
    longitude_deg: float
    ground_speed_kmh: float
    heading_deg: float
    altitude_m: int  # wire-формат смещён на +1000, чтобы влезать в uint16
    satellites: int


@dataclass(kw_only=True, slots=True, frozen=True)
class Attitude:
    """0x1E ATTITUDE payload (6 B), декодировано в радианы."""

    pitch_rad: float
    roll_rad: float
    yaw_rad: float


# Union для ParsedFrame.payload — все типы, которые умеет выдавать парсер.
PayloadT = LinkStatistics | BatterySensor | FlightMode | Gps | Attitude


@dataclass(kw_only=True, slots=True, frozen=True)
class ParsedFrame:
    """Один успешно декодированный кадр."""

    frame_type: int
    payload: PayloadT


# --- Decoders --------------------------------------------------------------


def _decode_link_statistics(payload: bytes) -> LinkStatistics:
    if len(payload) != 10:
        raise ValueError(f"LINK_STATISTICS payload must be 10 B, got {len(payload)}")
    # >BBBbBBBBBb = u8,u8,u8,i8, u8,u8,u8, u8,u8,i8  → 10 байт.
    (
        rssi_1_raw,
        rssi_2_raw,
        uplink_lq,
        uplink_snr,
        antenna,
        rf_mode,
        tx_power_enum,
        drssi_raw,
        dlq,
        dsnr,
    ) = struct.unpack(">BBBbBBBBBb", payload)
    return LinkStatistics(
        # wire-формат "uint8 dBm × -1" → actual dBm (negative).
        uplink_rssi_1_dbm=-rssi_1_raw,
        uplink_rssi_2_dbm=-rssi_2_raw,
        uplink_lq=uplink_lq,
        uplink_snr_db=uplink_snr,
        diversity_antenna=antenna,
        rf_mode=rf_mode,
        uplink_tx_power_mw=TX_POWER_MW.get(tx_power_enum, TX_POWER_UNKNOWN),
        downlink_rssi_dbm=-drssi_raw,
        downlink_lq=dlq,
        downlink_snr_db=dsnr,
    )


def _decode_battery_sensor(payload: bytes) -> BatterySensor:
    if len(payload) != 8:
        raise ValueError(f"BATTERY_SENSOR payload must be 8 B, got {len(payload)}")
    voltage_raw, current_raw, u_hi, u_mid, u_lo, remaining = struct.unpack(">HHBBBB", payload)
    used_capacity_mah = (u_hi << 16) | (u_mid << 8) | u_lo
    return BatterySensor(
        voltage_v=voltage_raw / 10.0,
        current_a=current_raw / 10.0,
        used_capacity_mah=used_capacity_mah,
        remaining_percent=remaining,
    )


def _decode_flight_mode(payload: bytes) -> FlightMode:
    # null-terminated ASCII; всё после первого \0 — мусор (padding или garbage),
    # обрезаем. errors="replace" — на случай non-ASCII байтов: не падаем.
    raw = payload.split(b"\x00", 1)[0]
    return FlightMode(mode=raw.decode("ascii", errors="replace"))


def _decode_gps(payload: bytes) -> Gps:
    if len(payload) != 15:
        raise ValueError(f"GPS payload must be 15 B, got {len(payload)}")
    lat, lon, gs_raw, hdg_raw, alt_raw, sats = struct.unpack(">iiHHHB", payload)
    return Gps(
        latitude_deg=lat / 1e7,
        longitude_deg=lon / 1e7,
        ground_speed_kmh=gs_raw / 10.0,
        heading_deg=hdg_raw / 100.0,
        altitude_m=alt_raw - 1000,
        satellites=sats,
    )


def _decode_attitude(payload: bytes) -> Attitude:
    if len(payload) != 6:
        raise ValueError(f"ATTITUDE payload must be 6 B, got {len(payload)}")
    pitch, roll, yaw = struct.unpack(">hhh", payload)
    return Attitude(
        pitch_rad=pitch / 10000.0,
        roll_rad=roll / 10000.0,
        yaw_rad=yaw / 10000.0,
    )


_DECODERS: dict[int, object] = {
    CRSF_FT_LINK_STATISTICS: _decode_link_statistics,
    CRSF_FT_BATTERY_SENSOR: _decode_battery_sensor,
    CRSF_FT_FLIGHT_MODE: _decode_flight_mode,
    CRSF_FT_GPS: _decode_gps,
    CRSF_FT_ATTITUDE: _decode_attitude,
}


# --- Parser ----------------------------------------------------------------


class CrsfTelemetryParser:
    """Stream-парсер CRSF: ``feed(bytes) → list[ParsedFrame]``.

    Внутри держит ``bytearray`` буфер; partial-кадры между ``feed`` сохраняются.
    На любом мусоре (bad sync, bad len, bad CRC) ресинкается вперёд, выдавая
    WARNING в инжектированный лог. Возвращает только успешно декодированные
    кадры известных типов; неизвестные типы тихо проглатываются.
    """

    def __init__(self, log_: logging.Logger | None = None) -> None:
        self._buf = bytearray()
        self._log = log_ if log_ is not None else logging.getLogger("crsf-telemetry")

    def feed(self, data: bytes) -> list[ParsedFrame]:
        """Подкормить байты, вытащить все полные кадры из буфера."""
        if data:
            self._buf.extend(data)
        out: list[ParsedFrame] = []
        while True:
            prev_len = len(self._buf)
            frame = self._try_parse_one()
            if frame is not None:
                out.append(frame)
                continue
            # frame is None: либо ждём больше данных, либо был resync (без выдачи).
            if len(self._buf) == prev_len:
                # Прогресса нет → ждём следующего feed.
                break
        return out

    @property
    def buffered(self) -> int:
        """Сколько байтов сейчас в внутреннем буфере (для тестов и диагностики)."""
        return len(self._buf)

    def _try_parse_one(self) -> ParsedFrame | None:
        # 1. Ресинк до sync-байта. Дропы — DEBUG, чтобы не спамить под мусором.
        drops = 0
        while self._buf and self._buf[0] != CRSF_SYNC_FC:
            del self._buf[0]
            drops += 1
        if drops:
            self._log.debug("crsf: resync dropped %d byte(s)", drops)

        # 2. Минимум: sync(1) + len(1) + type(1) + crc(1) = 4 байта.
        if len(self._buf) < 4:
            return None

        length = self._buf[1]
        if length < _MIN_LEN_BYTE or length > _MAX_LEN_BYTE:
            self._log.warning(
                "crsf: invalid len byte %d (must be %d..%d), dropping sync",
                length,
                _MIN_LEN_BYTE,
                _MAX_LEN_BYTE,
            )
            del self._buf[0]
            return None

        frame_total = 2 + length  # sync + len + body(length)
        if len(self._buf) < frame_total:
            return None  # ждём ещё байтов

        # body = [type, ...payload..., crc]
        frame_type = self._buf[2]
        # CRC считается от [type..payload] = self._buf[2 : 2+length-1]
        crc_payload_end = 2 + length - 1
        crc_received = self._buf[crc_payload_end]
        crc_computed = crc8(bytes(self._buf[2:crc_payload_end]))

        if crc_received != crc_computed:
            self._log.warning(
                "crsf: bad CRC for type 0x%02X (expected 0x%02X, got 0x%02X), dropping sync",
                frame_type,
                crc_computed,
                crc_received,
            )
            del self._buf[0]
            return None

        payload = bytes(self._buf[3:crc_payload_end])
        del self._buf[:frame_total]

        decoder = _DECODERS.get(frame_type)
        if decoder is None:
            # Неизвестный type — кадр валиден, но мы его не дешифруем.
            self._log.debug(
                "crsf: unknown frame type 0x%02X (%d B payload)", frame_type, len(payload)
            )
            return None

        try:
            decoded = decoder(payload)  # type: ignore[operator]
        except (ValueError, struct.error, UnicodeDecodeError) as e:
            self._log.warning("crsf: decode failed for type 0x%02X: %s", frame_type, e)
            return None

        return ParsedFrame(frame_type=frame_type, payload=decoded)


# --- TelemetryState --------------------------------------------------------

DEFAULT_STALE_SEC: float = 5.0


@dataclass(slots=True)
class TelemetryState:
    """In-memory snapshot последней принятой телеметрии каждого типа.

    Каждое поле — пара ``(payload | None, last_update_ts | None)``. ``None`` в
    ts означает "никогда не приходило". ``is_stale`` возвращает True для
    отсутствующих ИЛИ устаревших данных (``now - ts > threshold``).
    """

    link: LinkStatistics | None = None
    link_ts: float | None = None
    battery: BatterySensor | None = None
    battery_ts: float | None = None
    flight_mode: FlightMode | None = None
    flight_mode_ts: float | None = None
    gps: Gps | None = None
    gps_ts: float | None = None
    attitude: Attitude | None = None
    attitude_ts: float | None = None

    def apply(self, frame: ParsedFrame, now: float) -> None:
        """Обновить соответствующее поле по типу payload в декодированном кадре."""
        payload = frame.payload
        if isinstance(payload, LinkStatistics):
            self.link = payload
            self.link_ts = now
        elif isinstance(payload, BatterySensor):
            self.battery = payload
            self.battery_ts = now
        elif isinstance(payload, FlightMode):
            self.flight_mode = payload
            self.flight_mode_ts = now
        elif isinstance(payload, Gps):
            self.gps = payload
            self.gps_ts = now
        elif isinstance(payload, Attitude):
            self.attitude = payload
            self.attitude_ts = now

    @staticmethod
    def is_stale(ts: float | None, now: float, threshold_s: float) -> bool:
        """True если данных нет (ts is None) или старше threshold секунд."""
        if ts is None:
            return True
        return (now - ts) > threshold_s
