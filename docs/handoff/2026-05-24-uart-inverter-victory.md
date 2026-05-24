# HANDOFF — 2026-05-24 — UART_INVERTED проблема РЕШЕНА (74HC14N)

> **Победа.** OPi 5 Max теперь успешно управляет ELRS Ranger Micro через UART7 @ 420000 baud. Дрон забинден.
>
> Этот документ — финальный аудит работающей конфигурации, lessons и план обновления репозитория через Claude Code.

---

## 1. Что работает (полный аудит)

### Цепочка управления (end-to-end)
```
OPi 5 Max (Ubuntu, /dev/ttyS7 @ 420000 baud)
   │
   │ UART7 TX, non-inverted, 3.3V logic
   ▼
SN74HC14N hex Schmitt-trigger inverter (наша плата)
   │
   │ inverted CRSF, 3.3V logic
   ▼
ELRS Ranger Micro (firmware master 91b1ee, UART_INVERTED=on)
   │
   │ 2.4 GHz RF
   ▼
Дрон с ELRS RX (бинд OK)
```

### OPi 5 Max — используемые пины разъёма

| Pin OPi | Функция | Провод | Куда |
|---|---|---|---|
| 1 | 3.3V | синий | IC 74HC14N pin 14 (VCC) |
| 2 | 5V | красный | ELRS Ranger Micro pin 3 (питание модуля) |
| 6 | GND | чёрный длинный | ELRS pin 4 (GND модуля) |
| 6 | GND | чёрный короткий | плата (GND-шина IC) |
| 26 | UART7-M2 TX | зелёный | IC 74HC14N pin 1 (input) |

### UART7-M2 настройка

Overlay в `/boot/extlinux/extlinux.conf`:
```
fdtoverlays /lib/firmware/6.1.0-1025-rockchip/device-tree/rockchip/overlay/rk3588-uart7-m2.dtbo
```

Проверка:
```bash
ls -l /dev/ttyS7
# crw-rw---- 1 root dialout 4, 71 ... /dev/ttyS7
```

Нужен `sudo` или членство в группе `dialout` для записи в порт.

### 74HC14N инвертор — финальная схема

**Компонент:** Texas Instruments SN74HC14N, hex Schmitt-trigger inverter, DIP-14.

Используется только первый из шести инверторов (gate 1). Schmitt-trigger вход критичен — чистит фронты от RK3588 UART, выход всегда rail-to-rail 3.3V.

| Pin IC | Функция | Подключение |
|---|---|---|
| 1 | 1A (input) | зелёный провод от OPi pin 26 (UART7 TX) |
| 2 | 1Y (output, inverted) | белый провод к ELRS pin 5 |
| 3, 5, 9, 11, 13 | unused inputs (2A, 3A, 4A, 5A, 6A) | **все на GND** одной перемычкой |
| 4, 6, 8, 10, 12 | unused outputs (2Y, 3Y, 4Y, 5Y, 6Y) | NC (ничего) |
| 7 | GND | чёрный короткий от OPi pin 6, + входит в GND-шину |
| 14 | VCC | синий провод от OPi pin 1 (3.3V) |

**Ориентация:** выемка / точка-индикатор pin 1 — **сверху** при вертикальном монтаже, pin 1 в верхнем-левом углу.

**GND-шина:** один проводок физически проходит через pins 7, 3, 5, 9, 11, 13 на плате, припаян в 6 точках. От общей точки — чёрный короткий провод к OPi pin 6.

**Decoupling:** опционально 100 нФ между pin 14 и pin 7 у самого IC. **Не ставили, работает без него**, но рекомендуется для production-надёжности.

### ELRS Ranger Micro — pinout (JR-style)

| Pin модуля | Сигнал | Откуда |
|---|---|---|
| 3 | 5V | OPi pin 2 (красный) |
| 4 | GND | OPi pin 6 (чёрный длинный) |
| 5 | CRSF (inverted) | IC 74HC14N pin 2 (белый) |

---

## 2. Программная часть

### Python окружение на u2-pi

- Python 3 системный (Ubuntu 24.04 ARM64)
- `pyserial` (apt: `python3-serial`)
- Требуется `sudo` для доступа к `/dev/ttyS7`

### Где хранить тестовые скрипты на u2-pi

**НЕ в `/tmp/`** — это tmpfs, очищается при каждой перезагрузке.

**Правильное место:** `~/hardware/` (= `/home/ubuntu/hardware/`). Переживает ребуты, не требует sudo для редактирования.

Создание:
```bash
mkdir -p ~/hardware
```

### Тестовые скрипты (надо сохранить в репозитории + задеплоить на Pi)

**`hardware/crsf_smoke_test.py`** — генератор CRSF RC frames @ 250 Hz, baud 420000.

Шлёт фрейм с фиксированным значением 992 на всех 16 каналах. Использовался для smoke-теста инвертора (бинд с дроном получен).

Критический момент: использует `time.perf_counter()` + busy-wait, **не `time.sleep()`**. Причина — `time.sleep(0.004)` на Linux scheduler даёт ~16 ms granularity (60 Hz), а busy-wait даёт точные 4 ms (250 Hz). ELRS firmware требует rate ≥ 100 Hz для валидации CRSF link.

**`hardware/crsf_jitter_test.py`** — расширенная версия со статистикой: jitter (stddev интервалов), throughput (B/s, % от baud rate), min/max интервалов. Полезна для диагностики UART driver / scheduler проблем.

Норма для 250 Hz CRSF на этой системе:
- rate: **249.5 - 250.5 Hz**
- interval: **4.00 ± < 0.2 ms**
- min/max: **3.8 - 4.2 ms**
- throughput: **~6500 B/s** (это ~12% от теоретического 420000 baud — нормально)

Если эти числа сходятся — UART-стек идеальный.

### Workflow деплоя на Pi

После того как Claude Code сохранит скрипты в `hardware/` репозитория, обновление на Pi — одной командой:

```powershell
# С ноута, из корня репо
scp hardware/*.py ubuntu@192.168.31.100:~/hardware/
```

Или (если поднимется WireGuard):

```powershell
scp hardware/*.py ubuntu@10.8.0.7:~/hardware/
```

Запуск на Pi:
```bash
sudo python3 ~/hardware/crsf_smoke_test.py
sudo python3 ~/hardware/crsf_jitter_test.py
```

---

## 3. Lessons & Incidents (для CLAUDE.md)

Все добавлять в раздел `## Lessons & Incidents` **сверху** (новые записи выше). Формат уже задан в CLAUDE.md.

### Запись 1 — основная диагностика

````markdown
### 2026-05-24 · CRSF 420k через single-NPN inverter не работает (storage time)

Hardware-инвертор на одиночном BC548 для UART_INVERTED не валидируется ESP32 в ELRS Ranger Micro при 420000 baud. Симптом: модуль уходит в config mode (поднимает WiFi `ExpressLRS TX`) через ~30-60 секунд после старта стрима. DC уровни корректные (B=2.8V, C=0.2V — точно как теоретически), но edges на 420k размытые из-за storage time транзистора в hard saturation. Расчёт: R1=2.2kΩ даёт ib=1.2mA при необходимом 3.5µA — over-drive в 340x → storage time вырастает с 225ns datasheet до 1-2µs, что 40-80% bit time 2.38µs на 420k.

**Правило:** для UART > 230400 baud не использовать single-NPN inverter без speed-up cap или Baker clamp. Для дальнейших CRSF-каналов сразу брать 74HC14N или другой CMOS-инвертор.

**Проверка:** статический замер DC inversion ничего не докажет на скоростях. Нужен либо осциллограф, либо end-to-end test с реальным потребителем (ESP32 UART receiver валидирует фреймы).
````

### Запись 2 — фикс

````markdown
### 2026-05-24 · 74HC14N Schmitt-trigger как фикс UART invert на 420k

Замена single-NPN на SN74HC14N (hex Schmitt-trigger inverter, DIP-14) полностью решила проблему. ESP32 валидирует CRSF, модуль остаётся в operating mode, бинд с дроном проходит. Использован один gate (pin 1 IN / pin 2 OUT), остальные 5 input pins (3, 5, 9, 11, 13) обязательно стянуты на GND через одну перемычку, output pins (4, 6, 8, 10, 12) — NC.

Schmitt-trigger вариант выбран вместо обычного 74HC04, потому что гистерезис на входе (~0.4-1V) дополнительно чистит фронты от RK3588 UART и от паразитной capacitance проводов.

Финальная схема в `docs/inverter-schematic.md`.

**Правило:** для любого UART invert на скоростях ≥ 230400 — сразу 74HC14 (Schmitt). Не экономить на CMOS-IC ради «одного транзистора».

**Проверка:** smoke-test через `hardware/crsf_smoke_test.py`. Критерий: 2+ минуты стрима без появления `ExpressLRS TX` WiFi сети.
````

### Запись 3 — про ESP32 hardware feature

````markdown
### 2026-05-24 · UART_INVERTED в ELRS — ESP32-only hardware feature

Опция `UART_INVERTED` в ExpressLRS firmware работает ИСКЛЮЧИТЕЛЬНО на ESP32-based TX-модулях. Это build-time define, который конфигурирует hardware UART periphery ESP32 для приёма inverted-level сигнала — на чипе. Не runtime-видимая опция, в WebUI её обычно нет.

Для не-ESP32 модулей (STM32-based и т.д.) UART_INVERTED игнорируется, нужно делать hardware inversion снаружи.

**Правило:** перед попыткой UART-связи с ELRS-модулем проверять, какой у него MCU и какая прошивка. Если ESP32 + master firmware с UART_INVERTED=on → нужен hardware inverter ИЛИ пересборка прошивки с UART_INVERTED=off.

**Альтернатива hardware:** перепрошить ELRS через Configurator с снятой галкой "Invert TX". Тогда инвертор не нужен. В нашем проекте выбрали hardware-путь чтобы не трогать прошивку модуля.
````

### Запись 4 — про ELRS таймаут

````markdown
### 2026-05-24 · ELRS таймаут config mode — 30-60 секунд без валидного CRSF

После подачи питания ELRS Ranger Micro ждёт ~30-60 секунд валидный CRSF на UART. Если за это окно не получил — автоматически поднимает WiFi-сеть `ExpressLRS TX` для конфигурации. Это тот самый сигнал «CRSF не валидируется».

Окно теста для отладки UART к модулю: после reset питания у тебя ~30 секунд чтобы запустить стрим. Если не успел — модуль уйдёт в config, надо передёргивать питание (red wire к pin 3 модуля на 3 секунды).

**Правило:** тестовый процесс UART-моста к ELRS — это «передёрнул питание модуля → быстро стартанул стрим → жди 2 минуты для подтверждения». Если WiFi не появилась — успех.

**Проверка:** телефон с открытым списком WiFi-сетей рядом во время теста.
````

### Запись 5 — про Python timing

````markdown
### 2026-05-24 · Python time.sleep на Linux — 16ms granularity, не годится для UART

Скрипт с `time.sleep(0.004)` для CRSF 250 Hz на самом деле выдавал 60 Hz — `sleep()` округляется scheduler'ом до системного тика (~16ms). Это вызвало false-positive в диагностике: думали что hardware-инвертор не справляется, а на самом деле packet rate был втрое ниже ожидаемого.

Фикс — busy-wait через `time.perf_counter()`:
```python
next_tick = start + period
while time.perf_counter() < next_tick:
    pass
next_tick += period
```

Съедает 1 ядро CPU, но даёт микросекундную точность.

**Правило:** для любого периодического UART/network трафика с периодом < 20 ms — busy-wait, не `sleep`. Если CPU-расход важен — переписать на C или async с event loop, который умеет high-resolution timers.

**Проверка:** в скрипте логировать реальный `rate = packets_count / elapsed_time` и сравнивать с target.
````

### Запись 6 — про persistent storage скриптов

````markdown
### 2026-05-24 · /tmp на u2-pi — tmpfs, очищается при ребуте

Тестовые скрипты, сохранённые в `/tmp/` через heredoc (как привычно делать при отладке), пропадают после каждой перезагрузки. Постоянное место для hardware-тестов на u2-pi — `~/hardware/` (= `/home/ubuntu/hardware/`). Не требует sudo, переживает ребуты.

**Правило:** тестовые скрипты, которые могут понадобиться повторно, не хранить в `/tmp/`. Сохранять в репозитории (`hardware/`) и деплоить на Pi через `scp` в `~/hardware/`.

**Проверка:** после ребута Pi — `ls ~/hardware/` должен показывать сохранённые скрипты.
````

---

## 4. Файлы для создания/обновления в репозитории

Все пути от корня репо `C:\Users\ARDOR\Documents\Projects\u1u2-bridge`.

### Создать (новые)

**4.1. `docs/inverter-schematic.md`** — финальная схема инвертора:

Содержание:
- BOM (компонент: SN74HC14N DIP-14, опционально 100 нФ декаплинг)
- Pinout таблица (из раздела 1 этого handoff'а)
- Схема подключения 6 проводов системы (таблица из раздела 1)
- GND-шина — как делать перемычку через 6 пинов
- Что выкинули со старой BC548-платы (BC548, R1=2.2k, R2=4.7k)
- Тест-процедура (4 этапа: прозвонка → static DC → 115200 stream → CRSF 420k)

**4.2. `docs/opi5max-uart7-setup.md`** — как поднять UART7-M2 на pin 26:

Содержание:
- Зачем UART7-M2 (а не другой UART): доступность pin 26 на 40-pin header
- Какой overlay (`rk3588-uart7-m2.dtbo`)
- Изменения в `/boot/extlinux/extlinux.conf`
- Какой `/dev/ttyS*` получается (`/dev/ttyS7`)
- Доступ: sudo или dialout группа
- Verify-команды (`ls -l /dev/ttyS7`, `grep uart7 /boot/extlinux/extlinux.conf`)

**4.3. `hardware/crsf_smoke_test.py`** — финальный CRSF smoke-тест (250 Hz, busy-wait).

В начале файла обязательный docstring:
```python
"""CRSF smoke-test для 74HC14N инвертора.

Шлёт CRSF RC frames @ 250 Hz, baud 420000 на /dev/ttyS7.
Критерий успеха: 2+ минуты стрима, ESP32 не уходит в config mode
(WiFi сеть 'ExpressLRS TX' не появляется).

Запуск на u2-pi:
    sudo python3 ~/hardware/crsf_smoke_test.py

Деплой с ноута (из корня репо):
    scp hardware/crsf_smoke_test.py ubuntu@192.168.31.100:~/hardware/
"""
```

Тело скрипта (Python код) — взять из чата с Claude, блок `cat > /tmp/crsf_smoke.py << 'PYEOF' ... PYEOF` (только содержимое между PYEOF, без оболочки heredoc).

**4.4. `hardware/crsf_jitter_test.py`** — расширенная версия со статистикой.

В начале файла обязательный docstring:
```python
"""CRSF jitter / throughput test для 74HC14N инвертора.

Расширенная версия smoke-теста с измерением jitter (stddev интервалов),
throughput (B/s, % от 420k baud) и min/max интервалов между пакетами.
Полезно для диагностики UART driver и scheduler проблем.

Норма на u2-pi:
    rate: 249.5 - 250.5 Hz
    interval: 4.00 ± < 0.2 ms
    min/max: 3.8 - 4.2 ms
    throughput: ~6500 B/s

Запуск на u2-pi:
    sudo python3 ~/hardware/crsf_jitter_test.py
    # Ctrl+C через 30+ секунд для итоговой статистики

Деплой с ноута (из корня репо):
    scp hardware/crsf_jitter_test.py ubuntu@192.168.31.100:~/hardware/
"""
```

Тело — взять из чата с Claude.

**4.5. `hardware/README.md`** — описание папки `hardware/`:

Содержание (короткое):
- Назначение папки — Python-скрипты для тестирования физического слоя (UART, GPIO, hardware-инвертор)
- Список скриптов с одной строкой про каждый
- Workflow деплоя: пишем/правим скрипт в репо → `scp hardware/*.py ubuntu@<pi-ip>:~/hardware/` → SSH на Pi → `sudo python3 ~/hardware/<script>.py`
- Где это работает: u2-pi (OPi 5 Max), требуется UART7-M2 настроенный (см. `docs/opi5max-uart7-setup.md`)

### Обновить (существующие)

**4.6. `CLAUDE.md`** — добавить 6 новых записей в раздел `## Lessons & Incidents` (см. раздел 3 этого handoff'а). Все добавляются **сверху** (новые записи выше старых, перед записью от 2026-05-13).

**4.7. `docs/HANDOFF.md`** — глобальный handoff проекта u1u2-bridge:

- В §3 (архитектурные решения) добавить пункт про hardware inverter (74HC14N) как компонент между OPi и ELRS, со ссылкой на `docs/inverter-schematic.md`.
- В §6 (текущее состояние) пометить инвертор как РАБОТАЕТ: «UART invert через 74HC14N — собран, протестирован, end-to-end бинд с дроном проходит на u2-pi».
- В §7.1 (RS485 auto-direction) добавить ссылку на этот результат: «Для CRSF на 420k проблема edge speed решена через CMOS-инвертор. Для будущих CRSF-каналов и RS485 — сразу 74HC14N, не пытаться single-transistor.»
- В §8 (следующие шаги) — обновить приоритеты:
  1. ✅ ЗАКРЫТО: UART invert к ELRS-модулю #1.
  2. Сделать второй CRSF-канал (через ещё один gate того же 74HC14N — он 6-канальный, остались 5 свободных gates).
  3. Подключить второй ELRS-модуль.
  4. Тест в полёте с реальным каналом управления.
  5. Видео-pipeline (отдельная ветка).

---

## 5. Что НЕ трогать

Текущая конфигурация **работает**. До того как Claude Code обновит документы, прошу:

- НЕ переподключать провода на плате с 74HC14N
- НЕ менять `/boot/extlinux/extlinux.conf` (overlay UART7-M2)
- НЕ перепаивать GND-шину (через 6 пинов)
- НЕ менять прошивку ELRS-модуля (она уже скомпилирована под inverted UART, и наш hardware подходит)

Если что-то менять понадобится — сначала закоммитить текущее состояние в git, чтобы был rollback-точка.

---

## 6. Инструкция для Claude Code

В корне репо `C:\Users\ARDOR\Documents\Projects\u1u2-bridge` запусти Claude Code и дай ему этот handoff-файл + следующий промпт:

````
Прочитай docs/handoffs/2026-05-24-uart-inverter-victory.md.

Сделай следующее по порядку, перед каждым шагом показывая diff:

1. Создай папку docs/handoffs/ если её нет, и убедись, что handoff лежит там.

2. Создай docs/inverter-schematic.md согласно разделу 4.1 handoff'а. 
   Все данные (BOM, pinout, провода, GND-шина) — из раздела 1 handoff'а.
   Включи раздел "Тест-процедура" с 4 этапами проверки.

3. Создай docs/opi5max-uart7-setup.md согласно разделу 4.2 handoff'а.
   Verify-команды в конце.

4. Создай папку hardware/ и в ней:
   - crsf_smoke_test.py (с docstring из раздела 4.3 handoff'а)
   - crsf_jitter_test.py (с docstring из раздела 4.4 handoff'а)
   - README.md (по разделу 4.5)
   
   Тело Python-скриптов (без docstring) попроси у меня — 
   я скопирую из чата с Claude в браузере.

5. Обнови CLAUDE.md — добавь 6 записей из раздела 3 handoff'а в раздел 
   ## Lessons & Incidents. Все ДОБАВЛЯЮТСЯ СВЕРХУ, выше записи 2026-05-13. 
   Порядок записей внутри блока — от 1 к 6 (т.е. в файле 1 окажется самой 
   верхней, 6 — над записью 2026-05-13).

6. Обнови docs/HANDOFF.md согласно разделу 4.7 handoff'а — это четыре 
   правки в разных секциях (§3, §6, §7.1, §8).

7. Прогони .\verify.ps1 — должно быть зелёное. Если падает — покажи, 
   разберёмся.

8. Git commit с сообщением:
   "docs+hardware: финализация UART inverter (74HC14N), 6 lessons, тесты"
   Затем git push.

Не делай ничего, что не указано в плане. Если что-то непонятно — спроси.
````

После того как Claude Code попросит код тестовых скриптов — вернёшься в чат с Claude в браузере и скопируешь блоки `cat > ~/hardware/crsf_smoke_test.py << 'PYEOF'` и `cat > ~/hardware/crsf_jitter_test.py << 'PYEOF'` (только содержимое Python — без оболочки heredoc и `PYEOF` маркеров).

---

## 7. Тесты прямо сейчас (опционально, до Claude Code)

Если хочешь увидеть статистику скорости/jitter на работающей системе до того, как Claude Code что-то сделает — выполни в SSH на u2-pi:

```bash
mkdir -p ~/hardware && cat > ~/hardware/crsf_jitter_test.py << 'PYEOF'
# код возьми из чата с Claude
PYEOF
sudo python3 ~/hardware/crsf_jitter_test.py
```

Дай ему ~30 секунд побегать (модуль уже забинден, передёргивать ничего не нужно), потом Ctrl+C — увидишь блок `FINAL` с итоговой статистикой.

Норма указана в разделе 2 этого handoff'а.

Это **не обязательно** — система работает, тест был бы просто для красоты цифр.

---

## 8. Что осталось открытым после этой победы

- Второй CRSF-канал (для второго ELRS-модуля). Можно использовать ещё один gate того же 74HC14N — пины 3-4 (gate 2), 5-6 (gate 3), 9-8 (gate 4), 11-10 (gate 5), 13-12 (gate 6). Сейчас все unused inputs заземлены, при подключении второго канала нужно будет пины 3 (input gate 2) отключить от GND и завести на второй UART OPi.
- Второй UART на OPi для второго CRSF — потребует второго overlay (например `rk3588-uart8-m0.dtbo` или подобный) и пина для TX. План — в `docs/HANDOFF.md` §8.
- Реальный полёт с проверкой каналов (стики двигаются → дрон реагирует).
- Видео-pipeline (RX и TX) — отдельная ветка, ещё не начата.

---

*Конец handoff. Сохрани этот файл как `docs/handoffs/2026-05-24-uart-inverter-victory.md` в репозитории, потом передай Claude Code согласно разделу 6.*
