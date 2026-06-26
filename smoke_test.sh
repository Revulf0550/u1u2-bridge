#!/bin/bash
# smoke_test.sh — постдеплой-проверка u1u2-bridge на Orange Pi.
#
# Запускается после install.sh + setup_udev.sh + (опционально) поднятия
# WireGuard. Каждая проверка независима — мы прогоняем всё и в конце
# печатаем сводный результат. Exit 0 если все проверки PASS, 1 иначе.
#
# Usage:
#   sudo ./smoke_test.sh u1
#   sudo ./smoke_test.sh u2
#
# Зависимости: только coreutils + systemd + iputils-ping + gst-inspect-1.0
# (последнее — из gstreamer1.0-tools, ставится install.sh).

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

# Peer IP — противоположная Pi в /24 подсети CPE710. Симметрично install.sh.
if [[ "$ROLE" == "u1" ]]; then
  PEER_IP="192.168.1.10"
  PEER_IP_WG="${PEER_IP_WG:-10.8.0.7}"
  VIDEO_UNIT="video-rx.service"
  RKMPP_ELEM="mppvideodec"
  CRSF_INST="p1"
else
  PEER_IP="192.168.1.20"
  PEER_IP_WG="${PEER_IP_WG:-10.8.0.6}"
  VIDEO_UNIT="video-tx.service"
  RKMPP_ELEM="mpph264enc"
  CRSF_INST="elrs"
fi

# Управляющий юнит зависит от MODE: drone+u1 = joystick-to-crsf (plan B, USB-HID,
# без UART), иначе crsf-bridge@<inst>. Симметрично install.sh §11.
if [[ "$MODE" == "drone" && "$ROLE" == "u1" ]]; then
  CRSF_UNIT="joystick-to-crsf.service"
  CRSF_LABEL="joystick-to-crsf"
  HAS_SERIAL=0
  STATS_MARKER="udp tx="
else
  CRSF_UNIT="crsf-bridge@${CRSF_INST}.service"
  CRSF_LABEL="crsf-bridge@${CRSF_INST}"
  HAS_SERIAL=1
  STATS_MARKER="uart->udp"
fi

# --- цветной вывод -----------------------------------------------------------
# Включаем ANSI только если stdout — терминал. В pipe / journalctl / CI
# escape-коды сделают вывод нечитаемым (грязная привычка многих CLI).
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_RESET=$'\033[0m'
else
  C_RED=''
  C_GREEN=''
  C_YELLOW=''
  C_RESET=''
fi

# --- accounting ---------------------------------------------------------------
fail_count=0
warn_count=0
fail_list=()

pass()  { printf '  %s[ OK ]%s %s\n'   "$C_GREEN"  "$C_RESET" "$1"; }
warn()  { printf '  %s[WARN]%s %s\n'   "$C_YELLOW" "$C_RESET" "$1"; warn_count=$((warn_count + 1)); }
fail()  { printf '  %s[FAIL]%s %s\n'   "$C_RED"    "$C_RESET" "$1"; fail_count=$((fail_count + 1)); fail_list+=("$1"); }

section() { echo; printf '== %s\n' "$1"; }

# --- проверки -----------------------------------------------------------------

section "systemd units"

# CRSF/управление: юнит зависит от MODE (drone+u1=joystick-to-crsf, иначе crsf-bridge@<inst>).
if systemctl is-active --quiet "$CRSF_UNIT"; then
  pass "$CRSF_LABEL активен"
else
  fail "$CRSF_LABEL НЕ активен (см. \`systemctl status $CRSF_LABEL\`)"
fi

# Видео — на каждой роли свой юнит.
if systemctl is-active --quiet "$VIDEO_UNIT"; then
  pass "$VIDEO_UNIT активен"
else
  fail "$VIDEO_UNIT НЕ активен (см. \`journalctl -u $VIDEO_UNIT -n 50\`)"
fi

section "CRSF serial device"

if [[ "$HAS_SERIAL" != 1 ]]; then
  pass "serial N/A — plan B (USB-HID джойстик, без UART-адаптера)"
else
  # Имя устройства берём из env-файла моста, не хардкодим: железо разное по ролям —
  # u1: CH340 → /dev/ttyUSB0 (raw, без udev-symlink — CH340 даёт SerialNumber=0);
  # u2: /dev/ttyS7 (аппаратный UART7 RK3588, не USB — symlink неприменим).
  CRSF_ENV="/etc/u1u2-bridge/crsf-${CRSF_INST}.env"
  if [[ ! -f "$CRSF_ENV" ]]; then
    fail "$CRSF_ENV не найден — install.sh не отработал?"
  else
    SERIAL_DEV="$(awk -F= '/^SERIAL_DEV=/ {v=$2} END {print v}' "$CRSF_ENV")"
    if [[ -z "$SERIAL_DEV" ]]; then
      fail "SERIAL_DEV не задан в $CRSF_ENV"
    elif [[ -e "$SERIAL_DEV" ]]; then
      pass "$SERIAL_DEV существует (SERIAL_DEV из $CRSF_ENV)"
    else
      fail "$SERIAL_DEV отсутствует — устройство не подключено / UART7 overlay не загружен (см. $CRSF_ENV)"
    fi
  fi
fi

section "RKMPP (hardware H.264)"

# Проверяем элемент RKMPP под роль: u1 декодирует (mppvideodec в video_rx.sh),
# u2 кодирует (mpph264enc в video_tx.sh). Оба из gstreamer1.0-rockchip1, но
# проверяем именно используемый ролью — иначе на u1 битый декодер дал бы
# ложный PASS. Без нужного элемента видео-пайплайн упадёт в Restart-loop.
if gst-inspect-1.0 "$RKMPP_ELEM" >/dev/null 2>&1; then
  pass "$RKMPP_ELEM доступен"
else
  fail "$RKMPP_ELEM не найден — это не joshua-riek образ? \`apt install gstreamer1.0-rockchip1\`"
fi

section "network: peer через CPE710"

# -W 1 — 1s timeout на ответ; -c 3 — три попытки. 3 attempts + 1s каждый
# = max ~3 секунды wall-clock на проверку. Достаточно для local-LAN PtP.
if ping -c 3 -W 1 "$PEER_IP" >/dev/null 2>&1; then
  pass "ping $PEER_IP проходит"
else
  fail "ping $PEER_IP не проходит — проверь CPE710 (см. docs/CPE710-SETUP.md)"
fi

section "network: WireGuard туннель"

# WG-туннель опционален: если wg0 интерфейса нет — пропускаем без FAIL,
# чтобы не блокировать smoke-test на bench-фазе (поднимается перед полевыми).
if ip link show wg0 >/dev/null 2>&1; then
  if ping -c 3 -W 1 "$PEER_IP_WG" >/dev/null 2>&1; then
    pass "ping $PEER_IP_WG через wg0 проходит"
  else
    fail "wg0 поднят, но ping $PEER_IP_WG не проходит (handshake? см. \`wg show\`)"
  fi
else
  warn "wg0 не поднят — пропускаю проверку WireGuard (это норма для bench-фазы)"
fi

section "мост гоняет байты (требует ≥10s после старта)"

# Управляющий юнит пишет stats-строку раз в 10 секунд: crsf_bridge.py — "uart->udp",
# joystick_to_crsf.py — "udp tx=" (маркер выбран по MODE выше). Нет строки за минуту —
# сервис только стартовал (подожди) либо нет трафика (UART/джойстик).
if journalctl -u "$CRSF_LABEL" --since '1 min ago' --no-pager 2>/dev/null \
     | grep -q "$STATS_MARKER"; then
  pass "$CRSF_LABEL пишет stats line за последнюю минуту"
else
  warn "$CRSF_LABEL без stats line за минуту — сервис только стартовал? Или вход не подключён?"
fi

# --- итог ---------------------------------------------------------------------
echo
if [[ $fail_count -eq 0 ]]; then
  if [[ $warn_count -eq 0 ]]; then
    printf '%sВсе проверки прошли.%s\n' "$C_GREEN" "$C_RESET"
  else
    printf '%sПрошли с %d warning(s).%s\n' "$C_YELLOW" "$warn_count" "$C_RESET"
  fi
  exit 0
fi

printf '%sПровалено %d проверк(и):%s\n' "$C_RED" "$fail_count" "$C_RESET"
for item in "${fail_list[@]}"; do
  printf '  • %s\n' "$item"
done
exit 1
