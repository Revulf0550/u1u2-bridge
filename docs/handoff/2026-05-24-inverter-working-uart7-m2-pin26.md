# HANDOFF — 2026-05-24 — Инвертор работает + UART7-M2 на pin 26 найден

> Продолжение из чата ранее в этот день. Предыдущий handoff: `2026-05-23-evening-inverter-built-ufw-lesson.md`. В том чате инвертор был спаян, но smoke-тест НЕ проводился, WireGuard упал.

---

## Главное в этом чате

1. Smoke-тест провалился (Тест 2A показал 3.3V вместо 0.1–0.3V).
2. Долгая диагностика, нашли **холодную пайку коллектора** ([C] ↔ левая ножка BC547 = OL).
3. Параллельно выяснилось, что транзистор был запасной — `BC548 B 166` (NXP), а не BC547. Пользователь перепаял заново, поставив новый BC548 B в **правильной стандартной ориентации** (плоская сторона С НАДПИСЬЮ вверх, видна).
4. **Все тесты инвертора прошли**: continuity, DC inversion (HIGH→0.003V, LOW→2.9V), UART stream.
5. **UART7-M1 overlay в системе оказался от Radxa Rock 5B, а не от OPi 5 Max** — `/dev/ttyS7` работал в kernel, но pinmux физически не выводился на header. Подтверждено через `gpioinfo gpiochip3` (все линии `unused`).
6. **Решение**: заменили overlay на `rk3588-uart7-m2.dtbo`. Теперь UART7 TX выводится на **header pin 26 (GPIO1_B5)**.
7. UART stream-тест: на [B] получили **1.6 V** (среднее меандра 0–3.3V) → вся цепь Pi → инвертор → ESP32 работает.

**Финальный CRSF 420k smoke-test НЕ проводился** — это priority 1 для нового чата.

---

## Финальная актуальная схема

### 6 проводов в системе

| # | Цвет | OPi pin | Куда |
|---|------|---------|------|
| 1 | синий | **pin 1** (3.3V) | [A] на плате |
| 2 | зелёный | **pin 26** (GPIO1_B5 = UART7 TX M2) | [B] на плате |
| 3 | чёрный короткий | pin 6 (GND) | [D] на плате |
| 4 | белый | (с [C] на плате) | модуль pin 5 (CRSF input) |
| 5 | красный | pin 2 (5V) | модуль pin 3 (мимо платы) |
| 6 | чёрный длинный | pin 6 (GND) | модуль pin 4 (мимо платы) |

### BC548 B ориентация (актуально)

- Плоская сторона **с надписью** `BC548 B 166` смотрит **ВВЕРХ** (на читателя), видна с верхнего вида.
- Распиновка стандартная **C-B-E** слева направо.
- Левая ножка (C) → точка **[C]**, средняя (B) → точка **(·)**, правая (E) → точка **[D]**.

### Компоненты на плате

- **R1 = 2.2 kΩ** (base resistor, между точкой [B] и базой BC548).
- **R2 = 4.7 kΩ** (collector pull-up, между точкой [A] и точкой [C]).
- **BC548 B** (NXP, NPN, hFE 200–450).
- 5 точек пайки: `[A]`, `[B]`, `[C]`, `(·)`, `[D]`.

### Системные изменения

- `/boot/extlinux/extlinux.conf`: overlay изменён с `rk3588-uart7-m1.dtbo` на `rk3588-uart7-m2.dtbo`.
- Бэкап старого конфига: `/boot/extlinux/extlinux.conf.bak`.
- `/dev/ttyS7` теперь физически выводит на pin 26 (вместо невыведенного M1).

---

## Результаты всех тестов (для отчётности)

| Тест | Замер | Результат | Норма |
|---|---|---|---|
| Continuity 1.1 | [C] ↔ левая ножка | beep | beep |
| Continuity 1.2 | [D] ↔ правая ножка | beep | beep |
| Continuity 1.3 | [A] ↔ верх R2 | beep | beep |
| Continuity 1.4 | [B] ↔ верх R1 | beep | beep |
| R1 | [B] ↔ база | 2.1 kΩ | ~2.2 kΩ |
| DC 2A (HIGH base) | [C] vs [D] | **0.003 V** | 0.1–0.3V |
| DC 2B (LOW base) | [C] vs [D] | **2.9 V** | ~3.3V* |
| UART stream | [B] vs [D] | **1.6 V** | ~1.65V |

\* 2.9V вместо 3.3V — нормально, модуль ELRS тянет [C] вниз через CRSF-input pull-up.

---

## Lessons learned (для CLAUDE.md `## Lessons & Incidents`)

### Lesson A — Прозвонка пайки прежде гипотез о компонентах

После первой неудачи Теста 2A (3.3V вместо 0.1–0.3V) я (Claude как диагност) выдвинул гипотезу о «перевёрнутой распиновке BC547» и попросил выпаять и перевернуть транзистор. На самом деле причина была в холодной пайке коллектора. Стоило это ~1 час лишней работы и одну перепайку транзистора.

**Правило**: при отладке самодельной платы первый шаг после failed теста — **continuity-прозвонка всех пайок** (мультиметр в режиме beep, поочерёдно касаемся пятак ↔ ножка для каждого компонента). До любых гипотез о компонентах. Это 2 минуты работы и исключает 80% типичных проблем.

**Проверка**: при появлении нового симптома на плате задавать себе вопрос — «прозвонил ли я все пайки?» Если нет — сначала прозвонка.

### Lesson B — BC547 / BC548 / BC549 — стандартная распиновка C-B-E

Серия BC54x от NXP/Philips имеет стандартную распиновку **C-B-E** (если смотреть на плоскую сторону С маркировкой, ножки вниз: слева C, посередине B, справа E). Это отличает их от 2N3904, S8050, C8050 (E-B-C).

**Правило**: при использовании транзистора в TO-92 сначала проверить точную маркировку. BC54x → C-B-E, 2N3904 → E-B-C. Не предполагать обратной распиновки без datasheet.

**Проверка**: маркировка `BC548 B 166` или `BC547 B 166` (где B — hFE group, 166 — date code) подтверждает оригинальный NXP с C-B-E pinout.

### Lesson C — Device tree overlay может быть НЕ для твоей платы

В Joshua-Riek образе для OPi 5 Max использовался overlay `rk3588-uart7-m1.dtbo`, в котором `compatible = "radxa,rock-5b"` и `description = "...On Radxa ROCK 5B this is RX pin 11 and TX pin 15"`. То есть он включал UART7-M1 на GPIO3_C0/C1, которые на header OPi 5 Max **не выведены** (только Rock 5B их выводит). Драйвер `/dev/ttyS7` загружается, но физически TX никуда не выходит.

**Правило**: при настройке UART (или другой периферии) через overlay на не-RPi плате — проверять что overlay написан именно для этой платы. Команда `dtc -I dtb -O dts /path/to/overlay.dtbo | head -10` показывает `compatible` и `description`.

**Проверка через gpioinfo**: `sudo gpioinfo gpiochip<N>` показывает claimed lines. Если линии под предполагаемый UART значатся `unused` — overlay не сработал.

**Решение для OPi 5 Max**: использовать `rk3588-uart7-m2.dtbo` (GPIO1_B5 = pin 26 на header).

### Lesson D — Симметрия pinout OPi 5 Max ≈ OPi 5 Plus

OPi 5 Max и OPi 5 Plus имеют близкий (возможно идентичный) 40-pin header pinout. По pinout-картинке OPi 5 Plus:
- **UART7_TX_M2 → pin 26 (GPIO1_B5)**
- **UART7_RX_M2 → pin 24 (GPIO1_B4)**
- **UART6_TX_M1 → pin 8 (GPIO1_A1)**, UART6_RX_M1 → pin 10 (GPIO1_A0)
- **UART4_TX_M2 → pin 21/23 (GPIO1_B1/B3)**, UART4_RX_M2 → pin 19 (GPIO1_B2)
- **UART3_TX_M1 → pin 16 (GPIO3_B5)**, UART3_RX_M1 → pin 18 (GPIO3_B6)
- **UART1_TX_M1, UART1_RX_M1** — в районе pins 27/28.

На OPi 5 Max подтверждено эмпирически: UART7-M2 TX на pin 26 действительно работает (1.6V meander).

---

## Сетевые координаты (без изменений)

| Узел | WG IP | Local IP | Hostname |
|---|---|---|---|
| u2-pi | `10.8.0.7` | `192.168.31.100` | u2-pi |
| u1-pi | `10.8.0.6` | неизвестен | u1-pi |
| ноут | `10.8.0.5` | `192.168.31.150` | — |

WireGuard подсеть: `10.8.0.0/24`. **Сейчас всё ещё упал** — диагностика отложена со вчерашней сессии.

UFW на u2-pi: SSH 22 открыт из `10.8.0.5/32` (WG) и `192.168.31.0/24` (LAN-fallback, добавлено 2026-05-23).

---

## State в конце сессии

- ✅ **Инвертор полностью собран и работает**: BC548 B + R1=2.2k + R2=4.7k на перфоплате, все пайки чистые.
- ✅ **Continuity** все 4 пары пайки целые (beep).
- ✅ **DC inversion** работает в обе стороны (HIGH→0.003V, LOW→2.9V).
- ✅ **UART7-M2 stream-тест** прошёл: 1.6V на [B] при стриме 0x55 на /dev/ttyS7 (115200 бод).
- ✅ **Зелёный провод** закреплён на OPi pin 26 (GPIO1_B5).
- ✅ **extlinux.conf** содержит `rk3588-uart7-m2.dtbo` (бэкап старого в `.bak`).
- ⏳ **CRSF 420k smoke-test НЕ проводился** — главное недоделанное.
- ⏳ **WireGuard на u2-pi всё ещё упал** — диагностика отложена.

---

## Следующие шаги (priority order)

### Priority 1 — Финальный CRSF 420k smoke-test ⭐

Это главная задача нового чата. Запустить CRSF RC-стрим на 420000 бод через /dev/ttyS7 (теперь физически на pin 26), параллельно сканировать WiFi с телефона.

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
    channels = [992] * 16
    payload = bytearray(22)
    bit_idx = 0
    for ch in channels:
        for b in range(11):
            if ch & (1 << b):
                payload[bit_idx // 8] |= (1 << (bit_idx % 8))
            bit_idx += 1
    body = bytes([0x16]) + bytes(payload)
    return bytes([0xC8, 24]) + body + bytes([crc8(body)])
ser = serial.Serial('/dev/ttyS7', 420000)
pkt = crsf_rc_packet()
print(f'>>> Sending CRSF, hex={pkt.hex()}')
n = 0
start = time.time()
try:
    while True:
        ser.write(pkt)
        ser.flush()
        n += 1
        time.sleep(0.004)
        if n % 500 == 0:
            print(f'>>> {n} packets, {n/(time.time()-start):.0f} Hz', flush=True)
except KeyboardInterrupt:
    print(f'\n>>> Stopped after {n} packets')
finally:
    ser.close()
PYEOF
```

**Ожидание 60+ секунд при сканировании WiFi:**
- WiFi сеть `ExpressLRS TX` **НЕ появляется** → 🎉 ESP32 получил валидный CRSF, инверсия работает на 420k. Идём к интеграции и telemetry.
- WiFi `ExpressLRS TX` **появляется** → ESP32 не получил CRSF, перешёл в config mode. Возможно BC548 storage time не успевает на 420k. План Б — `74HC04` hex inverter IC (заказать) или увеличить R1 до 4.7k.

### Priority 2 — Диагностика WireGuard на u2-pi

```bash
sudo systemctl status wg-quick@wg0
sudo wg show
sudo journalctl -u wg-quick@wg0 -n 50 --no-pager
ip addr show wg0
```

Возможные причины: изменился внешний IP WG-сервера, DNS, истекли ключи, network change на u2.

### Priority 3 — Документация в репозитории (через Claude Code)

⚠️ **Переключиться в Claude Code** — это правки файлов в git-репозитории, ровно его профиль работы. В Claude Chat теряем git-историю и diff-контроль.

Через Claude Code:
1. Создать ветку `docs/inverter-and-pinout`.
2. Создать `docs/inverter-schematic.md` с финальной схемой:
   - Перфоплата (5 точек пайки)
   - BC548 B в правильной ориентации (C-B-E, надпись вверх)
   - 6 проводов в системе (таблица из этого handoff'а)
   - Конкретные pin numbers OPi 5 Max: pin 1 (3.3V), pin 2 (5V), pin 6 (GND), pin 26 (UART7 TX M2)
   - BOM
3. Опционально сохранить картинку pinout как `docs/orangepi-5-max-pinout.png` (та, что прислали с надписью `Orange pi 5 Max V1.0`).
4. Прогнать `verify.ps1` (если затрагивались Python-файлы — но тут чисто docs, так что не критично).
5. Закоммитить → PR / merge.

### Priority 4 — Обновить CLAUDE.md (через Claude Code)

⚠️ **Тот же переход в Claude Code** — это правка `CLAUDE.md` в репозитории.

Добавить 4 lessons learned (A, B, C, D) из этого handoff'а в раздел `## Lessons & Incidents` (новые записи сверху, по формату из CLAUDE.md). Особенно lesson A (прозвонка пайки прежде гипотез) — она применима ко всем будущим разборкам железа, не только к этому проекту.

Заодно обновить раздел `## Architecture` → `### Hardware и периферия` — там сейчас написано про UART через адаптеры USB-RS485 (Waveshare CH343G), а реальная конфигурация для CRSF теперь другая: встроенный UART7-M2 на pin 26 + hardware BC548-инвертор. Добавить ссылку на `docs/inverter-schematic.md`.

### Priority 5 — Telemetry (UART RX)

Сейчас закреплён только TX (pin 26). Для CRSF telemetry от ELRS обратно к Pi нужен RX:
- **UART7-M2 RX = GPIO1_B4 = предположительно pin 24** на OPi 5 Max (по аналогии с 5 Plus).
- Подтвердить эмпирически (после Priority 1).

---

## Открытые вопросы

- ❓ **Финальный CRSF 420k smoke-test не сделан** — основной вопрос для нового чата.
- ❓ **BC548 storage time на 420k** — теоретически marginal (40% bit time), на практике проверим только в Priority 1.
- ❓ **Действительно ли pin 24 на OPi 5 Max = UART7 RX M2** (для telemetry) — не подтверждено эмпирически.
- ❓ **WireGuard на u2-pi** — упал, причина неизвестна.
- ❓ **u1-pi local IP** в `192.168.31.x` — узнать через роутер 192.168.31.1.

---

## Файлы для нового чата

Скинь:
1. **Этот handoff** (`2026-05-24-inverter-working-uart7-m2-pin26.md`)
2. **Предыдущие два handoff'а**:
   - `2026-05-22-late-night-firmware-master.md`
   - `2026-05-23-evening-inverter-built-ufw-lesson.md`
3. **CLAUDE.md** из репозитория (в проекте, не загружать руками)

Формулировка задачи для нового чата (короткий промпт):

> Продолжаем проект u1u2-bridge. Инвертор собран и проверен (DC + UART stream). Осталось финальный CRSF 420k smoke-test через `/dev/ttyS7` (физически на OPi 5 Max pin 26, UART7-M2). Ожидание: WiFi `ExpressLRS TX` не появится. Если не выйдет — план Б с 74HC04. Также висит WireGuard.
>
> **После успешного smoke-теста переключаемся в Claude Code** (у меня установлен) для правок в репозитории: обновить `CLAUDE.md` с 4 lessons learned (A/B/C/D из handoff'а), создать `docs/inverter-schematic.md`, опционально сохранить картинку pinout как `docs/orangepi-5-max-pinout.png`. Всё через git branch + commit, не руками через чат.

### Когда переключаться в Claude Code

| Задача | Где делать |
|---|---|
| CRSF smoke-test, диагностика на u2 (SSH-команды, мультиметр) | Claude Chat (текущий формат) |
| WireGuard диагностика на u2 | Claude Chat |
| Правки `CLAUDE.md`, создание файлов в `docs/` | **Claude Code** |
| Правки Python-кода в `common/`, тестов в `tests/` | **Claude Code** |
| Любые `git commit / branch / push` | **Claude Code** |

Claude в новом чате должен **сам** напомнить про переход в Claude Code, когда речь зайдёт о правках репозитория. Если не напоминает — задать вопрос «а почему мы не в Claude Code сейчас?» (как было в этом чате).

---

*Конец handoff. Прости за долгие диагностические завалы в этом чате — урок про "сначала прозвонка пайки" зафиксирован, в следующий раз будем последовательнее.*
