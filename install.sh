#!/bin/bash
# install.sh — инсталлятор u1u2-bridge на Orange Pi 5 / 5 Max.
#
# Использование:
#   sudo ./install.sh u1      # на мастер-пульте
#   sudo ./install.sh u2      # на выносной базе
#
# Предполагается Ubuntu 24.04 от joshua-riek/ubuntu-rockchip (или Armbian
# с rockchip-mpp). Сетевая адресация (CPE710 LAN, Phase 1):
#   У2 Orange Pi:    192.168.1.10
#   У1 Orange Pi:    192.168.1.20
#   CPE710 master:   192.168.1.2
#   CPE710 slave:    192.168.1.3
#
# Сетевой интерфейс определяется автоматически (см. §7.2 HANDOFF). Имя
# зависит от модели платы: `end0` на Pi 5, `enP3p49s0` на Pi 5 Max.
# Переопределить вручную: IFACE=eth0 sudo ./install.sh u2
#
# UDEV-правила для адаптеров регистрируются ОТДЕЛЬНЫМ скриптом после
# физического подключения адаптеров:  sudo ./setup_udev.sh
# (install.sh больше не пишет placeholder-rules — это упрощает обновление
#  при пересборке адаптеров: меняй только setup_udev.sh, install.sh не
#  трогаем.)
#
# Опциональные env (для bench / VPN-фазы):
#   PEER_IP_OVERRIDE=10.8.0.4      # перенаправить PEER в env-файлах на VPN
#                                  # (вместо локального 192.168.1.x)
#   SKIP_NETPLAN=1                 # не трогать netplan (сеть уже настроена)
#   SKIP_VIDEO=1                   # не enable/start video-tx (U2) / video-rx (U1).
#                                  # Нужно на бенче без MS2130 grabber / HDMI-очков:
#                                  # иначе gst-launch падает и юнит уходит в
#                                  # бесконечный Restart-loop, забивая journalctl.

set -euo pipefail

ROLE="${1:-}"
if [[ "$ROLE" != "u1" && "$ROLE" != "u2" ]]; then
  echo "Usage: $0 {u1|u2}" >&2
  exit 1
fi

MODE="${MODE:-bench}"
if [[ "$MODE" != "bench" && "$MODE" != "drone" ]]; then
  echo "Usage: MODE={bench|drone} $0 {u1|u2}" >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

REPO="$(cd "$(dirname "$0")" && pwd)"
echo "==> repo: $REPO  role: $ROLE  mode: $MODE"

# --- 1. зависимости -----------------------------------------------------------
apt update
apt install -y \
  python3 python3-serial \
  gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly gstreamer1.0-libav \
  gstreamer1.0-rockchip1 \
  v4l-utils \
  wireguard wireguard-tools \
  curl git

if [[ "$MODE" == "drone" ]]; then
  apt install -y python3-evdev
fi

# --- 2. проверка RKMPP --------------------------------------------------------
if [[ "$MODE" == "bench" ]]; then
  if ! gst-inspect-1.0 mpph264enc &>/dev/null; then
    echo "!! mpph264enc не найден — проверьте, что установлен gstreamer1.0-rockchip1"
    echo "!! и что вы на образе с поддержкой Rockchip MPP (joshua-riek или Armbian)"
    exit 1
  fi
  echo "==> RKMPP encoder available"
fi

# --- 3. определение сетевого интерфейса --------------------------------------
# Если IFACE задан явно — используем его. Иначе берём первый не-lo интерфейс
# в состоянии UP (это отсекает wlan/usb-eth, которые поднялись но не подключены).
IFACE="${IFACE:-$(ip -br link | awk '$1 != "lo" && $2 == "UP" {print $1; exit}')}"
if [[ -z "$IFACE" ]]; then
  echo "!! Не удалось определить активный (UP) сетевой интерфейс. Задайте вручную:" >&2
  echo "!!   IFACE=enP3p49s0 sudo ./install.sh $ROLE" >&2
  exit 1
fi
echo "==> network interface: $IFACE"

# --- 4. сеть: статический IP --------------------------------------------------
if [[ "$ROLE" == "u2" ]]; then
  IP_ADDR="192.168.1.10/24"
  PEER_IP="192.168.1.20"
else
  IP_ADDR="192.168.1.20/24"
  PEER_IP="192.168.1.10"
fi

# Для bench-фазы через WireGuard можно перенаправить PEER на VPN-адрес —
# тогда CRSF-трафик пойдёт через туннель (10.8.0.x), а не локально (192.168.1.x).
if [[ -n "${PEER_IP_OVERRIDE:-}" ]]; then
  echo "==> PEER_IP_OVERRIDE задан: $PEER_IP -> $PEER_IP_OVERRIDE"
  PEER_IP="$PEER_IP_OVERRIDE"
fi

if [[ -z "${SKIP_NETPLAN:-}" ]]; then
  NETPLAN_FILE=/etc/netplan/99-u1u2-bridge.yaml
  cat > "$NETPLAN_FILE" <<EOF
network:
  version: 2
  ethernets:
    $IFACE:
      addresses: [$IP_ADDR]
      dhcp4: false
      dhcp6: false
      nameservers:
        addresses: [1.1.1.1]
EOF
  chmod 0600 "$NETPLAN_FILE"
  netplan apply || true
  echo "==> static IP set: $IP_ADDR on $IFACE (peer will be $PEER_IP)"
else
  echo "==> SKIP_NETPLAN=1 — netplan не трогаем (peer будет $PEER_IP)"
fi

# --- 5. код проекта -----------------------------------------------------------
install -d /etc/u1u2-bridge
install -d /opt/u1u2-bridge/common "/opt/u1u2-bridge/$ROLE"
install -m 0755 "$REPO/common/crsf_bridge.py" /opt/u1u2-bridge/common/
install -m 0755 "$REPO/$ROLE"/*.sh "/opt/u1u2-bridge/$ROLE/"

if [[ "$MODE" == "drone" ]]; then
  install -m 0644 "$REPO/common/crsf.py" /opt/u1u2-bridge/common/
  if [[ "$ROLE" == "u1" ]]; then
    install -m 0755 "$REPO/common/joystick_to_crsf.py" /opt/u1u2-bridge/common/
  fi
fi

# --- 6. systemd-юниты ---------------------------------------------------------
install -m 0644 "$REPO/common/systemd/crsf-bridge@.service" /etc/systemd/system/
install -m 0644 "$REPO/$ROLE/systemd/"*.service /etc/systemd/system/

if [[ "$MODE" == "drone" && "$ROLE" == "u1" ]]; then
  install -m 0644 "$REPO/common/systemd/joystick-to-crsf.service" /etc/systemd/system/
fi

# --- 7. env-файлы для CRSF-моста / joystick -----------------------------------
# PEER_HOST зависит от (MODE, ROLE).
# Bench: peer через CPE710 LAN. Drone: peer через WG-туннель.
if [[ "$MODE" == "drone" ]]; then
  if [[ "$ROLE" == "u2" ]]; then
    PEER_HOST="10.8.0.6"
  else
    PEER_HOST="10.8.0.7"
  fi
else
  if [[ "$ROLE" == "u2" ]]; then
    PEER_HOST="192.168.1.20"
  else
    PEER_HOST="192.168.1.10"
  fi
fi

if [[ "$MODE" == "drone" && "$ROLE" == "u1" ]]; then
  # u1-drone: только joystick.env, crsf-tx*.env не нужны
  cat > /etc/u1u2-bridge/joystick.env <<EOF
DEVICE=/dev/input/event0
PEER=$PEER_HOST:14550
RATE_HZ=250
CHANNEL_MAP_PATH=/etc/u1u2-bridge/channels.toml
TELEMETRY_LOG_INTERVAL_SEC=1.0
TELEMETRY_STALE_SEC=5.0
EOF
  # Idempotent копирование дефолтного channel-map. НЕ перезаписываем — иначе
  # затрём пользовательскую калибровку при повторном install.sh.
  if [[ ! -f /etc/u1u2-bridge/channels.toml ]]; then
    install -m 0644 "$REPO/common/channels.default.toml" /etc/u1u2-bridge/channels.toml
    echo "==> channels.toml: установлен дефолт (требует калибровки через evtest)"
  else
    echo "==> channels.toml: уже существует, оставляем как есть"
  fi
else
  # bench (u1+u2) и u2-drone: одинаковые crsf-tx*.env с переменным PEER_HOST
  cat > /etc/u1u2-bridge/crsf-tx1.env <<EOF
SERIAL_DEV=/dev/ttyACM-CRSF1
BAUD=420000
LISTEN=0.0.0.0:14550
PEER=$PEER_HOST:14550
EOF
  cat > /etc/u1u2-bridge/crsf-tx2.env <<EOF
SERIAL_DEV=/dev/ttyACM-CRSF2
BAUD=420000
LISTEN=0.0.0.0:14551
PEER=$PEER_HOST:14551
EOF
fi

# --- 8. udev-правила для адаптеров ------------------------------------------
# Правила теперь генерируются отдельным интерактивным скриптом setup_udev.sh
# по реальным серийникам подключённых адаптеров. Здесь — только напоминание.
if [[ "$MODE" == "drone" && "$ROLE" == "u1" ]]; then
  echo "==> drone-u1: UART-адаптеров нет, setup_udev.sh не нужен"
else
  if [[ ! -e /etc/udev/rules.d/90-u1u2-uart.rules ]]; then
    echo
    echo "==> udev-правила для адаптеров ещё не созданы."
    echo "    После физического подключения адаптеров:"
    echo "        sudo $REPO/setup_udev.sh"
    echo "    Без этого /dev/ttyACM-CRSF1/2 не появятся, и crsf-bridge@tx*"
    echo "    будет крутиться в Restart-loop."
  else
    echo "==> udev-правила уже на месте (/etc/udev/rules.d/90-u1u2-uart.rules)"
  fi
fi

# Проверка, что пользователь, под которым работает systemd-юнит, в dialout —
# иначе после реконнекта адаптера сервис не сможет открыть /dev/ttyACMx.
if ! getent group dialout | grep -qw "${SUDO_USER:-ubuntu}"; then
  echo
  echo "!! ${SUDO_USER:-ubuntu} не в группе dialout. Выполните:"
  echo "   sudo usermod -aG dialout ${SUDO_USER:-ubuntu}  &&  logout/login"
fi

# --- 9. отключаем display-manager на У1 (kmssink требует tty) -----------------
if [[ "$ROLE" == "u1" && "$MODE" == "bench" ]]; then
  systemctl set-default multi-user.target
  systemctl disable --now gdm3 lightdm sddm 2>/dev/null || true
fi

# --- 10. ядро: увеличиваем UDP-буферы -----------------------------------------
cat > /etc/sysctl.d/99-u1u2-bridge.conf <<'EOF'
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.core.netdev_max_backlog=5000
EOF
sysctl --system >/dev/null

# --- 11. запуск ---------------------------------------------------------------
systemctl daemon-reload

if [[ "$MODE" == "drone" ]]; then
  if [[ "$ROLE" == "u1" ]]; then
    systemctl enable --now joystick-to-crsf.service
  else
    systemctl enable --now crsf-bridge@tx1.service
    # tx2 пока не активируем — у дрона один ELRS канал
  fi
else
  systemctl enable --now crsf-bridge@tx1.service
  systemctl enable --now crsf-bridge@tx2.service
  if [[ -z "${SKIP_VIDEO:-}" ]]; then
    if [[ "$ROLE" == "u2" ]]; then
      systemctl enable --now video-tx.service
    else
      systemctl enable --now video-rx.service
    fi
  else
    echo "==> SKIP_VIDEO=1 — video-tx/video-rx не активируется"
  fi
fi

echo
echo "=========================================================================="
echo " Готово. Проверка:"
echo "   ping -i 0.2 $PEER_IP                    # связь по CPE710"
echo "   systemctl status crsf-bridge@tx1 crsf-bridge@tx2"
if [[ -z "${SKIP_VIDEO:-}" ]]; then
  if [[ "$ROLE" == "u2" ]]; then
    echo "   journalctl -u video-tx -f --since '1 min ago'"
  else
    echo "   journalctl -u video-rx -f --since '1 min ago'"
  fi
fi
echo "=========================================================================="
