# HANDOFF: Беспроводной радиомост У1↔У2 (Orange Pi 5 + CPE710 + WireGuard)

> Документ для переноса проекта в новую среду разработки. Состояние на момент написания: спроектирована архитектура, написан код для прозрачного мостирования UART/RS485 и видео через CPE710 + WireGuard, монтаж и полевые испытания не проводились.

---

## 1. Цель проекта

Беспроводная замена существующего 8-жильного кабеля между двумя устройствами FPV-наземки: **У1** (мастер-пульт оператора, работает с пультом П1 RadioMaster TX12 и видео-передатчиком MECH/VTX для очков) и **У2** (выносная база, содержит 2× ELRS-передатчика для управления дроном и VRX для приёма аналогового видео 5.8 ГГц). Между У1 и У2 сейчас проложен 8-жильный кабель, по которому идут: 2× RS485-канал (CRSF для управления дроном + CTRL для переключения каналов VRX с У1), 1× composite video от VRX к MECH, 1× пара питания 12V/GND. Дистанция до 1 км, оборудование работает в полевых условиях.

Цель — заменить кабель на пару Orange Pi 5, соединённых через готовый Wi-Fi мост TP-Link CPE710 (есть в наличии), так чтобы для У1 и У2 это было прозрачно: те же сигналы поступают на те же контакты их 8-pin разъёмов, оригинальный кабель остаётся как резервный. Приоритеты по важности (со слов пользователя): надёжность канала > низкая латенция видео > дальность > простота сборки и цена.

---

## 2. Стек

**Языки и среда исполнения:**
- Python 3.12 (Ubuntu 24.04 LTS на Orange Pi 5)
- Bash для скриптов запуска и инсталляции
- systemd для управления сервисами

**Python-библиотеки:**
- `pyserial` ≥ 3.5 (пакет `python3-serial`) — для работы с USB-RS485/UART
- стандартная библиотека (`socket`, `select`, `signal`, `argparse`, `logging`) — для UDP-моста

**Системные компоненты:**
- GStreamer 1.22+ с плагинами: `gstreamer1.0-tools`, `gstreamer1.0-plugins-good`, `gstreamer1.0-plugins-bad`, `gstreamer1.0-plugins-ugly`, `gstreamer1.0-libav`, `gstreamer1.0-rockchip1` — последний даёт `mpph264enc`/`mppvideodec` (аппаратный H.264 кодек через RKMPP на RK3588)
- WireGuard ≥ 1.0 (`wireguard`, `wireguard-tools`) — VPN-туннель поверх локальной сети CPE710
- `v4l-utils` — диагностика USB-видеограбберов

**Hardware:**
- 2× Orange Pi 5 (RK3588S, 4–8 GB RAM, NVMe SSD)
- 2× TP-Link CPE710 (5 ГГц 802.11ac PtP-мост, ~3–7 мс one-way)
- 4× Waveshare USB-TO-RS485 (B) на чипах CH343G + SP485EEN (заказаны, не пришли)
- 2× USB видеограбберы (у пользователя уже есть, тип не подтверждён — предполагаются на MS2130 или подобных UVC-чипах)
- 2× БП USB-C 5V 4A для Orange Pi
- 8-pin разъёмы (модель **не определена**, нужно фото от пользователя)

---

## 3. Архитектурные решения

**Структура папок проекта:**
```
u1u2-bridge/
├── README.md                   # документация
├── install.sh                  # инсталлятор для обеих сторон (u1|u2)
├── common/
│   ├── crsf_bridge.py          # UART↔UDP мост (общий для всех инстансов)
│   └── crsf-bridge@.service    # шаблонный systemd-юнит
├── u2/                         # выносная база
│   ├── video_tx.sh             # GStreamer pipeline VRX → H.264 RTP
│   └── systemd/
│       └── video-tx.service
└── u1/                         # мастер-пульт
    ├── video_rx.sh             # GStreamer pipeline H.264 RTP → HDMI
    └── systemd/
        └── video-rx.service
```

Обоснование: разделение на `common/u1/u2` позволяет одному репозиторию обслуживать обе стороны, выбор роли через аргумент `install.sh u1|u2`. Один и тот же `crsf_bridge.py` запускается на обеих сторонах с разными env-параметрами.

**Ключевые архитектурные выборы:**

1. **Не используем WFB-NG, остаёмся на обычном IP.** В первой итерации проекта рассматривался WFB-NG (raw 802.11 injection с FEC), но после уточнения, что у пользователя есть готовый CPE710, WFB-NG стал избыточен — CPE710 уже даёт ~3–7 мс one-way и встроенное шифрование. Стек упростился до UDP поверх Ethernet.

2. **WireGuard поверх CPE710.** Дополнительный VPN-туннель `10.10.0.0/24` поверх локальной сети `192.168.1.0/24` через CPE710. Даёт второй слой шифрования и стабильные имена пиров независимо от транспортного слоя (можно будет переключить на 4G/Starlink в будущем без переписывания скриптов). Overhead — 1–3 мс латенции, незначительный.

3. **Прозрачный байтовый мост UART↔UDP вместо парсинга CRSF.** `crsf_bridge.py` не пытается понимать CRSF-пакеты — он просто гонит байты в обе стороны. Это работает с любым UART-протоколом на нужной скорости: CRSF (420k), служебный CTRL-канал переключения VRX (точная скорость неизвестна), любые другие. Один скрипт — все каналы.

4. **Один UDP-порт на канал, peer-to-peer.** Каждый CRSF/CTRL-канал использует один UDP-порт двусторонне: обе стороны слушают на этом порту и шлют партнёру на тот же порт. Это упрощает конфигурацию (не надо разделять командный/телеметрийный поток) и работает потому, что RS485 у пользователя half-duplex — в каждый момент времени байты идут только в одну сторону.

5. **GStreamer RKMPP для видео вместо v4l2.** Используем `mpph264enc` (encode на У2) и `mppvideodec` (decode на У1) через `gstreamer1.0-rockchip1` — это аппаратный H.264 на VPU RK3588, латенция кодирования 8–12 мс против 15–20 мс у v4l2h264enc. Профиль `baseline` (нет B-кадров), GOP=15 для быстрого recovery после потерь.

6. **kmssink для вывода видео, отключённый display-manager.** Видео на У1 выводится через `kmssink` напрямую в DRM/KMS — минует X/Wayland-композитор, режет ~10–15 мс латенции. Требует, чтобы система загружалась в `multi-user.target` без графической оболочки. Инсталлятор это делает.

7. **systemd с `Restart=always` для всех критичных сервисов.** Любой сервис при падении перезапускается через 2–3 секунды. CRSF-сервисам выставлен realtime IO-приоритет (`IOSchedulingClass=realtime`) и `Nice=-10`, потому что CRSF чувствителен к джиттеру.

8. **udev-правила для стабильных имён UART.** USB↔RS485 адаптеры получают symlinks `/dev/ttyUSB-CRSF1`, `/dev/ttyUSB-CRSF2` через udev (по серийному номеру чипа) — иначе после ребута `/dev/ttyUSB0` и `ttyUSB1` могут поменяться местами и сервисы попадут на чужой адаптер.

---

## 4. Файлы проекта

### 4.1. `u1u2-bridge/README.md`

**Назначение:** документация проекта — архитектура, BOM, бюджет латенции, инструкции по настройке CPE710 и установке.

```markdown
# У1 ↔ У2 IP-мост через TP-Link CPE710 + Orange Pi 5

Передача 2× CRSF (ELRS) и аналогового видео между выносной базой и пультом FPV-оператора через готовый Wi-Fi PtP-мост TP-Link CPE710. Стек упрощён до обычного UDP поверх Ethernet — никаких ВFB-NG, monitor mode, ключей и diversity, всё это уже делает CPE710.

## Hardware (что вы используете)

| Узел | Компонент | Назначение |
|------|-----------|------|
| У2 | Orange Pi 5 (RK3588S) + 256 GB NVMe | SBC выносной базы, аппаратный H.264 encode через RKMPP |
| У2 | USB видеограббер MS2130 (CVBS) | оцифровка composite с VRX |
| У2 | 2× USB↔UART CP2102N | CRSF к двум ELRS-модулям |
| У2 | TP-Link CPE710 (master/AP) | 5 ГГц 802.11ac PtP-линк |
| У1 | Orange Pi 5 (RK3588S) | SBC оператора, H.264 decode + HDMI out |
| У1 | 2× USB↔UART CP2102N | CRSF в П1 trainer и во 2-й TX-модуль |
| У1 | TP-Link CPE710 (slave/Client) | приёмная сторона PtP |
| опционально | HDMI→CVBS конвертер | если очки только аналоговые (см. ниже) |

## Бюджет латенции

| Звено | мс |
|---|---:|
| дрон → VRX (5.8 ГГц аналог) | 0 |
| VRX → MS2130 → /dev/video0 | 30–40 |
| GStreamer mpph264enc (RKMPP) baseline | 8–12 |
| UDP в LAN | <1 |
| CPE710 air (one-way, 20 МГц BW) | 3–7 |
| LAN на приёмной стороне | <1 |
| GStreamer mpph264dec (RKMPP) | 5–8 |
| HDMI вывод Orange Pi 5 → очки | 5–15 |
| (вариант) HDMI→CVBS конвертер → MECH | +15–20 |
| **Итого glass-to-glass** | **52–82** (HDMI очки) или **67–102** (composite через MECH) |

## Сетевая модель

```
                       192.168.1.0/24 (один bridge через CPE710)
        У2 сторона                                            У1 сторона
  ┌──────────────────────┐                          ┌──────────────────────┐
  │ Orange Pi 5         │  Eth                Eth   │ Orange Pi 5         │
  │ 192.168.1.10        ├────[CPE710 master]≈≈≈≈≈≈≈[CPE710 slave]────────┤ 192.168.1.20  │
  │                     │     192.168.1.2  ↑↓ ~5 мс    192.168.1.3       │              │
  │ /dev/video0  (VRX)  │                                                │ HDMI → очки  │
  │ /dev/ttyUSB0,1      │                                                │ /dev/ttyUSB0,1│
  └──────────────────────┘                          └──────────────────────┘

UDP-порты:
  5600   видео H.264 RTP        У2 → У1
  14550  CRSF1 commands+telem   bidir (У1↔У2 на UART /dev/ttyUSB0)
  14551  CRSF2 commands+telem   bidir (на UART /dev/ttyUSB1)
```

Каждый CRSF-канал — один UDP-порт двунаправленно: оба `crsf_bridge.py` (на У1 и на У2) слушают этот порт и шлют в этот же порт партнёру. Видео — однонаправленно с У2 на У1.

## Настройка CPE710 (важные нюансы для FPV)

В Pharos UI (**192.168.0.254** по умолчанию):

1. **Operation Mode** — `Bridge`. Устанавливаем PtP: один CPE как `Access Point`, второй как `Client` с фиксированным MAC партнёра.
2. **Wireless → Channel Width = 20 MHz**. Не 40, не 80. Чем уже канал — тем устойчивее в движении и меньше джиттер.
3. **Fixed channel** в неперекрывающейся U-NII зоне без DFS — например **149**. Не используйте `Auto`.
4. **MAXtream TDMA = Disable**. При одном клиенте TDMA не нужен, обычный CSMA быстрее.
5. **Distance setting** в Advanced — выставить реальную дистанцию (например 1 km).
6. **TX Power** — снизить до 17–20 dBm для дистанции 1 км. Полная мощность 27 dBm на близких расстояниях даёт desensitization приёмника.
7. **DHCP** — отключить, выдать обоим CPE статические адреса (192.168.1.2, 192.168.1.3), Orange Pi тоже статика (192.168.1.10, 192.168.1.20).

## Установка софта на Orange Pi 5

ОС — рекомендую **Ubuntu 24.04 от Joshua Riek** (`joshua-riek/ubuntu-rockchip`).

Проверка наличия RKMPP-плагинов:
```bash
gst-inspect-1.0 | grep mpp
# должно быть: mpph264enc, mppjpegenc, mppvideodec, ...
```

Установка стека:
```bash
git clone <ваш репо> /opt/u1u2-bridge
cd /opt/u1u2-bridge
sudo ./install.sh u2   # на выносной базе
sudo ./install.sh u1   # на мастер-пульте
```

## Failsafe и надёжность

- ELRS на дроне сам уходит в failsafe через ~100 мс без CRSF.
- `systemd` все юниты с `Restart=always`, `RestartSec=2`.
- Hardware watchdog RK3588 (`rockchip-wdt`) с таймаутом 15 с.
- Мониторинг линка: `ping -i 0.2 192.168.1.20` в фоне с алертом в OSD при потерях >5%.
```

---

### 4.2. `u1u2-bridge/install.sh`

**Назначение:** инсталлятор для обеих сторон — ставит зависимости, копирует конфиги, регистрирует systemd-юниты, настраивает сеть и udev.

```bash
#!/bin/bash
# install.sh — стартовый скрипт установки на У1 или У2.
# Использование:  sudo ./install.sh u1      # на мастер-пульте
#                 sudo ./install.sh u2      # на выносной базе
#
# Предполагает Orange Pi 5 с Ubuntu 24.04 от joshua-riek/ubuntu-rockchip
# (или Armbian с rockchip-mpp). Сетевая конфигурация:
#   У2 Orange Pi:    192.168.1.10
#   У1 Orange Pi:    192.168.1.20
#   CPE710 master:   192.168.1.2
#   CPE710 slave:    192.168.1.3

set -euo pipefail

ROLE="${1:-}"
if [[ "$ROLE" != "u1" && "$ROLE" != "u2" ]]; then
  echo "Usage: $0 {u1|u2}" >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

REPO="$(cd "$(dirname "$0")" && pwd)"
echo "==> repo: $REPO  role: $ROLE"

# --- 1. зависимости -----------------------------------------------------------
apt update
apt install -y \
  python3 python3-serial \
  gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly gstreamer1.0-libav \
  gstreamer1.0-rockchip1 \
  v4l-utils \
  curl git

# --- 2. проверка RKMPP --------------------------------------------------------
if ! gst-inspect-1.0 mpph264enc &>/dev/null; then
  echo "!! mpph264enc не найден — проверьте что установлен gstreamer1.0-rockchip1"
  echo "!! и что вы на образе с поддержкой Rockchip MPP (joshua-riek или Armbian)"
  exit 1
fi
echo "==> RKMPP encoder available"

# --- 3. сеть: статический IP --------------------------------------------------
if [[ "$ROLE" == "u2" ]]; then
  IP_ADDR="192.168.1.10/24"
  PEER_IP="192.168.1.20"
else
  IP_ADDR="192.168.1.20/24"
  PEER_IP="192.168.1.10"
fi

NETPLAN_FILE=/etc/netplan/99-u1u2-bridge.yaml
cat > "$NETPLAN_FILE" <<EOF
network:
  version: 2
  ethernets:
    end0:
      addresses: [$IP_ADDR]
      dhcp4: false
      dhcp6: false
EOF
chmod 0600 "$NETPLAN_FILE"
netplan apply || true
echo "==> static IP set: $IP_ADDR (peer will be $PEER_IP)"

# --- 4. код проекта -----------------------------------------------------------
install -d /etc/u1u2-bridge
install -d /opt/u1u2-bridge/common /opt/u1u2-bridge/$ROLE
install -m 0755 "$REPO/common/crsf_bridge.py" /opt/u1u2-bridge/common/
install -m 0755 "$REPO/$ROLE"/*.sh /opt/u1u2-bridge/$ROLE/

# --- 5. systemd-юниты ---------------------------------------------------------
install -m 0644 "$REPO/common/crsf-bridge@.service" /etc/systemd/system/
install -m 0644 "$REPO/$ROLE/systemd/"*.service /etc/systemd/system/

# --- 6. env-файлы для CRSF-моста ----------------------------------------------
if [[ "$ROLE" == "u2" ]]; then
  cat > /etc/u1u2-bridge/crsf-tx1.env <<EOF
SERIAL_DEV=/dev/ttyUSB-CRSF1
BAUD=420000
LISTEN=0.0.0.0:14550
PEER=192.168.1.20:14550
EOF
  cat > /etc/u1u2-bridge/crsf-tx2.env <<EOF
SERIAL_DEV=/dev/ttyUSB-CRSF2
BAUD=420000
LISTEN=0.0.0.0:14551
PEER=192.168.1.20:14551
EOF
else
  cat > /etc/u1u2-bridge/crsf-tx1.env <<EOF
SERIAL_DEV=/dev/ttyUSB-CRSF1
BAUD=420000
LISTEN=0.0.0.0:14550
PEER=192.168.1.10:14550
EOF
  cat > /etc/u1u2-bridge/crsf-tx2.env <<EOF
SERIAL_DEV=/dev/ttyUSB-CRSF2
BAUD=420000
LISTEN=0.0.0.0:14551
PEER=192.168.1.10:14551
EOF
fi

# --- 7. udev-правила: стабильные имена UART -----------------------------------
cat > /etc/udev/rules.d/90-u1u2-uart.rules <<'EOF'
# CP2102N USB↔UART → стабильные имена /dev/ttyUSB-CRSF1, ttyUSB-CRSF2
# Замените серийники на свои:
#   udevadm info -a /dev/ttyUSB0 | grep -m1 'ATTRS{serial}'
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", \
  ATTRS{serial}=="REPLACE_WITH_SERIAL_1", SYMLINK+="ttyUSB-CRSF1"
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", \
  ATTRS{serial}=="REPLACE_WITH_SERIAL_2", SYMLINK+="ttyUSB-CRSF2"
EOF
udevadm control --reload || true

echo
echo "!! ВАЖНО: отредактируйте /etc/udev/rules.d/90-u1u2-uart.rules,"
echo "   подставьте серийники ваших CP2102N (см. udevadm info)"
echo "   После: sudo udevadm trigger"

# --- 8. отключаем display-manager на У1 (kmssink требует tty) -----------------
if [[ "$ROLE" == "u1" ]]; then
  systemctl set-default multi-user.target
  systemctl disable --now gdm3 lightdm sddm 2>/dev/null || true
fi

# --- 9. ядро: повышаем приоритет UDP-обработки --------------------------------
cat > /etc/sysctl.d/99-u1u2-bridge.conf <<'EOF'
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.core.netdev_max_backlog=5000
EOF
sysctl --system >/dev/null

# --- 10. запуск ---------------------------------------------------------------
systemctl daemon-reload
systemctl enable --now crsf-bridge@tx1.service
systemctl enable --now crsf-bridge@tx2.service
if [[ "$ROLE" == "u2" ]]; then
  systemctl enable --now video-tx.service
else
  systemctl enable --now video-rx.service
fi

echo
echo "=========================================================================="
echo " Готово. Проверка:"
echo "   ping -i 0.2 $PEER_IP                    # связь по CPE710"
echo "   systemctl status crsf-bridge@tx1 crsf-bridge@tx2"
echo "   journalctl -u video-${ROLE/u1/rx}${ROLE/u2/tx} -f --since '1 min ago'"
echo "=========================================================================="
```

> **Примечание о неактуальности udev-правил:** в текущей версии файла прописаны ID для CP2102N (10c4:ea60). После того как пользователь выбрал Waveshare USB-TO-RS485 (B) на чипе **CH343G** (1a86:55d3 или похожий — нужно уточнить через `lsusb` после получения адаптеров), эти ID нужно заменить. Файл сделать это пока не успел.

---

### 4.3. `u1u2-bridge/common/crsf_bridge.py`

**Назначение:** прозрачный байтовый мост UART/RS485 ↔ UDP, двусторонний peer-to-peer. Запускается systemd-инстансом с env-параметрами.

```python
#!/usr/bin/env python3
"""
CRSF UART <-> UDP bridge для IP-сети поверх TP-Link CPE710.

Прозрачно прокидывает байты между serial-портом и UDP-сокетом.
CRSF — пакетный протокол на 420 000 бод, кадры до 64 байт, 250–500 Hz.

Один скрипт работает в двунаправленном peer-to-peer режиме:
  - читает UART, шлёт UDP на peer (тот же порт у партнёра)
  - слушает UDP на listen-port, пишет всё в UART

Пример (на У2, мост к ELRS-модулю №1):
    crsf_bridge.py --serial /dev/ttyUSB-CRSF1 \\
                   --listen 0.0.0.0:14550 \\
                   --peer 192.168.1.20:14550

Пример (на У1, мост к П1 trainer-port):
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

import serial


CRSF_DEFAULT_BAUD = 420_000
CRSF_MAX_FRAME = 64
SELECT_TIMEOUT = 0.005     # 5 мс


def parse_addr(s: str) -> tuple[str, int]:
    host, port = s.rsplit(":", 1)
    return host, int(port)


def open_serial(dev: str, baud: int) -> serial.Serial:
    ser = serial.Serial(
        dev,
        baudrate=baud,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=0,            # неблокирующее чтение
        write_timeout=0.05,
        rtscts=False,
        dsrdtr=False,
    )
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def open_udp(listen: tuple[str, int]) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # увеличиваем буферы — критично при джиттере 5–10 мс на Wi-Fi мосте
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
    sock.bind(listen)
    sock.setblocking(False)
    return sock


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--serial", required=True, help="например /dev/ttyUSB-CRSF1")
    p.add_argument("--baud", type=int, default=CRSF_DEFAULT_BAUD)
    p.add_argument("--listen", required=True,
                   help="ip:port для приёма от партнёра (обычно 0.0.0.0:14550)")
    p.add_argument("--peer", required=True,
                   help="ip:port партнёра, куда отправлять с UART")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("crsf-bridge")

    listen = parse_addr(args.listen)
    peer = parse_addr(args.peer)
    log.info("serial=%s baud=%d listen=%s:%d peer=%s:%d",
             args.serial, args.baud, *listen, *peer)

    sock = open_udp(listen)

    stop = {"flag": False}
    def on_sig(*_): stop["flag"] = True
    signal.signal(signal.SIGTERM, on_sig)
    signal.signal(signal.SIGINT, on_sig)

    s2u_bytes = u2s_bytes = 0
    last_stat = time.monotonic()
    STAT_PERIOD = 10.0

    ser = None
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
            r, _, _ = select.select([ser.fileno(), sock.fileno()], [], [],
                                    SELECT_TIMEOUT)
        except (InterruptedError, OSError):
            continue

        if ser.fileno() in r:
            try:
                data = ser.read(CRSF_MAX_FRAME * 4)
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
                except (serial.SerialTimeoutException, serial.SerialException,
                        OSError) as e:
                    log.warning("uart write failed: %s", e)

        now = time.monotonic()
        if now - last_stat >= STAT_PERIOD:
            log.info("uart->udp=%d B/s  udp->uart=%d B/s",
                     int(s2u_bytes / STAT_PERIOD),
                     int(u2s_bytes / STAT_PERIOD))
            s2u_bytes = u2s_bytes = 0
            last_stat = now

    log.info("shutting down")
    if ser:
        ser.close()
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> **Важно для перехода:** скрипт написан под предположение «адаптер USB↔UART», но он будет работать **без изменений** с USB↔RS485 адаптерами (Waveshare CH343G+SP485EEN). С точки зрения Linux это всё тот же `/dev/ttyUSBx`, а auto-direction control на адаптере сам управляет half-duplex переключением. **Это пока не проверено на железе** — будет тест после получения адаптеров. Если auto-direction не сработает на 420k бод — нужно будет добавить ручное управление через RTS+`ioctl(TIOCSRS485)`.

---

### 4.4. `u1u2-bridge/common/crsf-bridge@.service`

**Назначение:** шаблонный systemd-юнит, по одному инстансу на каждый CRSF-канал (`crsf-bridge@tx1.service`, `crsf-bridge@tx2.service`).

```ini
# /etc/systemd/system/crsf-bridge@.service
#
# Шаблонный юнит. Параметризуется через имя инстанса:
#   systemctl enable --now crsf-bridge@tx1.service
#   systemctl enable --now crsf-bridge@tx2.service
#
# Конфиг для каждого инстанса лежит в /etc/u1u2-bridge/crsf-<имя>.env

[Unit]
Description=CRSF UART<->UDP bridge (%i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/u1u2-bridge/crsf-%i.env
ExecStart=/usr/bin/python3 /opt/u1u2-bridge/common/crsf_bridge.py \
  --serial $SERIAL_DEV \
  --baud $BAUD \
  --listen $LISTEN \
  --peer $PEER
Restart=always
RestartSec=2
# realtime-приоритет — CRSF чувствителен к джиттеру
Nice=-10
IOSchedulingClass=realtime
IOSchedulingPriority=4

[Install]
WantedBy=multi-user.target
```

---

### 4.5. `u1u2-bridge/u2/video_tx.sh`

**Назначение:** GStreamer pipeline на У2 — оцифровка composite с VRX через MS2130, кодирование в H.264 на RKMPP, отправка по UDP-RTP.

```bash
#!/bin/bash
# /opt/u1u2-bridge/u2/video_tx.sh
#
# На У2 (Orange Pi 5):
#   composite VRX → MS2130 (USB UVC) → RKMPP H.264 encoder → RTP → UDP к У1
#
# Параметры подобраны под приоритет «низкая латенция»:
#   - profile=baseline, нет B-кадров
#   - GOP=15 кадров (быстрый recovery после потерь)
#   - bitrate 2500 kbps — с запасом для CPE710 PHY 80+ Mbps
#
# MS2130 умеет MJPEG на грабере — это снижает USB-нагрузку до ~10 МБ/с
# и убирает лишний YUY2-конверт перед энкодером.

set -euo pipefail

DEV="${VIDEO_DEV:-/dev/video0}"
WIDTH="${VIDEO_W:-720}"
HEIGHT="${VIDEO_H:-576}"      # 576 для PAL, 480 для NTSC
FPS="${VIDEO_FPS:-25}"         # 25 для PAL, 30 для NTSC
BITRATE="${VIDEO_BITRATE:-2500000}"
PEER_HOST="${PEER_HOST:-192.168.1.20}"
PEER_PORT="${PEER_PORT:-5600}"

exec gst-launch-1.0 -v \
  v4l2src device="$DEV" io-mode=4 ! \
  image/jpeg,width=$WIDTH,height=$HEIGHT,framerate=$FPS/1 ! \
  jpegdec ! \
  videoconvert ! \
  video/x-raw,format=NV12 ! \
  mpph264enc \
    rc-mode=cbr \
    bps=$BITRATE \
    bps-max=$((BITRATE * 12 / 10)) \
    gop=15 \
    profile=66 \
    level=40 \
    header-mode=1 ! \
  video/x-h264,profile=baseline ! \
  h264parse config-interval=1 ! \
  rtph264pay pt=96 mtu=1400 config-interval=1 ! \
  udpsink host="$PEER_HOST" port="$PEER_PORT" sync=false async=false
```

---

### 4.6. `u1u2-bridge/u1/video_rx.sh`

**Назначение:** GStreamer pipeline на У1 — приём UDP-RTP H.264, декодирование на RKMPP, вывод на HDMI через kmssink.

```bash
#!/bin/bash
# /opt/u1u2-bridge/u1/video_rx.sh
#
# На У1 (Orange Pi 5):
#   UDP RTP H.264 → RKMPP decode → fullscreen HDMI вывод через kmssink
#
# kmssink выводит напрямую в DRM/KMS, минуя композитор — самая короткая
# цепочка для HDMI на Orange Pi 5.
#
# Если очки аналоговые: ставим HDMI→CVBS конвертер (CX2262 и подобные)
# между HDMI Orange Pi и входом MECH/VTX. В скрипте ничего не меняется.

set -euo pipefail

LISTEN_PORT="${LISTEN_PORT:-5600}"

# Перед запуском убедитесь что Orange Pi загрузился без X/wayland-композитора:
#   sudo systemctl set-default multi-user.target
# kmssink не уживается с Xorg/wayland, ему нужен прямой доступ к DRM.

exec gst-launch-1.0 -v \
  udpsrc port="$LISTEN_PORT" \
    caps="application/x-rtp,encoding-name=H264,payload=96,clock-rate=90000" \
    buffer-size=2097152 ! \
  rtpjitterbuffer latency=15 drop-on-latency=true do-lost=true ! \
  rtph264depay ! \
  h264parse ! \
  mppvideodec ! \
  videoconvert ! \
  kmssink sync=false force-modesetting=true can-scale=true
```

---

### 4.7. `u1u2-bridge/u2/systemd/video-tx.service`

**Назначение:** systemd-юнит для запуска `video_tx.sh` на У2.

```ini
# /etc/systemd/system/video-tx.service (на У2)

[Unit]
Description=Video TX (VRX -> H.264 RTP -> CPE710)
After=network-online.target dev-video0.device
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/u1u2-bridge/u2/video_tx.sh
Restart=always
RestartSec=3
Nice=-5

[Install]
WantedBy=multi-user.target
```

---

### 4.8. `u1u2-bridge/u1/systemd/video-rx.service`

**Назначение:** systemd-юнит для запуска `video_rx.sh` на У1.

```ini
# /etc/systemd/system/video-rx.service (на У1)

[Unit]
Description=Video RX (H.264 RTP -> HDMI)
After=network-online.target
Wants=network-online.target
Conflicts=display-manager.service

[Service]
Type=simple
ExecStart=/opt/u1u2-bridge/u1/video_rx.sh
Restart=always
RestartSec=3
Nice=-5
# kmssink требует владения DRM-устройством
Environment=GST_DEBUG=2

[Install]
WantedBy=multi-user.target
```

---

### 4.9. `steps/STEP-3-orange-pi-setup.md`

**Назначение:** пошаговая инструкция для пользователя — установка ОС на Orange Pi 5, настройка статической сети, CPE710 и WireGuard-туннеля. **Этот файл — единственное место, где описана WireGuard-конфигурация** (в коде её нет, только инструкции).

```markdown
# Этап 3. Настройка Orange Pi 5 + WireGuard

Цель — получить **две Orange Pi**, соединённые через TP-Link CPE710, с настроенным WireGuard-туннелем поверх. После этого этапа должен работать `ping 10.10.0.1` с одной Pi на другую через VPN.

## 3.1. Установка ОС на Orange Pi 5

Скачайте **Ubuntu 24.04 Server от Joshua Riek**: https://github.com/Joshua-Riek/ubuntu-rockchip/releases

Файл: `ubuntu-24.04-preinstalled-server-arm64-orangepi-5.img.xz`

Прошейте на SD-карту 32GB+ через Balena Etcher.

После первого входа:
```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

## 3.2. Базовая настройка

На У2:
```bash
sudo hostnamectl set-hostname u2-bridge
```

На У1:
```bash
sudo hostnamectl set-hostname u1-bridge
```

На обеих:
```bash
sudo apt install -y \
  vim htop tmux net-tools curl git \
  python3-pip python3-serial \
  iperf3 mtr tcpdump iw \
  wireguard wireguard-tools
sudo systemctl enable --now ssh
```

## 3.3. Настройка статической сети

### CPE710 настройки (через web 192.168.0.254):
- Operation Mode: Bridge
- Один CPE — AP, второй — Client (с привязкой MAC)
- Channel Width: 20 MHz
- Channel: 149 (фиксированный, без DFS)
- TX Power: 17–20 dBm
- MAXtream TDMA: Disable
- Distance: 1 km
- LAN IP: 192.168.1.2 (master) и 192.168.1.3 (slave)
- DHCP: Disable

### На Orange Pi (статические IP):

У2 (`192.168.1.10`):
```bash
sudo tee /etc/netplan/99-bridge.yaml <<'EOF'
network:
  version: 2
  ethernets:
    end0:
      addresses: [192.168.1.10/24]
      dhcp4: false
      dhcp6: false
      nameservers:
        addresses: [1.1.1.1]
EOF
sudo chmod 600 /etc/netplan/99-bridge.yaml
sudo netplan apply
```

У1 (`192.168.1.20`): то же самое с `192.168.1.20/24`.

Проверка:
```bash
ping -c 5 192.168.1.20         # должно быть <10 мс, 0% потерь
iperf3 -s                      # на одной стороне
iperf3 -c 192.168.1.20 -t 30   # на другой, ожидаем 30+ Mbps
```

## 3.4. WireGuard

На каждой Pi:
```bash
cd /etc/wireguard
sudo umask 077
sudo wg genkey | sudo tee privatekey | sudo wg pubkey | sudo tee publickey
sudo chmod 600 privatekey
sudo cat privatekey; sudo cat publickey
```

### Конфиг на У2 (10.10.0.1):
```bash
sudo tee /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = 10.10.0.1/24
PrivateKey = <U2_PRIVATE_KEY>
ListenPort = 51820

[Peer]
PublicKey = <U1_PUBLIC_KEY>
AllowedIPs = 10.10.0.2/32
EOF
sudo chmod 600 /etc/wireguard/wg0.conf
```

### Конфиг на У1 (10.10.0.2):
```bash
sudo tee /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = 10.10.0.2/24
PrivateKey = <U1_PRIVATE_KEY>

[Peer]
PublicKey = <U2_PUBLIC_KEY>
Endpoint = 192.168.1.10:51820
AllowedIPs = 10.10.0.1/32
PersistentKeepalive = 15
EOF
sudo chmod 600 /etc/wireguard/wg0.conf
```

### Запуск:
```bash
sudo wg-quick up wg0
sudo systemctl enable wg-quick@wg0
```

### Проверка:
```bash
ping -c 5 10.10.0.1        # с У1
sudo wg show               # должен быть handshake
```

## 3.5. Финальные проверки

| Тест | Команда | Ожидание |
|---|---|---|
| Локальный пинг | `ping 192.168.1.20` | <10 мс, 0% потерь |
| Туннельный пинг | `ping 10.10.0.2` | <12 мс, 0% потерь |
| Пропускная | `iperf3` через туннель | 25+ Мбит/с |
```

---

## 5. Внешние зависимости

### 5.1. Python-пакеты (через apt, не pip)

| Пакет | Версия | Назначение |
|---|---|---|
| `python3` | 3.12+ (поставляется с Ubuntu 24.04) | runtime |
| `python3-serial` | 3.5+ | `import serial` для UART/RS485 |

> Решено НЕ использовать pip/venv — все зависимости через apt. Это упрощает образ и убирает один потенциальный источник проблем при запуске через systemd. Если в новой среде используется poetry/uv — нужно будет добавить `pyserial` в `pyproject.toml`.

### 5.2. Системные пакеты

| Пакет | Назначение |
|---|---|
| `gstreamer1.0-tools` | `gst-launch-1.0`, `gst-inspect-1.0` |
| `gstreamer1.0-plugins-good` | базовые элементы (udpsink, rtph264pay) |
| `gstreamer1.0-plugins-bad` | h264parse, kmssink |
| `gstreamer1.0-plugins-ugly` | – резерв, не обязательно |
| `gstreamer1.0-libav` | резервный софтовый кодек |
| `gstreamer1.0-rockchip1` | **критично** — `mpph264enc`, `mppvideodec` (RKMPP) |
| `v4l-utils` | диагностика USB-видеограбберов |
| `wireguard`, `wireguard-tools` | VPN |
| `iperf3`, `mtr`, `tcpdump`, `iw` | диагностика сети |

### 5.3. Переменные окружения

Все env передаются через systemd `EnvironmentFile`. Файлы создаются `install.sh` в `/etc/u1u2-bridge/`:

**`crsf-tx1.env` (CRSF канал 1):**
```
SERIAL_DEV=/dev/ttyUSB-CRSF1
BAUD=420000
LISTEN=0.0.0.0:14550
PEER=<peer_ip>:14550
```

**`crsf-tx2.env` (CRSF канал 2 — или CTRL канал, зависит от назначения):**
```
SERIAL_DEV=/dev/ttyUSB-CRSF2
BAUD=420000
LISTEN=0.0.0.0:14551
PEER=<peer_ip>:14551
```

`peer_ip` = `192.168.1.10` (на У1, ссылается на У2) или `192.168.1.20` (на У2, ссылается на У1). В перспективе должно поменяться на `10.10.0.1`/`10.10.0.2` после поднятия WireGuard.

**Опциональные env для видео (используются в `video_tx.sh`):**
```
VIDEO_DEV=/dev/video0    # USB-видеограббер
VIDEO_W=720              # 720 для PAL, 720 для NTSC
VIDEO_H=576              # 576 PAL, 480 NTSC
VIDEO_FPS=25             # 25 PAL, 30 NTSC
VIDEO_BITRATE=2500000    # бит/с
PEER_HOST=192.168.1.20
PEER_PORT=5600
```

### 5.4. Hardware-зависимости

- ОС: Ubuntu 24.04 от Joshua Riek (`joshua-riek/ubuntu-rockchip`) — критично для `gstreamer1.0-rockchip1`. Армбиан Bookworm/Jammy с rockchip-mpp тоже должен подойти, но не проверено.
- Чип RK3588(S) — без него `mpph264enc`/`mppvideodec` не работают, и весь видео-стек ломается.
- Сетевой интерфейс на Orange Pi 5 (joshua-riek 24.04) — `end0`. На Orange Pi 5 **Max** — `enP3p49s0` (плата имеет **один** 2.5GbE, не два — путали с Pi 5 Plus). Если в новой среде имя другое — `install.sh` определяет интерфейс автоматически (первый не-`lo` интерфейс в состоянии UP); переопределение через `IFACE=... sudo ./install.sh ...`.

---

## 6. Текущее состояние

### Сессия 2026-05-18 (свежий статус железа)

- **u2-pi (Orange Pi 5 Max):** залит joshua-riek 24.04, SPI прошит U-Boot'ом, NVMe-загрузка работает. Hostname `u2-pi`. Пользователь `ubuntu` в группе `dialout`.
- **Сетевой интерфейс u2-pi:** один 2.5GbE, имя `enP3p49s0` (Pi 5 Max имеет **один** Ethernet-порт, не два — путали с Pi 5 Plus). `install.sh` определяет имя автоматически через `ip -br link | awk '$2 == "UP"'`.
- **WireGuard:** u2-pi подключён клиентом к wg-easy на VPS `95.140.147.108`, адрес в туннеле `10.8.0.7/24`. Дефолтный конфиг от wg-easy потребовал ручной правки: `AllowedIPs = 10.8.0.0/24` (не `0.0.0.0/0`), `PersistentKeepalive = 15` (не `0`). См. урок 2026-05-18 в `CLAUDE.md`.
- **Репозиторий:** `https://github.com/Revulf0550/u1u2-bridge` (public). На Pi склонирован в `~/u1u2-bridge`.
- **RS485-адаптер:** один Waveshare USB-TO-RS485 (B) подключён к u2-pi. Серийник `5A98051690`, vendor:product `1a86:55d3` (CH343G), драйвер `cdc_acm`, имя устройства **`/dev/ttyACM0`** (не `/dev/ttyUSB0`!). Остальные 5 адаптеров не подключены, серийники неизвестны.
- **Smoke-test `crsf_bridge.py`:** пройден на u2-pi — `--dry-run` отрабатывает, auto-reconnect при отсоединении адаптера работает.
- **u1-pi (ziz):** пока на старой конфигурации, `10.8.0.4`. Переустановка запланирована позже.
- **CPE710:** в bench-фазе не используется — трафик между u1-pi и u2-pi гоняется через WG-туннель к VPS. Локальный CPE710-link будет поднят на полевой фазе.
- **Адаптеры CP2102 и CH340G** (из фото в §3) **в проект не идут**, но могут пригодиться для loopback bench-теста TX↔RX на одной Pi.

### Что работает (код написан и логически готов)

| Компонент | Статус | Замечание |
|---|---|---|
| Архитектура и BOM | ✅ финализированы | Hardware частично получен (см. блок выше) |
| `crsf_bridge.py` | ✅ написан, smoke-test пройден | `--dry-run` и auto-reconnect ОК на u2-pi; реального CRSF-трафика ещё не было |
| `video_tx.sh` + `video_rx.sh` | ✅ написаны, **не тестированы** | Параметры подбирались по даташитам RK3588 |
| `install.sh` | ✅ написан, **не запускался end-to-end** | IFACE автоопределение + PEER_IP_OVERRIDE + SKIP_NETPLAN добавлены |
| Systemd-юниты | ✅ написаны | Готовы к деплою |
| Документация (README, STEP-3) | ✅ готова | |

### Что начато, но не доделано

| Компонент | Что сделано | Что осталось |
|---|---|---|
| Установка ОС на Orange Pi | u2-pi готова | u1-pi: прошить, базовая настройка |
| Настройка CPE710 | Параметры расписаны в STEP-3 | Применить (после bench-фазы по WG) |
| WireGuard-туннель | u2-pi подключён к VPS wg-easy (10.8.0.7) | Подключить u1-pi (после переустановки) |
| Подключение к RS485 | 1 из 6 адаптеров подключён к u2-pi (sn `5A98051690`) | Подключить остальные, узнать серийники, расширить udev rules |
| `crsf_bridge.py` для CTRL канала | Скрипт generic, подходит | Уточнить скорость CTRL канала, создать `crsf-ctrl.env` |

### Что обсуждалось без кода

| Тема | Состояние |
|---|---|
| Переходник 8-pin → клеммы Orange Pi | Решено сделать переходник, не лезть в У1/У2; модель 8-pin разъёма **не определена**, ждём фото от пользователя |
| Тип видеограббера на У2 | У пользователя есть «карты видеозахвата», точная модель **не уточнена**; код предполагает что грабер UVC-совместимый и поддерживает MJPEG |
| Скорость канала RS485_CTRL | **Неизвестна**, нужно узнать у пользователя или измерить осциллографом. Текущий план — попробовать 9600 и 115200 бод |
| Жилы `video_out` на плате У2 | На фото видно **два провода** (белый+жёлтый) припаяны к одному пятаку `video_out`. Не подтверждено — это сигнал+экран или просто параллельная пайка для надёжности. Может оказаться, что один провод — это аудио или что-то ещё |
| Питание Orange Pi | Решено сделать отдельным БП на каждой стороне, не отщипывать от шины 12V У1/У2 |
| Очки FPV | Не входят в проект — У1 сам с ними работает (через MECH или прямой кабель), наша задача — выдать composite в тот же пин 8-pin разъёма У1 |
| Идея «слепо передавать 6 проводов» через Orange Pi | Обсуждалась, отклонена — разные типы сигналов требуют разной оцифровки (UART → USB↔RS485, video → видеограббер) |

### Что выкинули из проекта

| Что | Почему |
|---|---|
| WFB-NG (raw 802.11 с FEC и diversity) | Избыточно при наличии готового CPE710 |
| Monitor mode на Wi-Fi картах, ключи `wifibroadcast.cfg` | Не нужно с CPE710 |
| HDMI→CVBS конвертер на У1 | Не нужно — У1 имеет свой MECH для очков, наша задача только дать composite в разъём |
| Прозвонка 8-pin кабеля мультиметром (STEP-2) | Заменена визуальным осмотром по фото внутренностей У2 |

---

## 7. Известные проблемы / баги

### 7.1. RS485 auto-direction на 420 000 бод — не подтверждено

**Симптом:** Текущий `crsf_bridge.py` ничего не знает про RS485 и просто пишет/читает `/dev/ttyUSBx`. На Waveshare USB-TO-RS485 (B) заявлено аппаратное auto-direction через TX-detect, но **на 420k бод half-duplex это не проверено**.

**Гипотезы причин если не сработает:**
- Auto-direction схема на Waveshare медленная, не успевает переключиться TX→RX между байтами
- SP485EEN требует guard-time, который на 420k нарушает таймин CRSF
- CRSF-фреймы 250–500 Гц могут вызвать коллизии когда обе стороны пытаются передать одновременно

**План если сработает плохо:** добавить ручное управление direction через RTS + `fcntl.ioctl(TIOCSRS485)` с правильным `delay_rts_before_send`/`delay_rts_after_send`. Это меняет `open_serial()` и добавляет несколько строк, но не пересборку архитектуры.

### 7.2. Имя сетевого интерфейса в `install.sh`

**Симптом:** `install.sh` hardcoded использует `end0` в netplan. На некоторых сборках Ubuntu/Armbian для RK3588 интерфейс может называться `eth0`, `enP3p49s0` или похоже.

**Решение:** перед `netplan apply` запустить `ip link show` и заменить `end0` на реальное имя. Лучше — переписать install.sh, чтобы он определял имя автоматически через `ip -br link | awk '$1 != "lo" {print $1; exit}'`.

### 7.3. Waveshare USB-TO-RS485 (B) на CH343G — `/dev/ttyACMx`, не `/dev/ttyUSBx` (ИСПРАВЛЕНО)

**История:** в первоначальной версии `install.sh` udev-правила были прописаны под Silicon Labs CP2102N (`10c4:ea60`, имя `/dev/ttyUSB-CRSFx`). Когда первый Waveshare USB-TO-RS485 (B) подключили к u2-pi (2026-05-18), он определился как USB CDC ACM device:

- **vendor:product** = `1a86:55d3` (WCH CH343G)
- **драйвер** = `cdc_acm` (не `cp210x` и не `ch341`)
- **имя устройства** = `/dev/ttyACM0` (не `/dev/ttyUSB0`)

**Что обновлено в `install.sh` (2026-05-18):**
- udev rule: `SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d3", SYMLINK+="ttyACM-CRSFx"`
- env-файлы: `SERIAL_DEV=/dev/ttyACM-CRSFx`
- серийники передаются через env: `WAVESHARE_SERIAL_1=... WAVESHARE_SERIAL_2=... sudo ./install.sh ...`
- проверка членства `${SUDO_USER}` в `dialout` с подсказкой если нет
- `udevadm trigger` после reload, чтобы symlinks появились без реконнекта

**Известные серийники адаптеров:**
| Адаптер | Серийник | Куда подключён |
|---|---|---|
| #1 | `5A98051690` | u2-pi → CRSF1 (планируется) |
| #2 | — | не подключён |
| #3..#6 | — | не подключены, 4 шт. в резерве |

**Что нужно делать по мере подключения новых адаптеров:**
```bash
udevadm info -a /dev/ttyACM0 | grep -m1 'ATTRS{serial}'
# полученный серийник — передать через WAVESHARE_SERIAL_2 (и т.д.) в install.sh,
# или вручную добавить ещё одну строку в /etc/udev/rules.d/90-u1u2-uart.rules
```

**Урок:** записан в `CLAUDE.md` (2026-05-18 · Waveshare USB-TO-RS485 (B) на CH343G → /dev/ttyACMx).

### 7.4. На фото 1 на пятак `video_out` припаяно два провода

**Симптом:** Не уверены, что белый+жёлтый — это видеосигнал+земля. Может оказаться, что один из них — лишний (дублирование) или несёт другой сигнал (аудио? отдельный канал?).

**Гипотеза:** скорее всего параллельная пайка обоих жил для надёжности (видео по одной паре). Но без подтверждения это создаёт риск перепутать сигналы при сборке переходника.

**Решение:** при сборке переходника проверить мультиметром или осциллографом, что оба провода действительно идут на один пин разъёма (или на два разных).

### 7.5. `kmssink` и графический режим конфликтуют

**Симптом:** `video-rx.service` имеет `Conflicts=display-manager.service`, и `install.sh` отключает GDM/lightdm/sddm. После этого Orange Pi У1 загружается в текстовый режим без рабочего стола.

**Гипотеза проблем:** Если кто-то решит отлаживать с подключённым монитором, будет неудобно — нет привычного DE. Решается через SSH с другой машины.

### 7.6. WireGuard поверх CPE710 — порт UDP/51820 не проверен на проход

**Гипотеза:** CPE710 в bridge-режиме должен пропускать всё, но если он будет в роутер-режиме — UDP 51820 может потребовать port-forward или вообще не пройти.

**Решение:** убедиться, что CPE710 настроен в **Bridge** Operation Mode, а не Router.

---

## 8. Следующие шаги (в порядке приоритета)

1. **Прошить и настроить обе Orange Pi 5** по `STEP-3-orange-pi-setup.md` — установить Ubuntu 24.04 от Joshua Riek, имена хостов, базовые пакеты. ~1 час.

2. **Настроить CPE710 в PtP** по параметрам из STEP-3 (channel 149, 20 MHz, Bridge mode, distance 1 km, фиксированные IP). Проверить `ping` и `iperf3` между Pi через мост. ~30 минут.

3. **Поднять WireGuard-туннель** — сгенерировать ключи, прописать конфиги, запустить `wg-quick up`. Проверить `ping 10.10.0.1`. ~20 минут.

4. **Дождаться адаптеров Waveshare USB-TO-RS485 (B)** ×4 шт. После получения — `lsusb`, узнать USB ID для udev-правил.

5. **Уточнить модель 8-pin разъёма** на У1/У2 (запросить фото у пользователя), заказать ответную часть. **Это блокер для физической сборки.**

6. **Собрать переходник 8-pin → 4 жилы Orange Pi** (2× RS485 на адаптеры, 1× video на видеограббер, 2× питание игнорируем). Проверить мультиметром что белый+жёлтый на `video_out` идут в правильные клеммы.

7. **Подключить адаптеры к Orange Pi и проверить `crsf_bridge.py` в bench-режиме** — запустить с одной стороны, подключить адаптер к ELRS-модулю, посмотреть в логе что есть `uart->udp` трафик. **Здесь же выяснится, работает ли RS485 auto-direction на 420k бод** (см. проблема 7.1).

8. **Подключить видеограббер к VRX**, запустить `video_tx.sh` на У2, `video_rx.sh` на У1, проверить что появляется картинка на HDMI-мониторе.

9. **Уточнить скорость CTRL-канала** (бод rate переключения каналов VRX), создать `crsf-ctrl.env` с правильной скоростью, поднять `crsf-bridge@ctrl.service`.

10. **Заменить IP в env-файлах `192.168.1.x` на `10.10.0.x`** чтобы трафик шёл через WireGuard, а не напрямую через CPE710. Это даёт дополнительный слой шифрования.

11. **Полевые испытания на дистанции 500–1000 м.** Замерить:
    - реальную латенцию видео (gopher-метод: камера снимает экран с миллисекундным таймером, который снимается дроном через VRX)
    - стабильность CRSF (RSSI/потери на пульте П1)
    - throughput через мост в реальных условиях
    - стабильность WireGuard handshake (потери? переподключения?)

12. **После полевых — рассмотреть watchdog/мониторинг:** OSD-наложение на видео с RSSI/SNR, hardware watchdog RK3588, read-only rootfs для production-устойчивости. **Эти задачи только обсуждались**, кода нет.

---

## Чего я не помню точно (нужно уточнить у пользователя или проверить)

- Точная модель USB-видеограббера у пользователя (предположил MS2130, но не подтверждено) — это влияет на параметры `v4l2src` в `video_tx.sh`. Если грабер не умеет MJPEG, надо переделать на YUY2.
- Точная модель Orange Pi 5: 5, 5B, 5+ или 5 Plus. Они немного различаются по периферии. Я полагался на стандартную 5 (RK3588S, end0 интерфейс).
- Объём SSD на У2: «126гссд» в одном из сообщений — это, видимо, опечатка от «256GB SSD». Если 128 GB — этого достаточно, кода это не меняет.
- Какое у пользователя сейчас разрешение camera/VRX — PAL 720×576 или NTSC 720×480. Поставил PAL по умолчанию.
