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
from typing import TYPE_CHECKING

import pytest
from common.crsf_bridge import bytes_to_hex, open_serial, open_udp, parse_addr

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
