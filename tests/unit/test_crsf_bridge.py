"""Unit-тесты для `common.crsf_bridge`.

Тестируем три зоны:
1. `parse_addr` — pure-функция, проверяем валидные/невалидные входы.
2. `open_serial` — проверяем, что `pyserial.Serial` вызывается с правильными
   параметрами (8N1, неблокирующий timeout=0, очистка буферов).
3. `open_udp` — проверяем, что UDP-сокет настроен с REUSEADDR, увеличенными
   буферами 64 KiB и неблокирующим режимом.

Главная цель этих тестов — фиксация **наблюдаемых конфигов**, которые
критичны для latency и стабильности. Если кто-то «оптимизирует» buffer-size
с 64 KiB на 8 KiB — тест немедленно упадёт.
"""

import socket
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import serial
from common.crsf_bridge import (
    bytes_to_hex,
    get_version,
    main,
    open_serial,
    open_udp,
    parse_addr,
    parse_env_text,
    validate_env_text,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


# --- parse_addr --------------------------------------------------------------


class TestParseAddr:
    """parse_addr должен корректно разбирать 'host:port'."""

    def test_ipv4(self) -> None:
        assert parse_addr("192.168.1.10:14550") == ("192.168.1.10", 14550)

    def test_hostname(self) -> None:
        assert parse_addr("orangepi-u1.local:5600") == ("orangepi-u1.local", 5600)

    def test_wildcard_listen(self) -> None:
        assert parse_addr("0.0.0.0:14550") == ("0.0.0.0", 14550)

    def test_ipv6_in_brackets(self) -> None:
        """IPv6 в форме [::1]:port должен разбираться через rsplit."""
        assert parse_addr("[::1]:14550") == ("[::1]", 14550)

    def test_no_port_raises(self) -> None:
        """Адрес без двоеточия — невалиден, должен бросить ValueError."""
        with pytest.raises(ValueError):
            parse_addr("192.168.1.10")

    def test_non_numeric_port_raises(self) -> None:
        """Порт должен быть числом."""
        with pytest.raises(ValueError):
            parse_addr("host:not-a-port")


# --- open_serial -------------------------------------------------------------


class TestOpenSerial:
    """open_serial должен вызывать pyserial с правильными параметрами для CRSF.

    Эти параметры — часть контракта моста: 8N1, неблокирующее чтение,
    очистка буферов. Если их случайно изменят — поведение под нагрузкой
    станет непредсказуемым.
    """

    def test_called_with_8n1_nonblocking(self, mocker: "MockerFixture") -> None:
        """Параметры: 8 бит, без чётности, 1 стоп-бит, неблокирующий timeout."""
        mock_serial = mocker.patch("common.crsf_bridge.serial.Serial")
        open_serial("/dev/ttyUSB0", 420_000)

        mock_serial.assert_called_once()
        kwargs = mock_serial.call_args.kwargs
        assert kwargs["baudrate"] == 420_000
        assert kwargs["bytesize"] == 8
        assert kwargs["parity"] == "N"
        assert kwargs["stopbits"] == 1
        assert kwargs["timeout"] == 0, "Чтение должно быть неблокирующим"
        assert kwargs["write_timeout"] == 0.05
        assert kwargs["rtscts"] is False
        assert kwargs["dsrdtr"] is False

    def test_buffers_reset_after_open(self, mocker: "MockerFixture") -> None:
        """После открытия буферы UART должны быть очищены — иначе подхватим мусор."""
        mock_serial = mocker.patch("common.crsf_bridge.serial.Serial")
        mock_ser_instance = mock_serial.return_value

        open_serial("/dev/ttyUSB0", 420_000)

        mock_ser_instance.reset_input_buffer.assert_called_once()
        mock_ser_instance.reset_output_buffer.assert_called_once()


# --- open_udp ----------------------------------------------------------------


class TestOpenUdp:
    """open_udp настраивает UDP-сокет с буферами 64 KiB и REUSEADDR.

    Буферы критичны при джиттере Wi-Fi-моста 5-10 мс — без них теряем пакеты.
    """

    def test_address_family_inet_dgram(self, mocker: "MockerFixture") -> None:
        """UDP-сокет: AF_INET + SOCK_DGRAM."""
        mock_socket = mocker.patch("common.crsf_bridge.socket.socket")
        open_udp(("0.0.0.0", 14550))

        mock_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)

    def test_reuseaddr_enabled(self, mocker: "MockerFixture") -> None:
        """SO_REUSEADDR обязателен — иначе после рестарта systemd 'Address in use'."""
        mock_socket = mocker.patch("common.crsf_bridge.socket.socket")
        mock_sock_instance = mock_socket.return_value

        open_udp(("0.0.0.0", 14550))

        mock_sock_instance.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def test_rcvbuf_64kib(self, mocker: "MockerFixture") -> None:
        """RCVBUF должен быть 65536 (64 KiB) — критично при Wi-Fi джиттере."""
        mock_socket = mocker.patch("common.crsf_bridge.socket.socket")
        mock_sock_instance = mock_socket.return_value

        open_udp(("0.0.0.0", 14550))

        mock_sock_instance.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)

    def test_sndbuf_64kib(self, mocker: "MockerFixture") -> None:
        """SNDBUF тоже 65536, симметрично с RCVBUF."""
        mock_socket = mocker.patch("common.crsf_bridge.socket.socket")
        mock_sock_instance = mock_socket.return_value

        open_udp(("0.0.0.0", 14550))

        mock_sock_instance.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)

    def test_bind_and_nonblocking(self, mocker: "MockerFixture") -> None:
        """Сокет должен забиндиться на listen-адрес и стать неблокирующим."""
        mock_socket = mocker.patch("common.crsf_bridge.socket.socket")
        mock_sock_instance = mock_socket.return_value

        listen_addr = ("0.0.0.0", 14550)
        open_udp(listen_addr)

        mock_sock_instance.bind.assert_called_once_with(listen_addr)
        mock_sock_instance.setblocking.assert_called_once_with(False)


# --- bytes_to_hex ------------------------------------------------------------


class TestBytesToHex:
    """bytes_to_hex форматирует байты как 'AB CD EF' для дебаг-логов."""

    def test_empty(self) -> None:
        assert bytes_to_hex(b"") == ""

    def test_single_byte(self) -> None:
        assert bytes_to_hex(b"\xab") == "AB"

    def test_multiple_bytes(self) -> None:
        assert bytes_to_hex(b"\xab\xcd\xef") == "AB CD EF"


# --- get_version & --version flag -------------------------------------------


class TestGetVersion:
    """get_version читает версию из importlib.metadata с фолбэком."""

    def test_returns_nonempty_string(self) -> None:
        """В нормальном окружении (uv sync) пакет установлен — версия должна быть."""
        v = get_version()
        assert isinstance(v, str)
        assert v

    def test_falls_back_when_package_not_found(self, mocker: "MockerFixture") -> None:
        """Если пакет не установлен — отдаём local fallback, не падаем."""
        mocker.patch(
            "common.crsf_bridge.version",
            side_effect=PackageNotFoundError("u1u2-bridge"),
        )
        assert get_version() == "0.0.0+local"


class TestVersionFlag:
    """--version печатает 'u1u2-bridge <ver>' в stdout и выходит с кодом 0."""

    def test_version_flag_prints_and_exits(
        self,
        mocker: "MockerFixture",
        capsys: "pytest.CaptureFixture[str]",
    ) -> None:
        mocker.patch("sys.argv", ["crsf_bridge.py", "--version"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "u1u2-bridge" in captured.out


# --- --dry-run flag ----------------------------------------------------------


class TestDryRun:
    """--dry-run открывает serial+UDP, логирует привязку, выходит без основного цикла."""

    _DRY_RUN_ARGV = [
        "crsf_bridge.py",
        "--serial",
        "/dev/ttyUSB-CRSF1",
        "--listen",
        "0.0.0.0:14550",
        "--peer",
        "192.168.1.20:14550",
        "--dry-run",
    ]

    def test_dry_run_opens_and_exits_zero(self, mocker: "MockerFixture") -> None:
        """Ровно одно открытие serial (нет retry-цикла), оба ресурса закрыты, return 0."""
        mocker.patch("sys.argv", self._DRY_RUN_ARGV)
        mock_open_udp = mocker.patch("common.crsf_bridge.open_udp")
        mock_open_serial = mocker.patch("common.crsf_bridge.open_serial")

        assert main() == 0

        mock_open_udp.assert_called_once()
        mock_open_serial.assert_called_once_with("/dev/ttyUSB-CRSF1", 420_000)
        mock_open_serial.return_value.close.assert_called_once()
        mock_open_udp.return_value.close.assert_called_once()

    def test_dry_run_serial_failure_returns_nonzero(self, mocker: "MockerFixture") -> None:
        """Если UART не открылся — return 1, но UDP-сокет всё равно закрыт."""
        mocker.patch("sys.argv", self._DRY_RUN_ARGV)
        mock_open_udp = mocker.patch("common.crsf_bridge.open_udp")
        mocker.patch(
            "common.crsf_bridge.open_serial",
            side_effect=serial.SerialException("device not found"),
        )

        assert main() == 1
        mock_open_udp.return_value.close.assert_called_once()

    def test_dry_run_does_not_install_signal_handlers(self, mocker: "MockerFixture") -> None:
        """Гарантия, что dry-run выходит до сигнал-хендлеров и while-цикла."""
        mocker.patch("sys.argv", self._DRY_RUN_ARGV)
        mocker.patch("common.crsf_bridge.open_udp")
        mocker.patch("common.crsf_bridge.open_serial")
        mock_signal = mocker.patch("common.crsf_bridge.signal.signal")

        assert main() == 0
        assert mock_signal.call_count == 0


# --- parse_env_text & validate_env_text --------------------------------------


_VALID_ENV = """\
# u2 crsf-tx1 sample env
SERIAL_DEV=/dev/ttyUSB-CRSF1
BAUD=420000
LISTEN=0.0.0.0:14550
PEER=192.168.1.20:14550
"""


class TestParseEnvText:
    """parse_env_text — синтаксический парсер systemd-style env-файлов."""

    def test_happy_path(self) -> None:
        env, errs = parse_env_text(_VALID_ENV)
        assert errs == []
        assert env == {
            "SERIAL_DEV": "/dev/ttyUSB-CRSF1",
            "BAUD": "420000",
            "LISTEN": "0.0.0.0:14550",
            "PEER": "192.168.1.20:14550",
        }

    def test_comments_and_blank_lines_ignored(self) -> None:
        env, errs = parse_env_text("\n  # comment\nKEY=val\n\n# trailing\n")
        assert errs == []
        assert env == {"KEY": "val"}

    def test_strips_matched_quotes(self) -> None:
        """systemd допускает кавычки — снимаем парные одинарные/двойные."""
        env, errs = parse_env_text("A=\"quoted\"\nB='single'\nC=unquoted\n")
        assert errs == []
        assert env == {"A": "quoted", "B": "single", "C": "unquoted"}

    def test_value_with_equals_kept_intact(self) -> None:
        """KEY=a=b=c → value должен быть 'a=b=c' (partition по первому =)."""
        env, _ = parse_env_text("KEY=a=b=c\n")
        assert env["KEY"] == "a=b=c"

    def test_line_without_equals_is_error(self) -> None:
        _, errs = parse_env_text("not_an_assignment\n")
        assert len(errs) == 1
        assert "no '='" in errs[0]

    def test_empty_key_is_error(self) -> None:
        _, errs = parse_env_text("=value\n")
        assert len(errs) == 1
        assert "empty key" in errs[0]


class TestValidateEnvText:
    """validate_env_text — семантический валидатор env-файла CRSF-моста."""

    def test_happy_path_clean(self) -> None:
        errors, warnings = validate_env_text(_VALID_ENV)
        assert errors == []
        assert warnings == []

    def test_missing_required_key_is_error(self) -> None:
        env = _VALID_ENV.replace("BAUD=420000\n", "")
        errors, _ = validate_env_text(env)
        assert any("missing required key: BAUD" in e for e in errors)

    def test_non_integer_baud_is_error(self) -> None:
        errors, _ = validate_env_text(_VALID_ENV.replace("BAUD=420000", "BAUD=fast"))
        assert any("BAUD" in e and "not an integer" in e for e in errors)

    def test_uncommon_baud_is_warning_not_error(self) -> None:
        """Нестандартный baud — предупреждение, не ошибка (могут быть эксперименты)."""
        errors, warnings = validate_env_text(_VALID_ENV.replace("BAUD=420000", "BAUD=57600"))
        assert errors == []
        assert any("BAUD=57600" in w for w in warnings)

    def test_invalid_listen_is_error(self) -> None:
        errors, _ = validate_env_text(_VALID_ENV.replace("LISTEN=0.0.0.0:14550", "LISTEN=garbage"))
        assert any("LISTEN" in e and "invalid host:port" in e for e in errors)

    def test_privileged_port_is_warning(self) -> None:
        """Порт <1024 — предупреждение (требует root)."""
        errors, warnings = validate_env_text(
            _VALID_ENV.replace("LISTEN=0.0.0.0:14550", "LISTEN=0.0.0.0:80")
        )
        assert errors == []
        assert any("LISTEN port 80" in w for w in warnings)

    def test_windows_device_path_is_warning_not_error(self) -> None:
        """SERIAL_DEV=COM3 — warning: deployable env-файл должен быть Linux-путь,
        но удобно гонять --check-config на dev-машине, не блокируя проверку."""
        errors, warnings = validate_env_text(
            _VALID_ENV.replace("SERIAL_DEV=/dev/ttyUSB-CRSF1", "SERIAL_DEV=COM3")
        )
        assert errors == []
        assert any("SERIAL_DEV" in w and "COM3" in w for w in warnings)


# --- --check-config flag -----------------------------------------------------


class TestCheckConfigFlag:
    """--check-config валидирует env-файл и возвращает exit code 0/1/2."""

    def test_valid_file_returns_zero(
        self,
        mocker: "MockerFixture",
        tmp_path: Path,
    ) -> None:
        env_file = tmp_path / "crsf-tx1.env"
        env_file.write_text(_VALID_ENV, encoding="utf-8")
        mocker.patch("sys.argv", ["crsf_bridge.py", "--check-config", str(env_file)])
        assert main() == 0

    def test_invalid_file_returns_one(
        self,
        mocker: "MockerFixture",
        tmp_path: Path,
    ) -> None:
        env_file = tmp_path / "bad.env"
        env_file.write_text("SERIAL_DEV=/dev/x\nBAUD=fast\n")  # missing keys + bad BAUD
        mocker.patch("sys.argv", ["crsf_bridge.py", "--check-config", str(env_file)])
        assert main() == 1

    def test_missing_file_returns_two(
        self,
        mocker: "MockerFixture",
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "nope.env"
        mocker.patch("sys.argv", ["crsf_bridge.py", "--check-config", str(missing)])
        assert main() == 2

    def test_check_config_warns_when_other_args_present(
        self,
        mocker: "MockerFixture",
        tmp_path: Path,
        caplog: "pytest.LogCaptureFixture",
    ) -> None:
        env_file = tmp_path / "ok.env"
        env_file.write_text(_VALID_ENV, encoding="utf-8")
        mocker.patch(
            "sys.argv",
            [
                "crsf_bridge.py",
                "--check-config",
                str(env_file),
                "--serial",
                "/dev/foo",
            ],
        )
        with caplog.at_level("WARNING"):
            assert main() == 0
        assert any("ignored" in r.message for r in caplog.records)

    def test_check_config_does_not_open_serial_or_udp(
        self,
        mocker: "MockerFixture",
        tmp_path: Path,
    ) -> None:
        """check-config — чисто bookkeeping, никаких open_serial/open_udp."""
        env_file = tmp_path / "ok.env"
        env_file.write_text(_VALID_ENV, encoding="utf-8")
        mock_open_udp = mocker.patch("common.crsf_bridge.open_udp")
        mock_open_serial = mocker.patch("common.crsf_bridge.open_serial")
        mocker.patch("sys.argv", ["crsf_bridge.py", "--check-config", str(env_file)])
        assert main() == 0
        mock_open_udp.assert_not_called()
        mock_open_serial.assert_not_called()

    def test_missing_required_args_without_check_config_errors(
        self,
        mocker: "MockerFixture",
    ) -> None:
        """Без --check-config обязательны serial/listen/peer — иначе argparse error."""
        mocker.patch("sys.argv", ["crsf_bridge.py"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2  # argparse error exit code
