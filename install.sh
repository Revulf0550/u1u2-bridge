#!/bin/bash
# install.sh — инсталлятор u1u2-bridge на Orange Pi 5.
#
# Использование:
#   sudo ./install.sh u1      # на мастер-пульте
#   sudo ./install.sh u2      # на выносной базе
#
# Предполагается Ubuntu 24.04 от joshua-riek/ubuntu-rockchip (или Armbian
# с rockchip-mpp). Сетевая адресация (CPE710 LAN):
#   У2 Orange Pi:    192.168.1.10
#   У1 Orange Pi:    192.168.1.20
#   CPE710 master:   192.168.1.2
#   CPE710 slave:    192.168.1.3
#
# Сетевой интерфейс определяется автоматически (см. §7.2 HANDOFF).
# Можно переопределить вручную: IFACE=eth0 sudo ./install.sh u2

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
  wireguard wireguard-tools \
  curl git

# --- 2. проверка RKMPP --------------------------------------------------------
if ! gst-inspect-1.0 mpph264enc &>/dev/null; then
  echo "!! mpph264enc не найден — проверьте, что установлен gstreamer1.0-rockchip1"
  echo "!! и что вы на образе с поддержкой Rockchip MPP (joshua-riek или Armbian)"
  exit 1
fi
echo "==> RKMPP encoder available"

# --- 3. определение сетевого интерфейса --------------------------------------
# Если IFACE задана явно — используем её, иначе берём первый не-lo интерфейс.
IFACE="${IFACE:-$(ip -br link | awk '$1 != "lo" {print $1; exit}')}"
if [[ -z "$IFACE" ]]; then
  echo "!! Не удалось определить сетевой интерфейс. Задайте вручную:" >&2
  echo "!!   IFACE=eth0 sudo ./install.sh $ROLE" >&2
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

# --- 5. код проекта -----------------------------------------------------------
install -d /etc/u1u2-bridge
install -d /opt/u1u2-bridge/common "/opt/u1u2-bridge/$ROLE"
install -m 0755 "$REPO/common/crsf_bridge.py" /opt/u1u2-bridge/common/
install -m 0755 "$REPO/$ROLE"/*.sh "/opt/u1u2-bridge/$ROLE/"

# --- 6. systemd-юниты ---------------------------------------------------------
install -m 0644 "$REPO/common/systemd/crsf-bridge@.service" /etc/systemd/system/
install -m 0644 "$REPO/$ROLE/systemd/"*.service /etc/systemd/system/

# --- 7. env-файлы для CRSF-моста ----------------------------------------------
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

# --- 8. udev-правила: стабильные имена UART -----------------------------------
# ВАЖНО: ID для CP2102N. После того как Waveshare на CH343G придут,
# нужно заменить на 1a86:55d3 (см. §7.3 HANDOFF).
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
echo "   подставьте серийники ваших USB-UART адаптеров (см. udevadm info)"
echo "   После: sudo udevadm trigger"

# --- 9. отключаем display-manager на У1 (kmssink требует tty) -----------------
if [[ "$ROLE" == "u1" ]]; then
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
if [[ "$ROLE" == "u2" ]]; then
  echo "   journalctl -u video-tx -f --since '1 min ago'"
else
  echo "   journalctl -u video-rx -f --since '1 min ago'"
fi
echo "=========================================================================="
