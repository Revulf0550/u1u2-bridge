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
# Опциональные env:
#   TRANSPORT=tunnel|direct       # адресация CRSF-peer (единый источник истины):
#                                 #   tunnel = WireGuard 10.8.0.x (ДЕФОЛТ),
#                                 #   direct = CPE710 LAN 192.168.1.x.
#                                 # Видео-peer (u2) тоже из TRANSPORT → video.env.
#   SERIAL_DEV=/dev/...           # переопределить serial CRSF
#                                 #   (дефолт: u1=/dev/ttyUSB0, u2=/dev/ttyS7)
#   PEER_IP_OVERRIDE=10.8.0.4      # переопределить peer ТОЛЬКО для netplan
#                                  # (на env CRSF не влияет — те берут TRANSPORT)
#   SKIP_NETPLAN=1                 # не трогать netplan (в tunnel — авто-1)
#   SKIP_VIDEO=1                   # не enable/start video-tx (U2) / video-rx (U1).
#                                  # Нужно на бенче без grabber / HDMI:
#                                  # иначе gst-launch падает и юнит уходит в
#                                  # бесконечный Restart-loop, забивая journalctl.
#   SKIP_APT=1                     # пропустить apt update/install (оффлайн-
#                                  # редеплой / поле, Режим №2; пакеты уже стоят).

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

TRANSPORT="${TRANSPORT:-tunnel}"
if [[ "$TRANSPORT" != "tunnel" && "$TRANSPORT" != "direct" ]]; then
  echo "Usage: TRANSPORT={tunnel|direct} $0 {u1|u2}" >&2
  exit 1
fi
# В tunnel-режиме статический 192.168.1.x netplan не нужен (адресация — WG);
# без авто-skip дефолтный запуск переписал бы LAN и порвал текущий линк.
if [[ "$TRANSPORT" == "tunnel" && -z "${SKIP_NETPLAN:-}" ]]; then
  SKIP_NETPLAN=1
  echo "==> TRANSPORT=tunnel → netplan не трогаем (SKIP_NETPLAN=1 авто)"
fi

SKIP_APT="${SKIP_APT:-}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

REPO="$(cd "$(dirname "$0")" && pwd)"
echo "==> repo: $REPO  role: $ROLE  mode: $MODE  transport: $TRANSPORT"

# --- 1. зависимости -----------------------------------------------------------
# SKIP_APT=1 — пропустить установку пакетов (оффлайн-редеплой / поле, Режим №2:
# у Pi нет интернета, пакеты уже стоят). Без guard `apt update` при set -e
# оборвал бы скрипт. Локальные проверки (§2 RKMPP) выполняются всегда.
if [[ -n "$SKIP_APT" ]]; then
  echo "==> SKIP_APT: пропускаю apt (зависимости считаю установленными)"
else
  apt update
  apt install -y \
    python3 python3-serial \
    gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    gstreamer1.0-rockchip1 \
    cage \
    v4l-utils \
    wireguard wireguard-tools \
    curl git

  if [[ "$MODE" == "drone" ]]; then
    apt install -y python3-evdev
  fi
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

# --- 2b. UART7 setup (только для роли u2) ------------------------------------
# Автоматизирует три ручных шага из bringup-сессии 2026-05-22 (см.
# docs/handoff/2026-05-22-late-uart7-bringup-complete.md, секция TL;DR):
#   - регистрация overlay m1 через /etc/default/u-boot (Lesson 2: _BOOT_PATH=""
#     quirk на joshua-riek — путь должен быть абсолютным),
#   - mask BT-сервисов, иначе AP6611-стек через brcm_patchram_plus захватит
#     /dev/ttyS7 (Lesson 1).
# Idempotent: маркер-строка "# u1u2-bridge UART7" в /etc/default/u-boot и
# проверка is-enabled=masked для сервисов. UART7_CHANGED=1 ставится только
# если реально что-то поменялось — тогда в конце скрипта печатается
# REBOOT REQUIRED.
UART7_CHANGED=0
if [[ "$ROLE" == "u2" ]]; then
  if ! command -v u-boot-update &>/dev/null; then
    echo "!! u-boot-update not found — not a joshua-riek image?" >&2
    exit 1
  fi

  if ! grep -qF "# u1u2-bridge UART7" /etc/default/u-boot; then
    cat >> /etc/default/u-boot <<'EOF'

# u1u2-bridge UART7 on pins 29/38 (TX/RX) via overlay m1.
# См. docs/handoff/2026-05-22-late-uart7-bringup-complete.md (Lesson 2)
U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"
U_BOOT_FDT_OVERLAYS="device-tree/rockchip/overlay/rk3588-uart7-m1.dtbo"
EOF
    u-boot-update
    UART7_CHANGED=1
    echo "==> UART7 overlay registered in /etc/default/u-boot"
  else
    echo "==> UART7 overlay already configured in /etc/default/u-boot"
  fi

  for svc in bluetooth.service ap6611s-bluetooth.service; do
    if ! systemctl list-unit-files "$svc" 2>/dev/null | grep -qE "^${svc}\s"; then
      continue
    fi
    state="$(systemctl is-enabled "$svc" 2>/dev/null || echo "")"
    if [[ "$state" == "masked" ]]; then
      continue
    fi
    systemctl disable --now "$svc" 2>/dev/null || true
    systemctl mask "$svc" 2>/dev/null || true
    UART7_CHANGED=1
    echo "==> $svc disabled and masked"
  done
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
# Реальная схема (вариант №1): u1 = crsf-bridge@p1 (Boxer → CH340 → ttyUSB0),
# u2 = crsf-bridge@elrs (UART7 ttyS7 → ELRS). Один инстанс на роль, порт 14552.
# Peer берётся из TRANSPORT (единый источник истины), НЕ из PEER_IP_OVERRIDE.
if [[ "$TRANSPORT" == "tunnel" ]]; then
  if [[ "$ROLE" == "u2" ]]; then CRSF_PEER="10.8.0.6"; else CRSF_PEER="10.8.0.7"; fi
else
  if [[ "$ROLE" == "u2" ]]; then CRSF_PEER="192.168.1.20"; else CRSF_PEER="192.168.1.10"; fi
fi
CRSF_PORT=14552

if [[ "$MODE" == "drone" && "$ROLE" == "u1" ]]; then
  # u1 plan B (отложенный): пульт как USB-HID joystick, не CRSF через JR-bay.
  cat > /etc/u1u2-bridge/joystick.env <<EOF
DEVICE=/dev/input/event0
PEER=$CRSF_PEER:$CRSF_PORT
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
elif [[ "$ROLE" == "u1" ]]; then
  # u1 вариант №1 (текущий): пульт Boxer → CH340 → /dev/ttyUSB0 → crsf-bridge@p1.
  # CH340 даёт SerialNumber=0 → udev-symlink невозможен, ttyUSB0 напрямую.
  cat > /etc/u1u2-bridge/crsf-p1.env <<EOF
SERIAL_DEV=${SERIAL_DEV:-/dev/ttyUSB0}
BAUD=420000
LISTEN=0.0.0.0:$CRSF_PORT
PEER=$CRSF_PEER:$CRSF_PORT
EOF
else
  # u2: UDP → crsf-bridge@elrs → /dev/ttyS7 (UART7) → ELRS-модуль.
  cat > /etc/u1u2-bridge/crsf-elrs.env <<EOF
SERIAL_DEV=${SERIAL_DEV:-/dev/ttyS7}
BAUD=420000
LISTEN=0.0.0.0:$CRSF_PORT
PEER=$CRSF_PEER:$CRSF_PORT
EOF
fi

# --- 7b. env видео-передатчика (только u2, ОБА транспорта) --------------------
# Видео-peer u2 == адрес u1 в активном транспорте == $CRSF_PEER (u2 шлёт и
# CRSF-телеметрию, и видео на один и тот же u1). Пишем в ОБОИХ режимах —
# единый источник истины, как у CRSF. Это закрывает дыру переключателя:
# direct→tunnel перезапишет .20 на 10.8.0.6, tunnel→direct — наоборот.
# Fallback PEER_HOST=10.8.0.6 в video_tx.sh остаётся только аварийным.
if [[ "$ROLE" == "u2" ]]; then
  cat > /etc/u1u2-bridge/video.env <<EOF
PEER_HOST=$CRSF_PEER
EOF
  echo "==> video.env: PEER_HOST=$CRSF_PEER ($TRANSPORT, → u1)"
fi

# --- 7c. UFW allow для direct-моста (192.168.1.x) ----------------------------
# Только TRANSPORT=direct. СТРОГО аддитивно: ufw allow idempotent (повтор даёт
# "Skipping adding existing rule"). НИКОГДА `ufw enable`, НИКОГДА смена
# default-policy. Если ufw inactive (u1) — правила лягут спящими, это ок.
# Парно к смене CRSF/видео-source: без этого UFW на active-стороне (u2) молча
# дропнет пакеты с нового источника (CLAUDE.md Lessons 2026-05-24 / 2026-06-05).
if [[ "$TRANSPORT" == "direct" ]] && command -v ufw &>/dev/null; then
  if [[ "$ROLE" == "u2" ]]; then
    ufw allow from 192.168.1.20 to any port 14552 proto udp comment "u1 CRSF local-subnet"
    ufw allow from 192.168.1.0/24 to any port 22 proto tcp comment "SSH from bridge subnet"
  else
    ufw allow from 192.168.1.10 to any port 5600 proto udp comment "u2 video local-subnet"
  fi
  echo "==> UFW: direct-allow добавлены (role=$ROLE, аддитивно, без enable)"
fi

# --- 8. udev-правила для адаптеров ------------------------------------------
# Правила теперь генерируются отдельным интерактивным скриптом setup_udev.sh
# по реальным серийникам подключённых адаптеров. Здесь — только напоминание.
if [[ "$MODE" == "drone" && "$ROLE" == "u1" ]]; then
  echo "==> drone-u1 (plan B): пульт как USB-HID, UART-адаптер не нужен"
elif [[ "$ROLE" == "u1" ]]; then
  CRSF_SERIAL="${SERIAL_DEV:-/dev/ttyUSB0}"
  if [[ ! -e "$CRSF_SERIAL" ]]; then
    echo
    echo "==> $CRSF_SERIAL ещё нет — подключи пульт Boxer (CH340)."
    echo "    CH340 даёт SerialNumber=0, udev-symlink невозможен — crsf-p1.env"
    echo "    использует /dev/ttyUSB0 напрямую (один адаптер на хосте)."
  else
    echo "==> $CRSF_SERIAL на месте (пульт Boxer → crsf-bridge@p1)"
  fi
else
  CRSF_SERIAL="${SERIAL_DEV:-/dev/ttyS7}"
  if [[ ! -e "$CRSF_SERIAL" ]]; then
    echo
    echo "==> $CRSF_SERIAL ещё нет — нужен UART7 overlay (см. §2b выше) + reboot."
  else
    echo "==> $CRSF_SERIAL на месте (UART7 → ELRS, crsf-bridge@elrs)"
  fi
fi

# Проверка, что пользователь, под которым работает systemd-юнит, в dialout —
# иначе сервис не сможет открыть serial-устройство CRSF.
if ! getent group dialout | grep -qw "${SUDO_USER:-ubuntu}"; then
  echo
  echo "!! ${SUDO_USER:-ubuntu} не в группе dialout. Выполните:"
  echo "   sudo usermod -aG dialout ${SUDO_USER:-ubuntu}  &&  logout/login"
fi

# --- 9. подготовка u1 для cage+waylandsink ------------------------------------
# kmssink на joshua-riek + RK3588 сломан VOP2-багами (см. CLAUDE.md Lessons
# 2026-06-03), вместо него — cage --> waylandsink. cage требует
# XDG_RUNTIME_DIR=/run/user/0; /run/user — tmpfs, после ребута каталога нет,
# video-rx упадёт. tmpfiles.d пересоздаёт при boot.
# Service-mode подтверждён на железе 2026-06-04: cage от root под systemd берёт
# DRM-master напрямую (libseat logind фейлится — нет seat0 — но wlroots падает
# на builtin/direct backend), минимального юнита video-rx.service достаточно,
# VT/PAM-обвязка не нужна. См. CLAUDE.md Lessons 2026-06-04.
if [[ "$ROLE" == "u1" ]]; then
  systemctl set-default multi-user.target
  systemctl disable --now gdm3 lightdm sddm 2>/dev/null || true

  cat > /etc/tmpfiles.d/u1u2-bridge.conf <<'EOF'
# /run/user/0 для cage в video-rx.service (waylandsink).
d /run/user/0 0700 root root -
EOF
  systemd-tmpfiles --create /etc/tmpfiles.d/u1u2-bridge.conf >/dev/null
  echo "==> u1: cage XDG_RUNTIME_DIR=/run/user/0 prepared via tmpfiles.d"
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

# CRSF: один инстанс на роль. u1=@p1 (или joystick в plan B), u2=@elrs.
if [[ "$MODE" == "drone" && "$ROLE" == "u1" ]]; then
  systemctl enable --now joystick-to-crsf.service
elif [[ "$ROLE" == "u1" ]]; then
  systemctl enable --now crsf-bridge@p1.service
else
  systemctl enable --now crsf-bridge@elrs.service
fi

# Видео отвязано от MODE: u2=video-tx, u1=video-rx.
if [[ -z "${SKIP_VIDEO:-}" ]]; then
  if [[ "$ROLE" == "u2" ]]; then
    systemctl enable --now video-tx.service
  else
    systemctl enable --now video-rx.service
  fi
else
  echo "==> SKIP_VIDEO=1 — video-tx/video-rx не активируется"
fi

echo
echo "=========================================================================="
echo " Готово. Проверка:"
echo "   ping -i 0.2 $PEER_IP                    # связь по CPE710 (direct)"
if [[ "$MODE" == "drone" && "$ROLE" == "u1" ]]; then
  echo "   systemctl status joystick-to-crsf"
elif [[ "$ROLE" == "u1" ]]; then
  echo "   systemctl status crsf-bridge@p1"
else
  echo "   systemctl status crsf-bridge@elrs"
fi
if [[ -z "${SKIP_VIDEO:-}" ]]; then
  if [[ "$ROLE" == "u2" ]]; then
    echo "   journalctl -u video-tx -f --since '1 min ago'"
  else
    echo "   journalctl -u video-rx -f --since '1 min ago'"
  fi
fi
if [[ "$UART7_CHANGED" == "1" ]]; then
  echo
  echo "!! ВНИМАНИЕ: внесены изменения в /etc/default/u-boot или BT-сервисы."
  echo "!! Для активации UART7 на пинах 29/38 — ТРЕБУЕТСЯ REBOOT:  sudo reboot"
fi
echo "=========================================================================="
