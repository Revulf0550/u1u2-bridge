"""Loopback bench: RS485 round-trip между двумя адаптерами на одной Pi.

⚠️  ВНИМАНИЕ: тест эмулирует НЕ production data-flow.
   См. секцию «Соответствие production» ниже перед интерпретацией результатов.
   §7.1 HANDOFF закрыт документально (вариант A+C) — не на основании
   PASS этого скрипта, а через raw `stty` + `cat`/`printf` (6/6 раз
   1000/1000 байт без потерь на 1200 бод).

## Архитектура

Один Python-процесс, два потока. Каждый управляет своим USB-RS485
адаптером. Между адаптерами проложены три перемычки между клеммниками:

    Waveshare #A  A+   <->  Waveshare #B  A+
    Waveshare #A  B-   <->  Waveshare #B  B-
    Waveshare #A  GND  <->  Waveshare #B  GND

Pinger (порт A): шлёт фрейм с инкрементным seq, ждёт ответа.
Echoer (порт B): читает фрейм, тут же шлёт его обратно тем же содержимым.
Один цикл = 2 переключения direction RS485 (A: TX→RX; B: RX→TX→RX).

## Запуск

    python3 bench/loopback.py --port-a /dev/ttyACM-CRSF1 \\
                              --port-b /dev/ttyACM-CRSF2 \\
                              --baud 9600 --rate 10 --duration 10

## Соответствие production

Bench эмулирует **bidirectional ping-pong на одной RS485 шине через два
адаптера на одной Pi**. В production такого сценария НЕТ:

- На u2-pi: ELRS Tx → Waveshare → `common/crsf_bridge.py` → UDP
  (one-way streaming от Tx к bridge'у).
- На u1-pi: UDP → `common/crsf_bridge.py` → Waveshare → П1 trainer-port
  (one-way streaming от bridge'a к П1).
- Между u1-pi и u2-pi — IP-сеть (CPE710 / WireGuard), не общая RS485 шина.

Реальный auto-direction Waveshare в production переключается только в
**одну сторону** на каждом адаптере (TX-only на u2-side, RX-only на u1-side,
или наоборот для телеметрии) — типичный CRSF use case, поддержан индустрией.
Bench нагружает auto-direction быстрыми DE-переключениями с **обеих**
сторон одновременно — это отдельный режим, и его нестабильность
**не означает, что production-flow сломан**.

## Limitations

- На high-baud (420k) bidirectional ping-pong требует стабильного DE на
  двух адаптерах одновременно. Waveshare USB-TO-RS485 (B) с авто-DE на
  CH343G+SP485EEN это не обеспечивает — наблюдались колебания
  `echoer.bytes_received` от 22 до 2073 байт между прогонами без
  изменений в коде или железе. Для bidirectional нагрузки на высоких
  baud нужен ручной TIOCSRS485 mode (не реализовано — production его
  не требует).
- На low-baud (1200, 9600) bench показывает корректную физику в
  forward-направлении, но B→A путь зависит от auto-direction timing
  и может давать `matched=0` даже на «здоровом» железе. Физика
  подтверждается отдельно через raw `stty raw -echo` + `cat`/`printf` —
  без bench-скрипта (см. §7.1 HANDOFF, секция «Что подтверждено
  raw-тестом»).

Скрипт не входит в `verify.ps1` (это инструмент, не production-код).
Pure helpers `compute_echo_deadline` / `compute_period_cap` покрыты
unit-тестами в `tests/unit/test_loopback.py` (включая регрессию `207ff66`
на invariant `cap ≥ deadline`).
"""

import argparse
import logging
import signal
import sys
import threading
import time
from types import FrameType

import serial

DEFAULT_BAUD = 420_000
DEFAULT_DURATION = 30.0
DEFAULT_RATE_HZ = 500.0

# Фрейм: 0xC8 (CRSF sync) + LEN(1) + TYPE(1) + 22 байт payload + 1 байт CRC-слот.
# Полная длина 26 байт — типичный CRSF-кадр на 500 Hz.
# В payload пишем seq в первых двух байтах (lo, hi), остальное — повтор паттерна.
FRAME_SIZE = 26
CRSF_SYNC = 0xC8

log = logging.getLogger("bench-loopback")


def compute_echo_deadline(baud: int, frame_size: int = FRAME_SIZE) -> float:
    """Бюджет на echo round-trip, в секундах.

    Два frame_tx_time (туда + обратно) плюс 20 мс на накопленный overhead:
    USB-CDC latency с обеих сторон, переключение DE на Waveshare,
    `serial.read(timeout=0.01)` slack, Python-парсинг кадра у echoer'а.
    На бенче 1200/2Hz измеренный RT ≈ 443 мс при чистом wire-time 433 мс
    → реальный overhead ~10 мс. Берём 20 мс с запасом ×2.

    На high-baud (420k, frame_tx ≈ 620 µs) сам margin доминирует, итог
    ≈ 21 мс — этого с запасом хватает на любую конфигурацию.
    """
    frame_tx_time = frame_size * 10 / baud
    return 2 * frame_tx_time + 0.020


def compute_period_cap(period: float, echo_deadline: float) -> float:
    """Per-cycle потолок на deadline (отсчитывается от `next_tx`).

    Оставляет 5 мс на setup следующей итерации, но НИКОГДА не меньше
    echo_deadline — иначе на low-baud cap отстригает echo, не дав ему доехать,
    и весь тест false-FAIL'ит независимо от физики (баг 207ff66).
    """
    return max(period - 0.005, echo_deadline)


def make_frame(seq: int) -> bytes:
    """Сгенерировать кадр с seq, узнаваемым на приёмной стороне."""
    seq_lo = seq & 0xFF
    seq_hi = (seq >> 8) & 0xFF
    # Заполнить payload повтором (seq_lo, seq_hi) 11 раз = 22 байта.
    payload = bytes((seq_lo, seq_hi) * 11)
    return bytes([CRSF_SYNC, len(payload) + 2, 0x16]) + payload + bytes([seq_lo])


def parse_seq(frame: bytes) -> int | None:
    """Извлечь seq из кадра. None если sync byte не совпадает."""
    if len(frame) < FRAME_SIZE or frame[0] != CRSF_SYNC:
        return None
    return frame[3] | (frame[4] << 8)


def open_port(dev: str, baud: int) -> serial.Serial:
    """Открыть serial-порт с теми же настройками, что и crsf_bridge.py."""
    ser = serial.Serial(
        dev,
        baudrate=baud,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=0.01,
        write_timeout=0.05,
        rtscts=False,
        dsrdtr=False,
    )
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


class Echoer(threading.Thread):
    """Поток B: читает фреймы и тут же отсылает их обратно."""

    def __init__(self, ser: serial.Serial, stop_event: threading.Event) -> None:
        super().__init__(daemon=True, name="echoer")
        self.ser = ser
        self.stop_event = stop_event
        self.frames_echoed = 0
        self.bytes_received = 0
        self._buf = bytearray()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                chunk = self.ser.read(FRAME_SIZE * 4)
            except serial.SerialException:
                continue
            if not chunk:
                continue
            self._buf.extend(chunk)
            self.bytes_received += len(chunk)
            # Извлекаем кадры по sync byte, пока в буфере хватает данных.
            while len(self._buf) >= FRAME_SIZE:
                if self._buf[0] != CRSF_SYNC:
                    idx = self._buf.find(CRSF_SYNC, 1)
                    if idx < 0:
                        self._buf.clear()
                        break
                    del self._buf[:idx]
                    continue
                frame = bytes(self._buf[:FRAME_SIZE])
                del self._buf[:FRAME_SIZE]
                # Echo back immediately.
                try:
                    self.ser.write(frame)
                    self.frames_echoed += 1
                except (serial.SerialTimeoutException, serial.SerialException):
                    pass


class Pinger(threading.Thread):
    """Поток A: шлёт кадры с seq, считает успешные round-trip'ы."""

    def __init__(
        self,
        ser: serial.Serial,
        baud: int,
        rate_hz: float,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True, name="pinger")
        self.ser = ser
        self.period = 1.0 / rate_hz
        self.stop_event = stop_event
        self.echo_deadline = compute_echo_deadline(baud)
        if self.echo_deadline > self.period - 0.005:
            log.warning(
                "echo_deadline %.0f ms ≥ period %.0f ms − 5 ms setup margin: "
                "rate too high for baud, pinger will fall behind schedule "
                "(expect false FAILs)",
                self.echo_deadline * 1000,
                self.period * 1000,
            )
        self.sent = 0
        self.received = 0
        self.matched = 0
        self.bytes_received = 0
        self._buf = bytearray()

    def _try_read_frame(self, deadline: float) -> bytes | None:
        """Читать порт до тех пор, пока не наберём фрейм или не вышел deadline."""
        while time.monotonic() < deadline:
            try:
                chunk = self.ser.read(FRAME_SIZE)
            except serial.SerialException:
                return None
            if chunk:
                self._buf.extend(chunk)
                self.bytes_received += len(chunk)
            while len(self._buf) >= FRAME_SIZE:
                if self._buf[0] != CRSF_SYNC:
                    idx = self._buf.find(CRSF_SYNC, 1)
                    if idx < 0:
                        self._buf.clear()
                        break
                    del self._buf[:idx]
                    continue
                frame = bytes(self._buf[:FRAME_SIZE])
                del self._buf[:FRAME_SIZE]
                return frame
        return None

    def run(self) -> None:
        next_tx = time.monotonic()
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now < next_tx:
                time.sleep(max(0.0, next_tx - now))
                continue
            seq = self.sent
            frame = make_frame(seq)
            try:
                self.ser.write(frame)
            except (serial.SerialTimeoutException, serial.SerialException):
                self.sent += 1
                next_tx += self.period
                continue
            self.sent += 1
            deadline = min(
                time.monotonic() + self.echo_deadline,
                next_tx + compute_period_cap(self.period, self.echo_deadline),
            )
            received = self._try_read_frame(deadline)
            if received is not None:
                self.received += 1
                received_seq = parse_seq(received)
                if received_seq == seq:
                    self.matched += 1
            next_tx += self.period


def verdict(loss_pct: float, corruption_pct: float) -> tuple[str, int]:
    """Дать вердикт по loss и corruption. Возвращает (label, exit_code)."""
    if loss_pct < 1.0 and corruption_pct < 1.0:
        return "PASS — RS485 auto-direction works (§7.1 closed)", 0
    if loss_pct < 10.0 and corruption_pct < 10.0:
        return "MARGINAL — auto-direction strained, consider manual DE-control", 1
    return "FAIL — auto-direction broken, manual TIOCSRS485 required", 2


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--port-a",
        required=True,
        help="порт pinger'а (например /dev/ttyACM-CRSF1)",
    )
    p.add_argument(
        "--port-b",
        required=True,
        help="порт echoer'а (например /dev/ttyACM-CRSF2)",
    )
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument("--duration", type=float, default=DEFAULT_DURATION, help="секунд")
    p.add_argument(
        "--rate",
        type=float,
        default=DEFAULT_RATE_HZ,
        help="частота отправки кадров pinger'ом, Гц",
    )
    args = p.parse_args()

    # Для bench-инструмента простой формат без timestamp — чище в терминале.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    log.info(
        "opening port-a=%s  port-b=%s  @ %d baud",
        args.port_a,
        args.port_b,
        args.baud,
    )
    ser_a = open_port(args.port_a, args.baud)
    ser_b = open_port(args.port_b, args.baud)

    stop_event = threading.Event()

    def on_sig(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    echoer = Echoer(ser_b, stop_event)
    pinger = Pinger(ser_a, args.baud, args.rate, stop_event)

    log.info(
        "running: pinger @ %.0f Hz  for %.0f s  (Ctrl-C to stop early)",
        args.rate,
        args.duration,
    )
    log.info("=" * 72)

    start = time.monotonic()
    echoer.start()
    pinger.start()

    last_stat = start
    try:
        while not stop_event.is_set():
            now = time.monotonic()
            if now - start >= args.duration:
                break
            if now - last_stat >= 1.0:
                elapsed = now - start
                lost = pinger.sent - pinger.received
                loss_pct = (lost / pinger.sent * 100) if pinger.sent else 0.0
                log.info(
                    "  t=%5.1fs  sent=%6d  echoed_back=%6d  matched=%6d  loss=%5.2f%%",
                    elapsed,
                    pinger.sent,
                    pinger.received,
                    pinger.matched,
                    loss_pct,
                )
                last_stat = now
            time.sleep(0.05)
    except KeyboardInterrupt:
        stop_event.set()

    stop_event.set()
    pinger.join(timeout=1.0)
    echoer.join(timeout=1.0)

    elapsed = time.monotonic() - start
    sent = pinger.sent
    received = pinger.received
    matched = pinger.matched
    lost = sent - received
    corrupted = received - matched
    loss_pct = (lost / sent * 100) if sent else 0.0
    corruption_pct = (corrupted / sent * 100) if sent else 0.0

    log.info("=" * 72)
    log.info(
        "Test complete after %.1fs @ %d baud, %.0f Hz",
        elapsed,
        args.baud,
        args.rate,
    )
    log.info("  Frames sent (pinger):         %d", sent)
    log.info("  Frames echoed back (recv):    %d", received)
    log.info("  Frames with matching seq:     %d", matched)
    log.info("  Echoer-side frames echoed:    %d", echoer.frames_echoed)
    log.info("  Pinger bytes RX:              %d", pinger.bytes_received)
    log.info("  Echoer bytes RX:              %d", echoer.bytes_received)
    log.info("  Lost frames:                  %d  (%.2f%%)", lost, loss_pct)
    log.info(
        "  Corrupted frames (wrong seq): %d  (%.2f%%)",
        corrupted,
        corruption_pct,
    )
    log.info("=" * 72)

    label, code = verdict(loss_pct, corruption_pct)
    log.info(label)

    ser_a.close()
    ser_b.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
