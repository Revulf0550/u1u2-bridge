# Orange Pi 5 Max — 40-pin GPIO + проектные подключения

> Источник: `sudo gpio readall` + `pinctrl-rockchip` debugfs на u2-pi (kernel 6.1.0-1025-rockchip, joshua-riek Ubuntu 24.04).
> Дата создания: 2026-05-22. Последнее обновление: 2026-05-22 (UART7 bringup, см. "История").
>
> Этот файл — единая точка правды для проекта `u1u2-bridge`. Обновляй при каждом изменении физических подключений (раздел "Подключения" ниже).

---

## Ориентация гребёнки

Смотришь на плату сверху, гребёнка справа (вдоль края). **Pin 1** — у угла, ближайшего к боковым кнопкам (BOOT/POWER). **Pin 39** — у дальнего угла.

- Левая колонка таблицы — нечётные пины (1, 3, 5, ..., 39).
- Правая колонка — чётные (2, 4, 6, ..., 40).

---

## Полная распиновка

Сокращения: **PWR** = питание; **GND** = земля; **UART/I2C/SPI/PWM** = соответствующие интерфейсы; **GPIO** = общий вход/выход.

| Pin |     Имя             | Тип  |   | Pin |     Имя              | Тип    |
|----:|---------------------|------|---|----:|----------------------|--------|
|   1 | 3.3V                | PWR  |   |   2 | 5V                   | PWR    |
|   3 | SDA.2 (GPIO16)      | I2C  |   |   4 | 5V                   | PWR    |
|   5 | SCL.2 (GPIO15)      | I2C  |   |   6 | GND                  | GND    |
|   7 | PWM3 (GPIO39)       | PWM  |   |   8 | GPIO0_B5             | GPIO   |
|   9 | GND                 | GND  |   |  10 | GPIO0_B6             | GPIO   |
|  11 | GPIO1_A0            | GPIO |   |  12 | GPIO4_B3             | GPIO   |
|  13 | GPIO1_A1            | GPIO |   |  14 | GND                  | GND    |
|  15 | GPIO1_A2            | GPIO |   |  16 | GPIO1_A3             | GPIO   |
|  17 | 3.3V                | PWR  |   |  18 | GPIO1_A4             | GPIO   |
|  19 | SPI0_TXD            | SPI  |   |  20 | GND                  | GND    |
|  21 | SPI0_RXD            | SPI  |   |  22 | GPIO1_B0             | GPIO   |
|  23 | SPI0_CLK            | SPI  |   |  24 | SPI0_CS0             | SPI    |
|  25 | GND                 | GND  |   |  26 | SPI0_CS1             | SPI    |
|  27 | GPIO1_B7            | GPIO |   |  28 | GPIO1_B6             | GPIO   |
|**29**| **UART7_TX (GPIO3_C1)** |**UART**| |  30 | GND               | GND    |
|  31 | GPIO3_B5            | GPIO |   |  32 | GPIO1_D6             | GPIO   |
|  33 | GPIO3_B6            | GPIO |   |  34 | GND                  | GND    |
|  35 | GPIO3_C2            | GPIO |   |  36 | GPIO3_D7             | GPIO   |
|  37 | GPIO3_D3            | GPIO |   |**38**| **UART7_RX (GPIO3_C0)** |**UART**|
|  39 | GND                 | GND  |   |  40 | GPIO3_B7             | GPIO   |

**Примечание про UART7:** активируется только при загруженном overlay `rk3588-uart7-m1.dtbo` (см. `/boot/extlinux/extlinux.conf`, строка `fdtoverlays`). Без overlay'я пины 29 и 38 работают как обычный GPIO. Вариант **m2** для Pi 5 Max **не работоспособен** — активирует ноду, но RX-пин остаётся в состоянии `GPIO UNCLAIMED`.

**Примечание про пины 8/10:** в `gpio readall` показываются в режиме `ALT10`, что на стоке Pi 5 соответствует UART2_M0. На Orange Pi 5 **Max** в нашей конфигурации UART2 не задействован, и эти пины никак не используются в проекте.

---

## Подключения в проекте

### u2-pi → ELRS TX модуль (UART7 через overlay m1)

**⚠️ Перед паянием — loopback-тест на пинах 29 и 38!** Закоротить их одним female-female проводком (наискосок через гребёнку), запустить:

```bash
python3 -c 'import serial,time; ser=serial.Serial("/dev/ttyS7",baudrate=420000,timeout=2,write_timeout=2); ser.reset_input_buffer(); ser.write(b"TEST123"); ser.flush(); time.sleep(0.1); print("in_waiting=",ser.in_waiting); data=ser.read(ser.in_waiting); print("got",len(data),"bytes:",repr(data)); ser.close()'
```

Если `in_waiting=7` и `got 7 bytes: b'TEST123'` — пинаут подтверждён, можно подключать ELRS. Если `in_waiting >> 7` (буфер забит мусором) — перемычка не контачит, попробуй другую. Если `in_waiting=0` — overlay не загружен или сидит не на m1 (см. `sudo grep -ri uart7 /sys/kernel/debug/pinctrl/ | grep pinmux-pins`).

| Pin Pi | Имя         | → ELRS TX модуль   | Назначение                              | Статус |
|-------:|-------------|--------------------|------------------------------------------|--------|
|      2 | 5V          | +5V                | Питание модуля (~100-300 мА)            | [ ]    |
|      6 | GND         | GND                | Общая земля                              | [ ]    |
|     29 | UART7_TX    | RX (CRSF input)    | Pi → ELRS — команды от joystick          | [ ]    |
|     38 | UART7_RX    | TX (CRSF output)   | ELRS → Pi — телеметрия с дрона           | [ ]    |

Поставь `[x]` напротив каждой строки после физической пайки и проверки.

**Неудобство распайки:** пины 29 и 38 на **разных сторонах** гребёнки (29 — нечётная сторона, 38 — чётная) и **наискосок**. Это требует двух проводов через всю гребёнку либо аккуратной разводки. Учитывать при сборке корпуса.

### u2-pi → USB-грабер (для будущего видео-пути в Step 5)

| Pin Pi    | Куда                  | Назначение                  | Статус |
|-----------|-----------------------|-----------------------------|--------|
| USB 3.0   | EasyCAP-грабер        | composite → /dev/video0     | [ ]    |
| (RCA вход грабера) | VRX composite out | analog 5.8 ГГц от дрона | [ ]    |

### u1-pi → джойстик TX12 (для control-цепи)

| Pin Pi    | Куда                  | Назначение                            | Статус |
|-----------|-----------------------|---------------------------------------|--------|
| USB any   | RadioMaster TX12      | HID joystick → /dev/input/eventN      | [ ]    |
| HDMI      | очки оператора        | декодированное видео из u2-pi         | [ ]    |

---

## История

- **2026-05-22 (первичное)**: первичная распиновка получена через `sudo gpio readall` на u2-pi (joshua-riek 24.04, kernel 6.1.0-1025-rockchip). Изначально предположили, что пины 8/10 (ALT10) — это UART7. Это **оказалось неверно** для Pi 5 Max.

- **2026-05-22 (UART7 bringup)**: попытка использовать overlay `rk3588-uart7-m2.dtbo` через ручную правку `/boot/extlinux/extlinux.conf` (пакет `u-boot-menu` молча игнорирует переменную `U_BOOT_FDT_OVERLAYS` в `/etc/default/u-boot`). M2 активировал ноду `serial@feba0000` (status=okay, `/dev/ttyS7` пишется без timeout), но привязывал пинмукс к pin 44/45 (физ. 24/26 — `SPI0_CS0/CS1`), причём RX-сторона оставалась в состоянии `GPIO UNCLAIMED`. Loopback на пинах 24/26 не работал ни на 420 000, ни на 9600 бод.

  Переключение на `rk3588-uart7-m1.dtbo` дало правильную привязку: **pin 112 (gpio3-16) = GPIO3_C0 = физ. 38 = RX**, **pin 113 (gpio3-17) = GPIO3_C1 = физ. 29 = TX**. Loopback на 420 000 бод прошёл успешно: отправили `b'TEST123'`, получили `b'TEST123'`, `in_waiting=7`. Это и закрепляется как рабочая распиновка для подключения к ELRS TX.

  **Открытый вопрос:** правка `extlinux.conf` помечена как auto-generated и пропадёт при следующем обновлении ядра / `u-boot-update`. Нужен механизм персистентности (см. Chunk D в HANDOFF).
