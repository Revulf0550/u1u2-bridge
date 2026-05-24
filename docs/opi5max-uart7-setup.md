# UART7-M2 на Orange Pi 5 Max (pin 26)

Настройка UART7 в режиме M2 для TX на физическом pin 26 40-pin header.

## Зачем UART7-M2

На 40-pin header OPi 5 Max доступны несколько UART-контроллеров через device-tree overlays. UART7-M2 выбран потому, что:

- Pin 26 свободен (не конфликтует с SPI/I2C/другими UART по умолчанию)
- Контроллер UART7 (`serial@feba0000`) реально работает в M2-конфигурации на этой плате (M1 тоже работает на пинах 29/38, но M2 удобнее по расположению)
- Проверено на kernel 6.1.0-1025-rockchip, joshua-riek Ubuntu 24.04

## Overlay

Файл: `rk3588-uart7-m2.dtbo`

Путь в системе: `/lib/firmware/<kernel-version>/device-tree/rockchip/overlay/rk3588-uart7-m2.dtbo`

## Конфигурация

В `/boot/extlinux/extlinux.conf` под label `l0` добавить строку `fdtoverlays`:

```
fdtoverlays /lib/firmware/6.1.0-1025-rockchip/device-tree/rockchip/overlay/rk3588-uart7-m2.dtbo
```

После изменения — `sudo reboot`.

**Внимание:** при обновлении ядра путь `/lib/firmware/<version>/...` изменится. Нужно обновить `extlinux.conf` на новую версию. Для автоматизации можно использовать `U_BOOT_FDT_OVERLAYS` в `/etc/default/u-boot` с абсолютным `U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"` (см. lesson в CLAUDE.md про `_BOOT_PATH` quirk).

## Результат

После reboot появляется `/dev/ttyS7` (не `ttyS0`, не `ttyUSB*`):

```
crw-rw---- 1 root dialout 4, 71 ... /dev/ttyS7
```

## Доступ

- `sudo` — всегда работает
- Без sudo — пользователь должен быть в группе `dialout`: `sudo usermod -aG dialout $USER` + relogin

## Конфликт с Bluetooth (AP6611)

На OPi 5 Max UART7 в M0-конфигурации штатно занят Bluetooth-чипом AP6611. Overlay M2 переключает pinmux, но BT-сервис (`ap6611s-bluetooth.service`) может продолжать держать `/dev/ttyS7` открытым.

Обязательно перед использованием:

```bash
sudo systemctl disable --now bluetooth.service ap6611s-bluetooth.service
sudo systemctl mask bluetooth.service ap6611s-bluetooth.service
```

Проверка что порт свободен:

```bash
sudo lsof /dev/ttyS7
# должно быть пусто
```

## Verify-команды

```bash
# 1. Устройство существует
ls -l /dev/ttyS7

# 2. Overlay загружен
grep uart7 /boot/extlinux/extlinux.conf

# 3. BT-сервисы замаскированы
systemctl is-active bluetooth.service ap6611s-bluetooth.service
# ожидание: inactive

# 4. Порт свободен
sudo lsof /dev/ttyS7
# ожидание: пусто

# 5. Loopback-тест (соединить pin 26 TX с другим UART RX, или проверить pyserial)
python3 -c "import serial; s=serial.Serial('/dev/ttyS7', 420000, timeout=1); print('OK'); s.close()"
```
