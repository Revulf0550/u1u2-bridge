# Orange Pi 5 Max — 40-pin GPIO + проектные подключения

> Источник: `sudo gpio readall` + `pinctrl-rockchip` debugfs на u2-pi (kernel 6.1.0-1025-rockchip, joshua-riek Ubuntu 24.04).
> Дата создания: 2026-05-22. Последнее обновление: 2026-06-13 (overlay m2/pin 26 как боевой деплой, см. баннер ниже).
>
> Этот файл — единая точка правды для проекта `u1u2-bridge`. Обновляй при каждом изменении физических подключений (раздел "Подключения" ниже).

> **⚠️ ОБНОВЛЕНИЕ 2026-06-13 (live `gpio readall` на боевой u2):** деплой работает на **UART7 overlay m2**, TX = физ. **pin 26** (GPIO1_B5, ALT10) → `/dev/ttyS7`, TX-управление односторонне. Это переобрамляет вывод ниже: «m2 не работоспособен» относится к **loopback-тесту** (а он требует RX) — у m2 не поднимается **RX** (UNCLAIMED), но **m2-TX (pin 26) работает** и используется в бою. Путь **m1 (TX 29 / RX 38)** ниже — двунаправленный (рабочий loopback), но в деплое НЕ активен; держим его как **резерв под RX/телеметрию** (RSSI на пульт — трек D). **m1-блок не удалять.** Приоритет источников при расхождении: CLAUDE.md (урок 2026-06-13) → этот файл.

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

**Примечание про UART7:** активируется только при загруженном overlay `rk3588-uart7-m1.dtbo` и **отключённом** Bluetooth-стеке (см. notice ниже в "Подключениях"). Без overlay'я пины 29 и 38 работают как обычный GPIO. Вариант **m2** для Pi 5 Max **не работоспособен** — активирует ноду, но RX-пин остаётся в состоянии `GPIO UNCLAIMED`.

**Примечание про пины 8/10:** в `gpio readall` показываются в режиме `ALT10`, что на стоке Pi 5 соответствует UART2_M0. На Orange Pi 5 **Max** в нашей конфигурации UART2 не задействован, и эти пины никак не используются в проекте.

---

## Подключения в проекте

### u2-pi → ELRS TX модуль (UART7 через overlay m1)

> **⚠️ КРИТИЧНО — отключить Bluetooth перед использованием UART7.** На Orange Pi 5 Max UART7 архитектурно занят встроенным Bluetooth-чипом AP6611 (подтверждено по hardware-спецификации Pi 5 Max от CNX Software и обсуждению на Arch Linux ARM форуме по joshua-riek BSP). При штатной загрузке joshua-riek образа служба `ap6611s-bluetooth.service` запускает `brcm_patchram_plus`, который держит `/dev/ttyS7` открытым для загрузки прошивки в BT-чип. Когда overlay m1 переключает физический pinmux на пины 29/38, BT-чип становится недоступен, патчер зависает и продолжает держать порт. Если параллельно пытаться открыть `/dev/ttyS7` из userspace — конфликт двух клиентов на одном UART-контроллере, RX выдаёт 0 байт.
>
> **Перед использованием UART7 обязательно:**
> ```bash
> sudo systemctl disable --now bluetooth.service ap6611s-bluetooth.service
> sudo systemctl mask bluetooth.service ap6611s-bluetooth.service
> ```
> Проверка: после ребута `sudo lsof /dev/ttyS7` возвращает пусто, `systemctl is-active bluetooth.service ap6611s-bluetooth.service` показывает `inactive`.

**⚠️ Перед паянием — loopback-тест на пинах 29 и 38!** Закоротить их одним female-female проводком (наискосок через гребёнку), запустить:

```bash
python3 -c 'import serial,time; ser=serial.Serial("/dev/ttyS7",baudrate=420000,timeout=2,write_timeout=2); ser.reset_input_buffer(); ser.write(b"TEST123"); ser.flush(); time.sleep(0.1); print("in_waiting=",ser.in_waiting); data=ser.read(ser.in_waiting); print("got",len(data),"bytes:",repr(data)); ser.close()'
```

Если `in_waiting=7` и `got 7 bytes: b'TEST123'` — пинаут подтверждён, можно подключать ELRS. Если `in_waiting >> 7` (буфер забит мусором) — перемычка не контачит, попробуй другую перемычку (Dupont часто бывают с обрывом внутри обжима). Если `in_waiting=0` — варианты: overlay не загружен (проверь `sudo grep -ri uart7 /sys/kernel/debug/pinctrl/ | grep pinmux-pins`), overlay не m1 (на m2 не работает), **или BT-стек не отключён** (см. notice выше).

> **Деплой: half-duplex single-wire (трек D, 2026-06-14).** Эта таблица показывает раздельные TX/RX (pin 29/38) — это ОТМЕНЁННОЕ full-duplex допущение. Реально CRSF к Ranger Micro идёт по одному проводу (инвертированный half-duplex). **Не паять по этой таблице** до пересмотра под half-duplex; узел и план — `docs/roadmap/rx-telemetry.md`.

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

  Переключение на `rk3588-uart7-m1.dtbo` дало правильную привязку: **pin 112 (gpio3-16) = GPIO3_C0 = физ. 38 = RX**, **pin 113 (gpio3-17) = GPIO3_C1 = физ. 29 = TX**. Loopback на 420 000 бод прошёл успешно с пары `b'TEST123'` ↔ `b'TEST123'` (`in_waiting=7`). Это и закрепляется как рабочая распиновка для подключения к ELRS TX.

- **2026-05-22 (late — persistence + BT-конфликт решены)**: достигнута полная persistence overlay'я и устранён конфликт с Bluetooth.
  - **Persistence через `u-boot-update`**: правка `extlinux.conf` руками затирается при следующем обновлении ядра. Правильный путь — `/etc/default/u-boot`. В joshua-riek образе rootfs включает `/boot` (не отдельная партиция), и `u-boot-update` ставит `_BOOT_PATH=""` — все пути в extlinux.conf пишутся абсолютно от корня FS. Поэтому относительные `U_BOOT_FDT_OVERLAYS_DIR="overlays/"` не работают: скрипт ищет файл в `/overlays/`, которого нет. **Рабочая конфигурация**:
    ```
    U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"
    U_BOOT_FDT_OVERLAYS="device-tree/rockchip/overlay/rk3588-uart7-m1.dtbo"
    ```
    `sudo u-boot-update` после этого сам прописывает корректную `fdtoverlays` строку. При обновлении ядра путь автоматически подставится с новой версией.
  - **BT-конфликт устранён**: на Pi 5 Max UART7 архитектурно делится с BT-чипом AP6611. Служба `ap6611s-bluetooth.service` через `brcm_patchram_plus` захватывает `/dev/ttyS7`. Решение — `systemctl disable + mask` для `bluetooth.service` и `ap6611s-bluetooth.service` (BT в проекте не нужен).
  - Финальное состояние: после полного штатного ребута UART7 поднимается автоматически, `/dev/ttyS7` свободен, loopback на 420k бод чистый.
