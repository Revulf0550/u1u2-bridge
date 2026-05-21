#!/bin/bash
# setup_udev.sh — интерактивная регистрация Waveshare USB-TO-RS485 адаптеров
# по серийным номерам в udev. Запускается ОДИН РАЗ после физического
# подключения адаптеров. Создаёт стабильные symlinks:
#
#   /dev/ttyACM-CRSF1 → конкретный физический адаптер №1
#   /dev/ttyACM-CRSF2 → конкретный физический адаптер №2
#
# Без udev-правил порядок /dev/ttyACM0 / ttyACM1 непредсказуем между
# ребутами — сервис может попасть на чужой адаптер. См. CLAUDE.md §
# Architecture → "udev-правила для стабильных имён USB-устройств".
#
# Адаптер Waveshare USB-TO-RS485 (B) использует чип WCH CH343G и идёт
# через драйвер cdc_acm как /dev/ttyACMx (НЕ /dev/ttyUSBx — урок
# 2026-05-18 в CLAUDE.md). Скрипт извлекает VID/PID из udevadm на
# реальном устройстве, не хардкодит — это переживает смену ревизии.
#
# Usage: sudo ./setup_udev.sh
# Exit:  0 при успешной регистрации обоих адаптеров, 1 при любой ошибке.

set -euo pipefail

RULES_FILE=/etc/udev/rules.d/90-u1u2-uart.rules
SYMLINK_PREFIX=/dev/ttyACM-CRSF

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: запускайте через sudo" >&2
  exit 1
fi

# --- helpers ------------------------------------------------------------------

# Снимок текущего набора ACM-устройств. Возвращает отсортированный список
# (один файл на строку), либо пусто. Глоб через цикл — `ls /dev/ttyACM*`
# падал бы при отсутствии файлов и shellcheck (SC2012) не любит ls.
snapshot_tty() {
  local f
  for f in /dev/ttyACM*; do
    [[ -e "$f" ]] && echo "$f"
  done | sort -u
}

# Найти ровно одно новое устройство между двумя снимками. Печатает путь к
# устройству; падает с понятной ошибкой при 0 или >1 новых записях.
diff_one_new() {
  local before="$1" after="$2"
  local new
  new="$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after"))"
  local count
  count="$(printf '%s\n' "$new" | grep -cv '^$' || true)"
  if [[ "$count" -eq 0 ]]; then
    echo "ERROR: ни одного нового /dev/ttyACMx не появилось." >&2
    echo "Проверьте: адаптер реально воткнут? \`dmesg | tail\` показывает cdc_acm?" >&2
    return 1
  fi
  if [[ "$count" -gt 1 ]]; then
    echo "ERROR: появилось $count новых устройств — подключайте по ОДНОМУ:" >&2
    printf '  %s\n' "$new" >&2
    return 1
  fi
  printf '%s\n' "$new"
}

# Извлечь ATTRS{serial}, ATTRS{idVendor}, ATTRS{idProduct} для конкретного
# /dev/ttyACMx. udevadm идёт по chain устройств — берём ПЕРВОЕ найденное
# значение каждого атрибута (это уровень USB-устройства, не порта-родителя).
extract_usb_attrs() {
  local dev="$1"
  local info
  info="$(udevadm info -a -n "$dev")"
  local serial vid pid
  serial="$(printf '%s\n' "$info" | grep -m1 'ATTRS{serial}==' | sed -E 's/.*ATTRS\{serial\}=="([^"]+)".*/\1/')"
  vid="$(printf '%s\n'    "$info" | grep -m1 'ATTRS{idVendor}=='  | sed -E 's/.*ATTRS\{idVendor\}=="([^"]+)".*/\1/')"
  pid="$(printf '%s\n'    "$info" | grep -m1 'ATTRS{idProduct}==' | sed -E 's/.*ATTRS\{idProduct\}=="([^"]+)".*/\1/')"
  if [[ -z "$serial" || -z "$vid" || -z "$pid" ]]; then
    echo "ERROR: не смог извлечь serial/VID/PID для $dev." >&2
    echo "Полный вывод udevadm info -a -n $dev — см. ниже:" >&2
    printf '%s\n' "$info" >&2
    return 1
  fi
  # Печатаем три значения через пробел.
  printf '%s %s %s\n' "$serial" "$vid" "$pid"
}

# Подключить N-ный адаптер и вернуть его (serial vid pid path).
register_one() {
  local idx="$1" before after new
  echo
  echo "==> Подключите адаптер для CRSF${idx} (отключив предыдущие, если только что добавили)."
  echo "    Когда индикатор/LED на адаптере загорелся — нажмите ENTER."
  before="$(snapshot_tty)"
  # read без переменной — нам важен факт нажатия ENTER, не само значение
  read -r _
  # Даём ядру 1 секунду на enumeration после физического подключения —
  # иначе на быстрых USB-портах snapshot может прочитаться раньше, чем
  # cdc_acm создаст /dev/ttyACMx.
  sleep 1
  after="$(snapshot_tty)"
  local new_dev
  new_dev="$(diff_one_new "$before" "$after")"
  echo "    Новое устройство: $new_dev"

  local attrs serial vid pid
  attrs="$(extract_usb_attrs "$new_dev")"
  serial="$(echo "$attrs" | awk '{print $1}')"
  vid="$(   echo "$attrs" | awk '{print $2}')"
  pid="$(   echo "$attrs" | awk '{print $3}')"
  echo "    serial=$serial  VID=$vid  PID=$pid"

  # Возвращаем serial vid pid через stdout — caller (main) парсит.
  printf '%s %s %s\n' "$serial" "$vid" "$pid"
}

# --- main ---------------------------------------------------------------------

echo "==> Регистрация Waveshare USB-TO-RS485 (B) адаптеров"
echo "    Скрипт перепишет $RULES_FILE."
echo
echo "    ВНИМАНИЕ: перед началом отсоедините ОБА адаптера CRSF от Pi,"
echo "    скрипт попросит подключить их по очереди."
echo
read -r -p "Готовы? (ENTER чтобы продолжить, Ctrl-C чтобы отменить) "

attrs1="$(register_one 1)"
serial1="$(echo "$attrs1" | awk '{print $1}')"
vid1="$(   echo "$attrs1" | awk '{print $2}')"
pid1="$(   echo "$attrs1" | awk '{print $3}')"

attrs2="$(register_one 2)"
serial2="$(echo "$attrs2" | awk '{print $1}')"
vid2="$(   echo "$attrs2" | awk '{print $2}')"
pid2="$(   echo "$attrs2" | awk '{print $3}')"

if [[ "$serial1" == "$serial2" ]]; then
  echo "ERROR: оба адаптера сообщили одинаковый serial $serial1." >&2
  echo "Это означает что вы подключили один и тот же адаптер дважды." >&2
  exit 1
fi

# --- запись udev-правил -------------------------------------------------------
echo
echo "==> Записываю $RULES_FILE"
cat > "$RULES_FILE" <<EOF
# Auto-generated by setup_udev.sh — Waveshare USB-TO-RS485 (B) на WCH CH343G.
# Драйвер cdc_acm, устройство /dev/ttyACMx (НЕ /dev/ttyUSBx, см. CLAUDE.md
# lesson 2026-05-18). Стабильные symlinks по серийному номеру чипа.
#
# Защита от ModemManager (он может пытаться "позвонить" в CH343G как в модем,
# забирая порт у нашего сервиса).
SUBSYSTEM=="tty", ATTRS{idVendor}=="$vid1", ATTRS{idProduct}=="$pid1", \\
  ATTRS{serial}=="$serial1", SYMLINK+="ttyACM-CRSF1", \\
  ENV{ID_MM_DEVICE_IGNORE}="1", MODE="0660", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="$vid2", ATTRS{idProduct}=="$pid2", \\
  ATTRS{serial}=="$serial2", SYMLINK+="ttyACM-CRSF2", \\
  ENV{ID_MM_DEVICE_IGNORE}="1", MODE="0660", GROUP="dialout"
EOF
chmod 0644 "$RULES_FILE"

# --- reload + проверка --------------------------------------------------------
echo "==> udevadm control --reload && trigger"
udevadm control --reload
udevadm trigger --subsystem-match=tty --action=change

# udev асинхронен; settle ждёт пока все pending события обработаются.
udevadm settle --timeout=5

missing=()
for n in 1 2; do
  link="${SYMLINK_PREFIX}${n}"
  if [[ ! -e "$link" ]]; then
    missing+=("$link")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: symlinks не появились:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo
  echo "Диагностика:" >&2
  echo "  ls -l /dev/ttyACM*" >&2
  echo "  udevadm test \$(udevadm info -q path -n /dev/ttyACM0)" >&2
  echo "  cat $RULES_FILE" >&2
  exit 1
fi

echo
echo "==> Готово. Зарегистрированы:"
ls -l "${SYMLINK_PREFIX}"1 "${SYMLINK_PREFIX}"2
echo
echo "    Дальше: \`sudo systemctl restart crsf-bridge@tx1 crsf-bridge@tx2\`"
echo "    Проверить: \`sudo ./smoke_test.sh \$ROLE\`"
