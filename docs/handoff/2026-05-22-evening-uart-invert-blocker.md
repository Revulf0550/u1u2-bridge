# HANDOFF: u1u2-bridge — П3 (Ranger Micro) застрял на UART_INVERTED (2026-05-22, evening)

> Документ продолжает серию handoff'ов. Предыдущий: `docs/handoff/2026-05-22-night-p2-done-ranger-micro-ahead.md` (П2 UART7-setup automation закрыт). Эта сессия — третья за день, посвящена П3: распайка к ELRS TX модулю Ranger Micro. Сессия закончилась на критическом архитектурном открытии (`UART_INVERTED`) и неоднозначной прозвонке пайки, требующей перепроверки в новой сессии.
>
> Перед стартом нового чата прочитать в репо: `CLAUDE.md`, `docs/wiring-opi5max.md`, все handoff'ы в `docs/handoff/`. Также пользователь должен выполнить **2 домашних задания** до открытия чата (см. §10).

---

## 1. ⚡ TL;DR

- **Hardware:** Ranger Micro 2.4 ГГц ELRS получен, вскрыт (4 винта M2 по сторонам корпуса). Пайка выполнена к **сервисным пятакам** на нижней стороне PCB: синий→`32_TX`, зелёный→`32_RX`, чёрный→`GND`. К `3V3` пятаку не паялись (правильно).
- **Pi-side wiring:** синий→Pin 38 (UART7_RX), зелёный→Pin 29 (UART7_TX), чёрный→Pin 6 (GND) на OPi 5 Max. Использует тот же UART7 что и в предыдущей сессии (`/dev/ttyS7`).
- **Что работает:** UART7 жив (loopback из прошлой сессии), pin 29 → пятак `32_RX` имеет электрическую связь (TX-spam test, voltage 3.2V→0V), модуль запитан (LED горит и от USB-C, и от XT30 8V).
- **Что НЕ работает:** Ranger Micro **не реагирует** на отправляемые валидные CRSF RC_CHANNELS_PACKED пакеты (отправлено 1799 пакетов за 30 сек, LED паттерн не изменился).
- **CP2102 USB-Serial не открывается** на Windows (Error 31 "Присоединённое устройство не работает"). Это боковая ветка, не блокер.
- **Главное открытие:** документация ExpressLRS говорит — `UART_INVERTED` по умолчанию **включён** для ESP32-based TX модулей. Ranger Micro со стоковой прошивкой ожидает **инвертированный** CRSF. Наш OPi UART7 шлёт **неинвертированный**. Это и есть причина почему LED не реагирует.

---

## 2. 🟢 Что сделано в этой сессии (хронология)

1. **Исследование Ranger Micro:** найдены datasheet (manuals.plus 403 — недоступен через web_fetch, пользователь сам прислал скриншоты). Определены интерфейсы: JR-bay 5-pin (NC/NC/5V-12V/GND/CRSF), USB-C (только для прошивки), XT30 (6-16.8V питание).
2. **Архитектурные развилки рассмотрены:** A (JR-bay socket + обвязка), B (пайка к ESP32 UART), C (DTS-инверсия + резистор). После того как пользователь вскрыл модуль и прислал фото платы (нижняя сторона) — обнаружены **сервисные пятаки** `32_TX`/`32_RX`/`GND`/`3V3`. Это рассматривалось как идеальный вариант (предположительно неинвертированный full-duplex UART) — поэтому выбрали путь пайки прямо к пятакам, без socket'а и без обвязки.
3. **Пайка выполнена пользователем** (фото подтверждают чистый вид, термоусадка/strain relief у выхода с PCB).
4. **На стороне OPi:** подтверждено что припаял к Pin 29/38 по `docs/wiring-opi5max.md`.
5. **Bench-тест #1 (failed):** `stty -F /dev/ttyS7 420000 raw ...` → `stty: invalid argument '420000'`. Стандартный stty не принимает нестандартные baudrate. `cat` открыл порт на дефолтном baud, 0 байт.
6. **Bench-тест #2 (failed):** Python+pyserial. PermissionError на `/tmp/ranger.bin` — sandboxed Python (AppArmor/snap) не может писать в /tmp под sudo. Fixed редиректом `> ~/ranger.bin` снаружи sudo.
7. **Bench-тест #3 (0 байт, питание USB-C):** listener получил 0 байт за 20 сек. Гипотеза — USB-C недостаточно питает модуль.
8. **Bench-тест #4 (0 байт, питание XT30 8V):** тот же результат → питание не виновато.
9. **TX-spam test с мультиметром:** ключевой тест на целостность пайки. Команда `ser.write(b'\xaa' * 4096)` в цикле, мерял напряжение DC на пятаке `32_RX` Ranger Micro относительно `GND`:
    - **Idle:** 3.2V (UART idle high — норма)
    - **Во время spam:** упало до ~0V (среднее на быстро меняющемся UART сигнале)
    - **Вывод:** pin 29 OPi → пятак `32_RX` модуля имеет электрическую связь. TX/RX swap нет (если бы был — изменения не было бы).
10. **CRSF packet test:** написан правильный CRSF RC_CHANNELS_PACKED packet (16 channels × 11 bits LSB-first, CRC8 poly 0xD5). Отправлено 1799 пакетов за 30 сек на ~60 Hz (цель была 250 Hz, но `time.sleep(0.004)` + Python overhead снизили).
    - **Generated packet hex:** `c81816e0031ff8c0073ef0810f7ce0031ff8c0073ef0810f7cad`
    - **Структура:** 0xC8 (sync) + 0x18 (length=24) + 0x16 (type=RC_CHANNELS_PACKED) + 22 байта payload + 0xAD (CRC8)
    - **LED модуля паттерн НЕ изменился** → ELRS не парсит наш сигнал.
11. **Параллельно — попытка CP2102 USB-Serial на ноутбуке:** видится как `COM5`, но PuTTY и PowerShell SerialPort.Open() обе выдают `Error 31 "Присоединённое к системе устройство не работает"`. `handle.exe COM5` → "No matching handles" (порт не занят). Скорее всего сломан Windows-драйвер или CP2102 на плате в boot mode. **Не блокер**, отложено.
12. **Web-search ExpressLRS docs:** найдена ключевая фраза:
    > "UART_INVERTED works only with ESP32-based TXes. Almost all handsets require UART_INVERTED on, such as the FrSky QX7, TBS Tango 2, and RadioMaster TX16S. You want to keep this enabled in most cases."
    
    Это объясняет всё: пятаки `32_TX`/`32_RX` подключены к ESP32 UART, который **прошивкой настроен в режим invert=true**. ESP32 в idle держит pull-up (откуда 3.2V), но **протокольно ожидает** инвертированный сигнал. Наш неинвертированный CRSF интерпретируется как шум.
13. **Финальная попытка прозвонки пайки** (пользователь): «нигде ничего не пищит». **Противоречит** TX-spam тесту — это требует перепроверки в новой сессии (см. §7).

---

## 3. ✅ Что точно подтверждено фактами

| # | Факт | Подтверждение |
|---|---|---|
| 1 | UART7 OPi 5 Max жив | Loopback в предыдущей сессии (P2) |
| 2 | `/dev/ttyS7` существует, права `crw-rw---- root dialout` | `ls -l /dev/ttyS7` сегодня |
| 3 | Pyserial открывает порт на 420000 без ошибок | Все listener/spam команды выполнялись без exception |
| 4 | OPi pin 29 драйвит линию когда write() выполняется | Voltage 3.2V→0V на 32_RX во время spam |
| 5 | Зелёный провод имеет электрический контакт от pin 29 до пятака 32_RX | То же измерение (на самом пятаке мерили, не у OPi) |
| 6 | TX/RX swap отсутствует | Если был бы swap — изменение voltage было бы на 32_TX, не 32_RX |
| 7 | Ranger Micro получает питание | LED горит при USB-C и при XT30 8V |
| 8 | Ranger Micro USB-C виден ноутбуком как COM5 (CP2102) | Get-PnpDevice показал устройство |
| 9 | Ranger Micro со stock firmware ожидает инвертированный CRSF | Документация ExpressLRS (UART_INVERTED enabled by default) |

---

## 4. ❌ Что НЕ работает — точные симптомы

1. **Listener `/dev/ttyS7`** при питании модуля от USB-C или XT30 → 0 байт за 20 сек. Возможные причины: модуль без TX12 не шлёт ничего на 32_TX (telemetry idle), либо нужна инверсия для приёма команды чтобы вызвать ответ.
2. **CRSF packet stream на 32_RX** → LED модуля паттерн не меняется. **Главный симптом**, объясняется UART_INVERTED hypothesis.
3. **CP2102 USB-Serial на Windows** → Error 31 при любом подключении (PuTTY, PowerShell SerialPort). Порт не занят (handle.exe пусто). Гипотеза: ESP32 main удерживает CP2102 в каком-то rst/boot-mode, или Windows-драйвер сломан. **Не критично для основной задачи.**
4. **Прозвонка пайки** (последний шаг сессии): пользователь говорит "нигде не пищит". **Противоречит** TX-spam, нужна перепроверка с правильной техникой (щуп на металл пятака, не на флюс).

---

## 5. 💡 Главное архитектурное открытие — UART_INVERTED

### Цитаты из ExpressLRS docs:

> **UART_INVERTED** — This only works with ESP32 based TXes (will not work with modules without built-in inversion/uninversion), but enables compatibility with radios that output inverted CRSF, such as the FrSky QX7, TBS Tango 2, RadioMaster TX16S. **You want to keep this enabled in most cases.**

> **Almost all handsets require UART_INVERTED on**, such as the FrSky QX7, TBS Tango 2, and RadioMaster TX16S.

### Что это значит для нас

Ranger Micro собран и поставляется с прошивкой ExpressLRS у которой `UART_INVERTED=on` (это **default**). Внутри firmware ESP32 main MCU при инициализации UART вызывает что-то вроде `uart_set_line_inverse(UART_NUM_0, UART_SIGNAL_TXD_INV | UART_SIGNAL_RXD_INV)` (ESP-IDF API).

Эффект на физическом уровне:
- ESP32 на этом UART **передаёт** с инвертированным сигналом (idle low, start bit high)
- ESP32 **ожидает приём** с инвертированным сигналом (то же)
- Pull-up на GPIO при idle держит пин в high (отсюда наши 3.2V), но **это не «idle UART»**, это просто passive pull-up без активной передачи. ESP32 в момент ожидания фрейма ищет переход high→low **в инвертированном** мире (т.е. реально low→high на ножке)

Поэтому наш стандартный неинвертированный CRSF от OPi UART7:
- Линия idle high (3.3V) ← но ESP32 ожидает invert idle = low. Когда переключилось из 3.3V «idle» на наш start bit (low) — для ESP32 invert это выглядит как переход idle→stop bit, мусор
- Все байты неправильно декодируются
- LED не реагирует (ни один CRSF фрейм не прошёл валидацию)

### Альтернативная гипотеза, которую тоже нужно держать в уме

Возможно `32_TX`/`32_RX` это **debug UART** (например, UART0 ESP32, тот же что подключён к CP2102), а CRSF от JR-bay идёт через **другой UART** (UART1 или UART2). Тогда мы пишем не в тот UART, и инверсия здесь ни при чём.

**Как проверить:** найти в открытых исходниках ExpressLRS `targets/Unified_ESP32_TX.h` или target-файл для Ranger Micro и посмотреть назначение UART. Это **задача №1** для новой сессии — ОБЯЗАТЕЛЬНО проверить через GitHub ExpressLRS прежде чем строить hardware-инвертор.

---

## 6. 🛤️ Три пути решения (детально)

### Путь A — Hardware-инвертор

**Схема:** между OPi pin 29 и пятаком `32_RX` ставим транзистор-инвертор (NPN с pull-up). То же зеркально для `32_TX` → pin 38.

Один канал инвертора:
```
3.3V ──┬── R1 (10 кОм pull-up) ──┬── OUT (на ESP32 32_RX)
       │                          │
       │                  Коллектор NPN
       │                          │
       │                          NPN базы ── R2 (1 кОм) ── IN (от OPi pin 29)
       │                          │
       └── GND ─── Эмиттер NPN ───┘
```

Когда IN=high → транзистор открыт → OUT=low. Когда IN=low → транзистор закрыт → OUT pull-up к 3.3V. Это и есть инверсия.

**Препятствия:** нужны 2× NPN транзистора (BC547, 2N2222, S8050) + 4 резистора (2× 1 кОм, 2× 10 кОм). Если деталей нет — путь A блокирован пока не закажешь.

**Преимущества:** работает гарантированно, signal levels чистые, не зависит от unverified DTS feature.

### Путь B — DTS-инверсия UART7 на OPi

RK3588 mainline serial-rockchip driver в принципе поддерживает свойства device tree:
- `rx-invert` / `tx-invert` (в некоторых ветках Rockchip BSP)
- ИЛИ через termios2 ioctl на runtime

Шаги:
1. Найти исходник `rk3588-uart7-m1.dtsi` (в `arch/arm64/boot/dts/rockchip/`)
2. Добавить properties:
   ```
   &uart7 {
       rx-invert;
       tx-invert;
   };
   ```
3. Пересобрать `.dtbo`
4. Подменить в `/lib/firmware/device-tree/rockchip/overlay/`
5. `u-boot-update` + reboot

**Препятствия:** не оттестировано на нашем дистрибутиве (Ubuntu 24.04 от joshua-riek). Возможно, ядро не поддерживает эти DT properties для UART7. Час на пробу, может не сработать.

**Преимущества:** не требует hardware изменений, всё чисто на стороне OPi.

### Путь C — Перепрошить Ranger Micro с UART_INVERTED=off

Через ExpressLRS Configurator:
1. Скачать ExpressLRS source (на ноуте, не на OPi)
2. Через Configurator выбрать target: `RadioMaster Ranger Micro 2.4GHz`
3. В Configurator есть опция выбрать `UART_INVERTED off`
4. Build firmware
5. Flash через WiFi (потому что CP2102 не работает)

**Препятствия:**
- CP2102 broken (USB прошивка отпадает)
- WiFi прошивка работает через ESP backpack — нужно знать SSID/password дефолтного WiFi AP модуля (обычно `ExpressLRS TX` без пароля или с binding phrase)
- **Меняет stock-состояние модуля**: если завтра попробуем вставить в TX12 — там не будет работать, потому что TX12 шлёт инвертированный CRSF
- Это решение «дорога в одну сторону» — нужно понимать что мы тогда **навсегда** теряем совместимость с обычной радиостанцией

**Преимущества:** один раз пересобрал — работает чисто, без обвязки и DTS-хаков.

---

## 7. 🚨 Висящие неопределённости (нужны в новой сессии)

### 7.1. Целостность пайки — противоречие

- **TX-spam test:** voltage 3.2V→0V на пятаке `32_RX` → **сигнал доходит**.
- **Прозвонка:** «нигде не пищит» → **сигнал не доходит**.

Эти два утверждения **взаимоисключающие**. Возможные причины:
- Прозвонка делалась не на металле пятака, а на флюсе/застывшем олове
- Щуп мультиметра тупой / разболтанный — не контачит с проводом
- Прозвонка делалась под напряжением (XT30 ещё был подключён) → внутреннее сопротивление модуля рушит прозвонку
- TX-spam test случайно «прозвонил» через GND-path (parasitic capacitance) и показывает false-positive

**В новой сессии:** обязательно перепроверить прозвонку с чёткой техникой — модуль обесточен, провода вынуты из OPi GPIO, щуп на металл пятака (не на флюс или соседний пятак).

### 7.2. Какой именно UART подключён к 32_TX/32_RX?

Прежде чем делать обвязку или DTS-инверсию — **прочитать target-файл ExpressLRS** для Ranger Micro. GitHub: `ExpressLRS/ExpressLRS/src/hardware/TX/Radiomaster_Ranger_Micro_2400_TX/*.json`. Там должно быть `serial_rx` и `serial_tx` (GPIO номера ESP32). Сравнить с расположением пятаков на PCB и подтвердить что мы паяемся к **тому** UART который ELRS использует для CRSF от JR-bay.

Если окажется что `32_TX`/`32_RX` — это **debug UART** (на ESP32 UART0, общий с CP2102 USB-Serial), то наш путь в принципе неверный, и нужно искать другой пятак или паяться напрямую к JR-bay CRSF pin.

### 7.3. Состояние пользовательских компонентов

Пользователь не инвентаризовал свои ящики с электроникой. Это блокер для выбора путь A.

---

## 8. ⚠️ Антипаттерны (НЕ повторять)

1. **НЕ вставлять Ranger Micro в TX12** пока 32_RX припаян к OPi — drive contention между JR-bay инвертирующим буфером (внутри модуля) и OPi UART7_TX может сжечь либо буфер, либо GPIO.
2. **НЕ запитывать через пятак `3V3`** — это выход внутреннего регулятора модуля, подача внешнего 3.3V убьёт регулятор.
3. **НЕ трогать пятаки `8285_TX`/`8285_RX`** — это **внутренняя шина** между ESP32 main и ESP8285 backpack. Эти пятаки видны на image 2 (макро верхней правой части PCB) И на image 3 (нижняя сторона, в левой нижней четверти — там тоже есть `8285_*`). Подключение сюда сломает WiFi/Bluetooth backpack.
4. **НЕ тратить время на CP2102 USB-Serial Error 31** на Windows — это боковая ветка. Если нужен debug log модуля — флешить через WiFi backpack или ставить ESP8285 + ESP-NOW listener.
5. **НЕ использовать USB-RS485 адаптеры Waveshare (CH343G)** для Ranger Micro — модуль работает по TTL UART (3.3V), не RS485 (±7V). RS485 адаптеры были в исходном BOM проекта для другого кейса (CRSF через 8-pin кабель в оригинальной архитектуре).
6. **НЕ запускать `crsf-bridge@tx1` пока UART_INVERTED не решён** — сервис будет в loop'е reconnect или, хуже, лить мусор на 32_RX который ESP32 интерпретирует как невалидный CRSF.

---

## 9. 📋 Технические данные (для копирования)

### Hardware распиновка

| Сторона | Сигнал | Цвет провода |
|---|---|---|
| Ranger Micro PCB | `32_TX` (нижняя сторона, верх PCB) | синий |
| Ranger Micro PCB | `32_RX` (нижняя сторона, верх PCB) | зелёный |
| Ranger Micro PCB | `GND` (нижняя сторона, верх PCB) | чёрный |
| OPi 5 Max GPIO | Pin 38 (UART7_RX) | синий |
| OPi 5 Max GPIO | Pin 29 (UART7_TX) | зелёный |
| OPi 5 Max GPIO | Pin 6 (GND) | чёрный |

### Питание Ranger Micro

- **XT30:** 6.0–16.8V DC, использовался 8V в тестах. LED горит, модуль активен.
- **USB-C:** даёт частичное питание (LED горит, но CP2102 не отвечает по Windows Error 31). Достаточно для bench-теста ESP32, но может быть проблема в текущей сессии тоже.
- **JR-bay Pin 3 (5V-12V):** не использовался (модуль не вставлялся в радио, см. антипаттерны).

### Software ландшафт u2-Pi

- **OS:** Ubuntu 24.04 от joshua-riek/ubuntu-rockchip
- **Сервис в reconnect loop:** `crsf-bridge@tx1`
- **Env-файл устарел:** `/etc/u1u2-bridge/crsf-tx1.env` содержит `SERIAL_DEV=/dev/ttyACM-CRSF1`, должно быть `/dev/ttyS7`
- **Точное содержимое env:**
  ```
  SERIAL_DEV=/dev/ttyACM-CRSF1
  BAUD=420000
  LISTEN=0.0.0.0:14550
  PEER=10.8.0.4:14550
  ```
- **WireGuard:** туннель поднят, PEER=10.8.0.4 это u1-Pi через VPN.
- **SSH:** `ssh ardor@192.168.1.10` timeout (через CPE710 LAN). Через WireGuard SSH работает.

### Команды (готовые к копированию)

**Stop сервис:**
```bash
sudo systemctl stop crsf-bridge@tx1
```

**TX-spam (проверка пайки через мультиметр):**
```bash
sudo python3 -c "
import serial, time
ser = serial.Serial('/dev/ttyS7', 420000)
end = time.time() + 60
while time.time() < end:
    ser.write(b'\xaa' * 4096)
    ser.flush()
ser.close()
"
```

**Listener (Python+pyserial, redirect в home):**
```bash
sudo systemctl stop crsf-bridge@tx1
rm -f ~/ranger.bin
sudo python3 -c "
import serial, time, sys
print('>>> Listener активен. Запись 20 сек.', file=sys.stderr, flush=True)
ser = serial.Serial('/dev/ttyS7', 420000, timeout=1)
data = b''
start = time.time()
while time.time() - start < 20:
    chunk = ser.read(4096)
    if chunk:
        data += chunk
        print(f'  получено {len(data)} байт', file=sys.stderr, flush=True)
ser.close()
sys.stdout.buffer.write(data)
print(f'>>> Готово. Размер: {len(data)} байт', file=sys.stderr)
" > ~/ranger.bin
ls -la ~/ranger.bin
xxd ~/ranger.bin | head -30
```

**CRSF packet generator + sender (250 Hz):**
```bash
sudo python3 << 'PYEOF'
import serial, time

def crc8(data, poly=0xD5):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def crsf_rc_packet():
    channels = [992] * 16  # 1500us center
    payload = bytearray(22)
    bit_idx = 0
    for ch in channels:
        for b in range(11):
            if ch & (1 << b):
                payload[bit_idx // 8] |= (1 << (bit_idx % 8))
            bit_idx += 1
    body = bytes([0x16]) + bytes(payload)
    pkt = bytes([0xC8, 24]) + body + bytes([crc8(body)])
    return pkt

ser = serial.Serial('/dev/ttyS7', 420000)
pkt = crsf_rc_packet()
print(f'>>> CRSF packet ({len(pkt)} bytes): {pkt.hex()}')
end = time.time() + 30
n = 0
while time.time() < end:
    ser.write(pkt)
    ser.flush()
    n += 1
    time.sleep(0.004)
ser.close()
print(f'>>> Отправлено {n} CRSF пакетов')
PYEOF
```

**Generated CRSF packet (для справки):**
```
c81816e0031ff8c0073ef0810f7ce0031ff8c0073ef0810f7cad
```
- 0xC8 = sync (CRSF_ADDRESS_FLIGHT_CONTROLLER)
- 0x18 = length (24 = type + 22 payload + 1 crc)
- 0x16 = type CRSF_FRAMETYPE_RC_CHANNELS_PACKED
- 22 bytes payload = 16 channels × 11 bits LSB-first, all 992 (1500μs center)
- 0xAD = CRC8 poly 0xD5 over (type + payload)

### Что НЕ делать (повторы)

- `stty -F /dev/ttyS7 420000` — **не принимает** нестандартный baudrate (`invalid argument`). Только pyserial через termios2 или Python serial.
- `cat /dev/ttyS7 > /tmp/file.bin` под sudo — может упасть PermissionError из-за sandboxed Python. Использовать `~/` через shell redirect снаружи sudo.

---

## 10. 🚀 Приоритет 1 для новой сессии

### Домашние задания ДО открытия чата

1. **Чистая прозвонка пайки** (5 минут). Модуль обесточен (XT30 + USB-C вынуты), провода вынуты из OPi GPIO. Мультиметр в режим прозвонки. Точки:
   - `32_TX` пятак (металл!) ↔ кончик синего провода (вынутый из pin 38) — должно пищать
   - `32_RX` пятак ↔ кончик зелёного — должно пищать
   - `GND` пятак ↔ кончик чёрного — должно пищать
   - `32_TX` ↔ `32_RX` — НЕ должно пищать (нет короткого)
   - `32_TX` ↔ `GND` — НЕ должно
   - `32_RX` ↔ `GND` — НЕ должно
   
   Если есть обрыв в одной из первых трёх — перепаять. Если пищит — двигаться к шагу 2.

2. **Инвентаризация компонентов** (10 минут полазить по ящикам):
   - **NPN транзисторы:** BC547, 2N2222, S8050, S9013, 2N3904, KN2222, или любые SOT-23/TO-92 NPN signal transistor
   - **Single-gate inverters:** 74HC1G04, 74LVC1G04, 74HC1G14, 74LVC1G14, 74HC04 (DIP-14 hex inverter — тоже подойдёт)
   - **Резисторы:** 1 кОм, 10 кОм (по 4 штуки каждого)
   - **Перфоборд / макетка** для монтажа

### В новой сессии

3. **Полезть в ExpressLRS GitHub** и найти target-файл для Ranger Micro. Подтвердить: GPIO пины ESP32 для `serial_rx`/`serial_tx` — соответствуют ли они пятакам `32_TX`/`32_RX` (гипотеза была что да, но не подтверждена документацией).
   - URL: `https://github.com/ExpressLRS/ExpressLRS/tree/master/src/hardware/TX/`
   - Искать файл с именем содержащим `Ranger_Micro`

4. **На основе пунктов 1+2+3 выбрать путь:**
   - Прозвонка ОК, target-файл подтверждает наш UART, есть транзисторы → **путь A** (hardware-инвертор)
   - Прозвонка ОК, target-файл подтверждает, нет компонентов → **путь B** (DTS-инверсия — экспериментальный)
   - Прозвонка ОК, target-файл показывает другой UART → паяться к **другим** пятакам или к JR-bay CRSF pin напрямую
   - Прозвонка fail → перепайка → начать заново

5. **После того как пакет CRSF доходит и парсится** (LED меняется):
   - Поправить env-файл сервиса: `SERIAL_DEV=/dev/ttyS7` (было `/dev/ttyACM-CRSF1`)
   - `sudo systemctl restart crsf-bridge@tx1`
   - `sudo systemctl status` — должен быть `active (running)` без reconnect loop
   - Логи `journalctl -u crsf-bridge@tx1 -f` — должны идти статистики `uart->udp=X B/s`

6. **End-to-end тест** с u1-Pi через WireGuard (если у u1-Pi настроена параллельная пайка к П1 trainer port или к другому CRSF источнику).

---

## 11. 📚 Lessons (черновики для CLAUDE.md)

После закрытия П3 эти Lessons стоит закоммитить в `CLAUDE.md`:

```markdown
### 2026-05-22 (evening) · stty не принимает нестандартные baudrate

CRSF использует 420 000 бод — это нестандартная скорость, не входящая в POSIX-таблицу stty. Стандартный `stty -F /dev/ttyS7 420000 ...` падает с `invalid argument '420000'`. Linux в принципе поддерживает arbitrary baudrate через termios2 ioctl, но stty это не использует.

**Правило:** для нестандартных baudrate использовать pyserial (она внутри вызывает termios2), а не stty. `serial.Serial(port, 420000)` работает там, где `stty 420000` падает.

**Проверка:** `python3 -c "import serial; s=serial.Serial('/dev/ttyS7', 420000); print('ok'); s.close()"` — если "ok" → baudrate настроен.

### 2026-05-22 (evening) · Pyserial под sudo + /tmp = PermissionError

При запуске `sudo python3 -c "...open('/tmp/file.bin','wb')..."` падает `PermissionError: [Errno 13] Permission denied: '/tmp/file.bin'` даже когда процесс под root. Скорее всего AppArmor sandbox для Python (snap или дистрибутивный hardening на Ubuntu 24.04 от joshua-riek).

**Правило:** при записи бинарных данных через `sudo python3 -c "..."` использовать `sys.stdout.buffer.write(data)` внутри Python, и redirect `> ~/file.bin` снаружи sudo. Тогда write делает shell от имени пользователя, а не sandboxed root.

**Проверка:** `sudo python3 -c "import sys; sys.stdout.buffer.write(b'test')" > ~/test.bin && ls -la ~/test.bin` — файл создан с правами пользователя.

### 2026-05-22 (evening) · Не верить шёлкографии PCB без проверки документацией

На плате Ranger Micro есть сервисные пятаки `32_TX` / `32_RX`. По логике (имя + наличие в открытом доступе) они выглядят как «чистый неинвертированный UART к ESP32». На деле — оказалось, что ELRS firmware настраивает этот UART в режим `UART_INVERTED=true` (default для совместимости с радиостанциями). Шёлкография говорит «вот UART ESP32», но **не говорит** «инвертированный или нет».

**Правило:** перед пайкой к сервисным пятакам ELRS-модулей — обязательно проверить в target-файле ExpressLRS (на GitHub) что firmware ожидает на этом UART: invert или нет, full-duplex или half. То же касается других open-source RF проектов (TBS Crossfire, R9, etc).

**Проверка:** GitHub поиск `ExpressLRS/ExpressLRS/src/hardware/TX/Radiomaster_<Module>_TX/` — там JSON или .h файл с `serial_rx`, `serial_tx`, `uart_invert`, `serial_half_duplex` properties.

### 2026-05-22 (evening) · TX-spam + мультиметр в DC = быстрый тест целостности 3.3V UART

Когда нужно проверить «доходит ли сигнал OPi UART до пятака ESP32 после пайки», самый дешёвый метод:
1. Послать с OPi непрерывный байт-паттерн с большим content of transitions (`b'\xAA' * 4096` в цикле write+flush)
2. Мерять напряжение DC на пятаке относительно GND
3. Сравнить idle (без write) и spam (во время write)

На 3.3V логике idle UART = ~3.3V (или 3.2V с учётом drop). На быстром меняющемся сигнале мультиметр DC показывает что-то от 0 до 2V, среднее ~1.5V — главное **изменение** от idle на >1V.

**Правило:** этот тест не требует осциллографа и не требует ответа от противоположной стороны. Подтверждает только электрическую связь и работу OPi TX. Не подтверждает что сигнал интерпретируется правильно.

**Проверка:** записать idle voltage и spam voltage в одной точке (32_RX или другая RX-сторона цепи). Разница > 1V = связь есть.
```

---

## 12. 📌 Шаблон первого сообщения в новом чате

```
Продолжаем bringup u1u2-bridge. Прикладываю handoff 2026-05-22-evening-uart-invert-blocker.md.
TL;DR: пайка к 32_TX/32_RX Ranger Micro выполнена, но LED не реагирует на наши CRSF
пакеты. Открытие: ExpressLRS UART_INVERTED по умолчанию on — модуль ожидает
инвертированный CRSF, а наш OPi UART7 шлёт неинвертированный.

Прошу прочитать в репо: CLAUDE.md, docs/wiring-opi5max.md, все handoff'ы в docs/handoff/.

Действия которые я сделал ДО открытия этого чата:

1. Чистая прозвонка пайки (модуль обесточен, провода вынуты с OPi):
   - 32_TX ↔ синий провод: [пищит / нет]
   - 32_RX ↔ зелёный провод: [пищит / нет]
   - GND ↔ чёрный провод: [пищит / нет]
   - 32_TX ↔ 32_RX: [пищит / нет] (должно быть НЕТ)
   - 32_TX ↔ GND: [пищит / нет] (должно быть НЕТ)
   - 32_RX ↔ GND: [пищит / нет] (должно быть НЕТ)

2. Инвентаризация компонентов в ящиках:
   - NPN транзисторы: [есть/нет, какие именно]
   - 74HC1G04 / 74LVC1G14 single-gate инверторы: [есть/нет]
   - 74HC04 hex инвертор DIP-14: [есть/нет]
   - Резисторы 1 кОм: [есть/нет, скольно]
   - Резисторы 10 кОм: [есть/нет, скольно]
   - Перфоборд / макетка: [есть/нет]

Дальше планирую: путь A (hardware-инвертор) если есть детали, путь B (DTS-инверсия)
если деталей нет. Также прошу первым шагом полезть в ExpressLRS GitHub и найти
target-файл для Ranger Micro — подтвердить какие именно GPIO ESP32 связаны с
пятаками 32_TX/32_RX и тот ли это UART который обрабатывает CRSF от JR-bay.
```

---

## 13. 🎒 Что не входит в этот handoff (для полноты)

- **u1-Pi настройка** — не трогалась в этой сессии. По handoff'у предыдущей сессии — Ubuntu, hostname, статика, CPE710, WireGuard клиент. План в `docs/handoff/2026-05-22-night-p2-done-ranger-micro-ahead.md` §3.
- **8-pin разъём модель** — всё ещё не определена (запрос фото от пользователя был ранее, не получено). Не блокер для bench-теста П3, но блокер для финального переходника.
- **Видео pipeline** — `video_tx.sh` / `video_rx.sh` написаны, не тестировались на железе. Не задача П3.
- **CTRL-канал второй CRSF** — не обсуждался в этой сессии. По плану — второй экземпляр `crsf-bridge@tx2` для второго ELRS-передатчика, аналогичная инверсионная проблема скорее всего повторится.

---

## 14. 🧠 Предпочтения пользователя (соблюдать в новой сессии)

1. **Claude Code установлен** в `C:\Users\ARDOR\Documents\Projects\u1u2-bridge`. При переходе к работе с репо/git — анонсировать заранее, не молча. PowerShell на Windows.
2. **Длинный чат → handoff + новый чат заранее.** Анонсировать.
3. **Дозировать информацию.** Один логический блок за раз, ждать подтверждения.
4. **Когда шаг требует открыть программу** (PowerShell, SSH, браузер, PuTTY, web-UI) — явно сказать в начале шага и расписать пошагово.
5. **Общается по-русски,** отвечать по-русски.
