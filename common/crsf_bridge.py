"""CRSF UART <-> UDP bridge для IP-сети поверх TP-Link CPE710.

Прозрачно прокидывает байты между serial-портом и UDP-сокетом.
CRSF — пакетный протокол на 420 000 бод, кадры до 64 байт, 250–500 Hz.

Один скрипт работает в двунаправленном peer-to-peer режиме:
  - читает UART, шлёт UDP на peer (тот же порт у партнёра)
  - слушает UDP на listen-port, пишет всё в UART

Пример (на У2, мост к ELRS-модулю №1)::

    crsf_bridge.py --serial /dev/ttyUSB-CRSF1 \\
                   --listen 0.0.0.0:14550 \\
                   --peer 192.168.1.20:14550

Пример (на У1, мост к П1 trainer-port)::

    crsf_bridge.py --serial /dev/ttyUSB-CRSF1 \\
                   --listen 0.0.0.0:14550 \\
                   --peer 192.168.1.10:14550

Переподключение UART при отсоединении адаптера выполняется автоматически.
"""

import argparse
import logging
import select
import signal
import socket
import sys
import time
from types import FrameType
from typing import Any

import serial

CRSF_DEFAULT_BAUD = 420_000
CRSF_MAX_FRAME = 64
SELECT_TIMEOUT = 0.005  # 5 мс


def parse_addr(s: str) -> tuple[str, int]:
    """Разобрать строку 'host:port' в кортеж (host, port).

    Используется rsplit, чтобы корректно работать с IPv6-адресами в форме [::1]:port.
    """
    host, port = s.rsplit(":", 1)
    return host, int(port)


def open_serial(dev: str, baud: int) -> serial.Serial:
    """Открыть serial-порт с настройками под CRSF (8N1, неблокирующее чтение)."""
    ser = serial.Serial(
        dev,
        baudrate=baud,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=0,  # неблокирующее чтение
        write_timeout=0.05,
        rtscts=False,
        dsrdtr=False,
    )
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def open_udp(listen: tuple[str, int]) -> socket.socket:
    """Открыть UDP-сокет на listen-адресе. Буферы 64 KiB — важно при джиттере Wi-Fi."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # критично при джиттере 5–10 мс на Wi-Fi мосте
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
    sock.bind(listen)
    sock.setblocking(False)
    return sock


def main() -> int:
    """Основная функция: парс аргументов, цикл UART↔UDP, авто-реконнект, статистика."""
    p = argparse.ArgumentParser()
    p.add_argument("--serial", required=True, help="например /dev/ttyUSB-CRSF1")
    p.add_argument("--baud", type=int, default=CRSF_DEFAULT_BAUD)
    p.add_argument(
        "--listen",
        required=True,
        help="ip:port для приёма от партнёра (обычно 0.0.0.0:14550)",
    )
    p.add_argument(
        "--peer",
        required=True,
        help="ip:port партнёра, куда отправлять с UART",
    )
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("crsf-bridge")

    listen = parse_addr(args.listen)
    peer = parse_addr(args.peer)
    log.info(
        "serial=%s baud=%d listen=%s:%d peer=%s:%d",
        args.serial,
        args.baud,
        *listen,
        *peer,
    )

    sock = open_udp(listen)

    stop = {"flag": False}

    def on_sig(_signum: int, _frame: FrameType | None) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_sig)
    signal.signal(signal.SIGINT, on_sig)

    s2u_bytes = u2s_bytes = 0
    last_stat = time.monotonic()
    stat_period = 10.0

    ser: serial.Serial | None = None
    while not stop["flag"]:
        # автопереподключение UART
        if ser is None:
            try:
                ser = open_serial(args.serial, args.baud)
                log.info("uart opened: %s", args.serial)
            except (serial.SerialException, OSError) as e:
                log.warning("uart open failed: %s, retry in 1s", e)
                time.sleep(1)
                continue

        try:
            r, _, _ = select.select([ser.fileno(), sock.fileno()], [], [], SELECT_TIMEOUT)
        except (InterruptedError, OSError):
            continue

        if ser.fileno() in r:
            try:
                data: Any = ser.read(CRSF_MAX_FRAME * 4)
            except (serial.SerialException, OSError) as e:
                log.warning("uart read failed: %s — reopening", e)
                ser.close()
                ser = None
                continue
            if data:
                try:
                    sock.sendto(data, peer)
                    s2u_bytes += len(data)
                except OSError as e:
                    log.warning("udp send failed: %s", e)

        if sock.fileno() in r:
            try:
                data, _ = sock.recvfrom(2048)
            except BlockingIOError:
                data = b""
            if data and ser is not None:
                try:
                    ser.write(data)
                    u2s_bytes += len(data)
                except (
                    serial.SerialTimeoutException,
                    serial.SerialException,
                    OSError,
                ) as e:
                    log.warning("uart write failed: %s", e)

        now = time.monotonic()
        if now - last_stat >= stat_period:
            log.info(
                "uart->udp=%d B/s  udp->uart=%d B/s",
                int(s2u_bytes / stat_period),
                int(u2s_bytes / stat_period),
            )
            s2u_bytes = u2s_bytes = 0
            last_stat = now

    log.info("shutting down")
    if ser:
        ser.close()
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
