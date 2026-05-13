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
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
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


def bytes_to_hex(data: bytes) -> str:
    """Форматирует байты как 'AB CD EF' для дебаг-логов CRSF-кадров."""
    return " ".join(f"{b:02X}" for b in data)


def get_version() -> str:
    """Возвращает версию пакета. Fallback если запущен из git-клонa без install."""
    try:
        return version("u1u2-bridge")
    except PackageNotFoundError:
        return "0.0.0+local"


CRSF_COMMON_BAUDS = frozenset({115_200, 420_000, 921_600})
REQUIRED_ENV_KEYS = ("SERIAL_DEV", "BAUD", "LISTEN", "PEER")
MIN_USER_PORT = 1024
MAX_PORT = 65_535


def parse_env_text(text: str) -> tuple[dict[str, str], list[str]]:
    """Распарсить содержимое systemd-style env-файла.

    Возвращает (env, errors). Поддерживает: KEY=VALUE, # comments, пустые строки,
    значения в одинарных/двойных кавычках. Не делает shell-eval и подстановок —
    зеркало того, как systemd `EnvironmentFile=` читает файл.
    """
    env: dict[str, str] = {}
    errors: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            errors.append(f"line {line_no}: no '=' in {line!r}")
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            errors.append(f"line {line_no}: empty key in {line!r}")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env[key] = value
    return env, errors


def validate_env_text(text: str) -> tuple[list[str], list[str]]:
    """Проверить env-файл для CRSF-моста. Возвращает (errors, warnings).

    Каждая запись — однострочное человекочитаемое сообщение. Errors → exit 1,
    warnings допустимы. Файл считается валидным, если errors пустой.
    """
    env, errors = parse_env_text(text)
    warnings: list[str] = []

    for k in REQUIRED_ENV_KEYS:
        if k not in env:
            errors.append(f"missing required key: {k}")

    if "BAUD" in env:
        try:
            baud = int(env["BAUD"])
        except ValueError:
            errors.append(f"BAUD={env['BAUD']!r}: not an integer")
        else:
            if baud not in CRSF_COMMON_BAUDS:
                warnings.append(f"BAUD={baud}: not a common CRSF baud rate")

    for k in ("LISTEN", "PEER"):
        if k not in env:
            continue
        try:
            _, port = parse_addr(env[k])
        except ValueError as e:
            errors.append(f"{k}={env[k]!r}: invalid host:port ({e})")
            continue
        if not MIN_USER_PORT <= port <= MAX_PORT:
            warnings.append(f"{k} port {port}: outside [{MIN_USER_PORT}, {MAX_PORT}]")

    if "SERIAL_DEV" in env:
        dev = env["SERIAL_DEV"]
        if not dev.startswith("/dev/"):
            warnings.append(f"SERIAL_DEV={dev!r}: doesn't look like a Linux device path")

    return errors, warnings


def _addr_port(addr: str | None) -> int | None:
    """Достать порт из 'host:port'. None если пусто/не парсится — для cross-check."""
    if not addr:
        return None
    try:
        _, port = parse_addr(addr)
    except ValueError:
        return None
    return port


def cross_check_envs(
    envs: list[tuple[str, dict[str, str]]],
) -> tuple[list[str], list[str]]:
    """Попарно проверить env-файлы CRSF на конфликты ресурсов и расхождения настроек.

    Принимает список `(label, env_dict)`. `label` — короткое имя для сообщений.
    Возвращает (errors, warnings). Меньше двух файлов — пустой результат.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if len(envs) < 2:
        return errors, warnings

    for i, (label_a, env_a) in enumerate(envs):
        for label_b, env_b in envs[i + 1 :]:
            port_a = _addr_port(env_a.get("LISTEN"))
            if port_a is not None and port_a == _addr_port(env_b.get("LISTEN")):
                errors.append(f"{label_a} and {label_b} both LISTEN on port {port_a}")
            dev_a = env_a.get("SERIAL_DEV")
            if dev_a and dev_a == env_b.get("SERIAL_DEV"):
                errors.append(f"{label_a} and {label_b} share SERIAL_DEV={dev_a}")
            peer_a = env_a.get("PEER")
            if peer_a and peer_a == env_b.get("PEER"):
                warnings.append(f"{label_a} and {label_b} have identical PEER={peer_a}")

    bauds = {env["BAUD"] for _, env in envs if "BAUD" in env}
    if len(bauds) > 1:
        warnings.append(f"BAUD differs across files: {', '.join(sorted(bauds))}")

    peer_hosts: set[str] = set()
    for _, env in envs:
        peer = env.get("PEER")
        if not peer:
            continue
        try:
            host, _ = parse_addr(peer)
        except ValueError:
            continue
        peer_hosts.add(host)
    if len(peer_hosts) > 1:
        warnings.append(f"PEER hosts differ across files: {', '.join(sorted(peer_hosts))}")

    return errors, warnings


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
    p.add_argument(
        "--version",
        action="version",
        version=f"u1u2-bridge {get_version()}",
    )
    p.add_argument("--serial", help="например /dev/ttyUSB-CRSF1")
    p.add_argument("--baud", type=int, default=CRSF_DEFAULT_BAUD)
    p.add_argument(
        "--listen",
        help="ip:port для приёма от партнёра (обычно 0.0.0.0:14550)",
    )
    p.add_argument(
        "--peer",
        help="ip:port партнёра, куда отправлять с UART",
    )
    p.add_argument(
        "--check-config",
        metavar="PATH",
        nargs="+",
        help=(
            "проверить env-файл(ы) и выйти, без открытия устройств. "
            "При двух+ файлах — попарный cross-check (LISTEN/SERIAL_DEV конфликты, "
            "расхождения BAUD/PEER)."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="открыть serial+UDP, залогировать привязку, выйти (без основного цикла)",
    )
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("crsf-bridge")

    if args.check_config:
        if args.serial or args.listen or args.peer:
            log.warning("check-config mode: --serial/--listen/--peer ignored")
        parsed_envs: list[tuple[str, dict[str, str]]] = []
        total_errors = 0
        total_warnings = 0
        io_failed = False
        for path in args.check_config:
            label = Path(path).name
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError as e:
                log.error("check-config [%s]: cannot read: %s", label, e)
                io_failed = True
                continue
            env, _ = parse_env_text(text)
            errors, warnings = validate_env_text(text)
            for w in warnings:
                log.warning("check-config [%s]: %s", label, w)
            for err in errors:
                log.error("check-config [%s]: %s", label, err)
            total_errors += len(errors)
            total_warnings += len(warnings)
            parsed_envs.append((label, env))

        if len(parsed_envs) >= 2:
            x_errors, x_warnings = cross_check_envs(parsed_envs)
            for w in x_warnings:
                log.warning("check-config [cross]: %s", w)
            for err in x_errors:
                log.error("check-config [cross]: %s", err)
            total_errors += len(x_errors)
            total_warnings += len(x_warnings)

        log.info(
            "check-config: %d errors, %d warnings across %d file(s)",
            total_errors,
            total_warnings,
            len(args.check_config),
        )
        if io_failed:
            return 2
        return 1 if total_errors else 0

    missing = [
        name
        for name, val in (("serial", args.serial), ("listen", args.listen), ("peer", args.peer))
        if not val
    ]
    if missing:
        p.error("the following arguments are required: --" + ", --".join(missing))

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

    if args.dry_run:
        try:
            ser_check = open_serial(args.serial, args.baud)
        except (serial.SerialException, OSError) as e:
            log.error("dry-run: uart open failed: %s", e)
            sock.close()
            return 1
        log.info(
            "dry-run: uart=%s @ %d ok, udp bound %s, peer %s:%d",
            args.serial,
            args.baud,
            sock.getsockname(),
            *peer,
        )
        ser_check.close()
        sock.close()
        return 0

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
