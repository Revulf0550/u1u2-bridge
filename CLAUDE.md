# CLAUDE.md

> Живая память проекта. Эволюционирует с каждым PR и инцидентом.
> Принцип: если факт можно получить через `cat`, `ls`, `grep` — он не здесь.

---

## Project Context

- **Продукт:** беспроводная замена 8-жильного кабеля между двумя устройствами FPV-наземки (У1 — мастер-пульт с TX12 + видео-передатчиком к очкам, У2 — выносная база с 2× ELRS-передатчиками и VRX). Дистанция до 1 км, через готовый Wi-Fi PtP мост TP-Link CPE710.
- **Стадия:** код написан и логически готов, не тестирован на железе. Hardware заказан, не получен.
- **Стек:** Python 3.12 + Bash + systemd на Ubuntu 24.04 ARM64 (Orange Pi 5 / RK3588S). GStreamer с RKMPP для видео, WireGuard для VPN поверх CPE710.
- **Деплой:** `sudo ./install.sh u1` или `sudo ./install.sh u2` на каждой Orange Pi. Локального запуска нет — всё работает на железе.
- **Регуляторика:** нет (hobby/personal use).
- **Нагрузка:** 2× CRSF потоки (420k бод, 250–500 Hz, до 64 байт/кадр), 1× видео H.264 RTP (2.5 Mbps, 25–30 fps), всё через UDP.
- **Бюджет латенции:** glass-to-glass <100 мс (видео), CRSF round-trip <20 мс.

---

## Architecture

### Структура исходников

```
.
├── common/                # Python код, общий для У1 и У2
│   ├── crsf_bridge.py     # UART↔UDP байтовый мост
│   └── systemd/           # шаблонные systemd-юниты (.service)
├── u1/                    # мастер-пульт (HDMI вывод видео для очков)
│   ├── video_rx.sh        # GStreamer RX pipeline
│   └── systemd/
├── u2/                    # выносная база (видео-кодирование + ELRS)
│   ├── video_tx.sh        # GStreamer TX pipeline
│   └── systemd/
├── install.sh             # деплоер на Orange Pi (роль u1|u2)
├── docs/                  # HANDOFF.md, документация по железу/деплою
└── tests/                 # unit-тесты с моками socket/serial
```

**Слоистость:** `common/` — переиспользуемый код. `u1/` и `u2/` — деплой-артефакты для соответствующей роли. Никаких импортов между `u1/` и `u2/`.

### Python — общие инварианты

- **Стандартная библиотека где возможно.** В рантайме только `pyserial` (UART) и стандартная библиотека (`socket`, `select`, `signal`, `logging`). Никакого `asyncio` (он усложнит тесты и не даёт выигрыша на блокировке IO с таймаутом 5 мс — выбор сознательный).
- **Типы strict.** `mypy --strict` (настроен в `pyproject.toml`). `Any` запрещён в публичных сигнатурах. Все функции с аннотациями параметров и возврата.
- **Тулинг.** Линтер и форматтер — `ruff` с правилами `ASYNC` (на случай мисмикса) и `T20` (запрет `print`). Тесты — `pytest` + `pytest-mock` для моков сокетов/serial.
- **Логирование — через `logging`, не `print`.** Уровни: `INFO` для статистики, `WARNING` для отказов IO, `ERROR` для unrecoverable. Стандартный `logging.basicConfig` — логи попадают в `journalctl` через stdout/stderr.
- **Обработка сигналов.** `SIGTERM` и `SIGINT` ставят стоп-флаг, цикл доходит до конца итерации и выходит. Никаких `os._exit()` — иначе systemd ждёт `TimeoutStopSec` и потом убивает `SIGKILL`.

### IO-петли и буферизация

- **Неблокирующее IO + `select`.** Любой долгоживущий сервис — `select.select([serial, sock], [], [], 5_ms)` цикл. Не `time.sleep`, не блокирующее `read`.
- **Авто-переподключение USB-устройств.** Если `serial.SerialException` — закрыть, переоткрыть через 1 секунду, **не убивать процесс**. systemd `Restart=always` не должен быть first line of defence для типовых выдёргиваний кабеля.
- **UDP-буферы — увеличены явно.** `SO_RCVBUF=65536`, `SO_SNDBUF=65536`. На Wi-Fi мосте джиттер 5–10 мс, без буфера будут потери.
- **UART буферы — очистка при открытии.** `reset_input_buffer()` + `reset_output_buffer()` после `Serial()` — иначе подхватывается мусор от предыдущей сессии.

### systemd — паттерны деплоя

- **`Restart=always`, `RestartSec=2`** для всех боевых юнитов. Любой crash → перезапуск через 2 сек.
- **`Type=simple`**, не `notify` (избегаем зависимости на `sd_notify` в Python-коде).
- **`After=network-online.target` + `Wants=network-online.target`** для всех сетевых юнитов. Без этого юнит может стартовать до подъёма интерфейса.
- **`EnvironmentFile=/etc/u1u2-bridge/<name>.env`** для параметризации. Никаких хардкодов IP, баудрейтов, портов в скриптах.
- **Шаблонные юниты `name@.service`** там, где несколько инстансов одного типа (`crsf-bridge@tx1`, `crsf-bridge@tx2`). Параметризация через `%i`.
- **`Nice=-10` + `IOSchedulingClass=realtime`** для latency-критичных сервисов (CRSF). Не для всех — это потребляет ресурсы. Видео обходится `Nice=-5`.

### Bash-скрипты — инварианты

- **`set -euo pipefail` на каждом скрипте.** Без этого ошибки тихо проглатываются и `install.sh` "успешно" заканчивается с битой системой.
- **`shellcheck` обязателен.** Запускается в `verify.ps1` для всех `.sh`-файлов.
- **Все настраиваемые параметры — через env с дефолтами.** `BITRATE="${VIDEO_BITRATE:-2500000}"`. Не позиционные аргументы.
- **`exec` в конце GStreamer-скриптов.** `exec gst-launch-1.0 ...` — иначе процессы плодятся, systemd видит "родителя" а не реальный pipeline.

### Сеть — UDP и WireGuard

- **UDP-порт на канал, peer-to-peer.** Каждый CRSF/CTRL канал — один UDP порт двунаправленно. RS485 half-duplex даёт гарантию, что обе стороны не передают одновременно.
- **Адресация двухслойная.** Локально: `192.168.1.0/24` (CPE710 LAN). Туннель: `10.10.0.0/24` (WireGuard поверх). После полевых испытаний — переключить env-файлы с `192.168.1.x` на `10.10.0.x`.
- **WireGuard `PersistentKeepalive = 15`** на клиентской стороне. Без него NAT-таблица CPE710 может протухать.
- **MTU учтён в RTP.** `rtph264pay mtu=1400` — оставляем 100 байт на инкапсуляцию (Wi-Fi headers + WireGuard 60–100 байт overhead).

### GStreamer — низкая латентность

- **Только `mpph264enc` / `mppvideodec`** на Orange Pi 5 (аппаратный H.264 через VPU RK3588). Не `v4l2h264enc` (медленнее на 7–10 мс). Зависимость: пакет `gstreamer1.0-rockchip1` из репо joshua-riek.
- **`profile=baseline`** (нет B-кадров), GOP=15 для быстрого recovery после потерь.
- **`rtpjitterbuffer latency=15 drop-on-latency=true`** на приёмнике. Не больше 15 мс джиттера — теряем кадр, не ждём.
- **`kmssink` для вывода на HDMI**, не `xvimagesink`/`waylandsink`. Минует композитор, режет 10–15 мс. Требует загрузки в `multi-user.target` (без graphical-target). `install.sh` это делает.
- **`udpsink sync=false async=false`** — иначе GStreamer пытается синхронизировать по часам, добавляет задержку.

### Hardware и периферия

- **udev-правила для стабильных имён USB-устройств.** `/dev/ttyUSB-CRSF1`, `/dev/ttyUSB-CRSF2` через `SYMLINK+=` по серийному номеру чипа. Никогда не использовать `/dev/ttyUSB0`/`ttyUSB1` в env-файлах — порядок меняется при перезагрузке.
- **USB↔RS485 auto-direction.** Полагаемся на аппаратное переключение TX-detect (Waveshare на SP485EEN). Если на 420k бод не сработает — fallback на ручное управление через RTS + `fcntl.ioctl(TIOCSRS485)`. Открытый вопрос, см. `docs/HANDOFF.md` §7.1.
- **Сетевой интерфейс Orange Pi 5 в Ubuntu от Joshua Riek — `end0`.** В Armbian может быть `eth0` или `enp1s0`. `install.sh` определяет имя автоматически через `ip -br link | awk '$1 != "lo" {print $1; exit}'`.

### Embedded-надёжность (когда дойдём)

- **Hardware watchdog RK3588** (модуль `rockchip-wdt`), таймаут 15 секунд. Включается через `/etc/watchdog.conf`.
- **Read-only rootfs** для production-устройств (overlay FS). Защита от повреждения файловой системы при внезапном отключении питания.
- **Логи на tmpfs или отдельный раздел** — чтобы read-only FS не мешал записи логов и не убивал ресурс SD-карты.

---

## Commands

### Verification (на Windows локально, перед коммитом)

| Что | Команда |
|---|---|
| Все проверки разом | `.\verify.ps1` |
| Только тесты | `uv run pytest` |
| Только типы | `uv run mypy common tests` |
| Только линт Python | `uv run ruff check common tests` |
| Автопочинка | `.\format.ps1` |

### На Orange Pi (после `install.sh`)

| Что | Команда |
|---|---|
| Установить (роль u1 или u2) | `sudo ./install.sh u1` |
| Зарегистрировать UART-адаптеры в udev (после физ. подключения) | `sudo ./setup_udev.sh` |
| Постдеплой smoke-test | `sudo ./smoke_test.sh u1` (или `u2`) |
| Статус CRSF-моста | `systemctl status crsf-bridge@tx1` |
| Логи CRSF live | `journalctl -u crsf-bridge@tx1 -f` |
| Статус видео | `systemctl status video-tx` (У2) или `video-rx` (У1) |
| Тест локальной сети | `ping -i 0.2 192.168.1.20` |
| Тест туннеля | `ping 10.10.0.2` (после WireGuard) |
| Проверка RKMPP | `gst-inspect-1.0 mpph264enc` |
| Preflight CRSF (без запуска моста) | `uv run python -m common.crsf_bridge --serial /dev/ttyUSB-CRSF1 --listen 0.0.0.0:14550 --peer 192.168.1.20:14550 --dry-run` |
| Валидация env-файла(ов) CRSF | `uv run python -m common.crsf_bridge --check-config /etc/u1u2-bridge/crsf-tx1.env /etc/u1u2-bridge/crsf-tx2.env` |

### Зависимости (Python, локально)

| Что | Команда |
|---|---|
| Установить | `uv sync --all-groups` |
| Добавить runtime-dep | `uv add <package>` |
| Добавить dev-dep | `uv add --dev <package>` |

---

## Lessons & Incidents

> **Формат записи:**
> ```
> ### YYYY-MM-DD · Короткий симптом
> Что произошло (1–3 предложения).
> **Правило:** одно предложение, применимое к похожим случаям.
> **Проверка:** команда или тест, который ловит регрессию.
> ```
>
> Новые записи добавляй **сверху**. После каждого merged PR спрашивай себя:
> «Произошёл хоть один сюрприз / откат / 'ой не туда'? Если да — формулируй правилом».

### 2026-05-24 · UFW дропает пакеты на новые порты crsf-bridge молча

Сервис `crsf-bridge@elrs` стартует чисто (`bind ok`, в журнале только INFO), но статистика показывает вечный `udp->uart=0 B/s`. `tcpdump` на интерфейсе видит пакеты, `ss` подтверждает bind на `0.0.0.0:14552`, но application получает 0 B/s. Это сигнатура UFW default-deny дропа на INPUT chain — пакеты дропаются **до** сокета, без ICMP-reject, без записи в лог (если не включён `ufw logging`). Тишина в логе приложения не означает «нет трафика», а означает «UFW молча дропнул».

**Правило:** при создании нового `/etc/u1u2-bridge/crsf-<name>.env` обязательный парный шаг — `sudo ufw allow from <peer-ip> to any port <port> proto udp comment '<name>'`. В идеале вшить в `install.sh` или сделать `add-crsf-channel.sh`.

**Проверка:** `sudo iptables -L INPUT -v -n` — счётчик у policy DROP не должен расти при работающем bench. `sudo journalctl -u crsf-bridge@<name> -n5` — после первого stat_period (10 сек) `udp->uart` должно быть ненулевым.

---

### 2026-05-24 · ELRS TX в WiFi config mode игнорирует CRSF, обратная телеметрия = 0

Мост работает, `udp->uart` показывает ожидаемые B/s, но `uart->udp=0` и нет ответа от дрона. Можно потратить минуты на гипотезы про инвертор и UART RX, тогда как ELRS-модуль просто был в WiFi setup mode (после двойного power-on у некоторых прошивок), не подключал CRSF UART. SSID `ExpressLRS TX` на телефоне — мгновенный индикатор.

**Правило:** до любой диагностики UART-цепи проверить — виден ли SSID `ExpressLRS TX` на телефоне/ноуте. Если виден — power-cycle модуля (передёрнуть 5V на 3 сек). Светодиод модуля в нормальном режиме мигает паттерном бинда/линка, в config mode обычно горит постоянно.

**Проверка:** `uart->udp` в логе моста стабильно ненулевое (link statistics ~50–300 B/s) — признак живой обратной цепи.

---

### 2026-05-24 · CRSF 420k через single-NPN inverter не работает (storage time)

Hardware-инвертор на одиночном BC548 для UART_INVERTED не валидируется ESP32 в ELRS Ranger Micro при 420000 baud. Симптом: модуль уходит в config mode (поднимает WiFi `ExpressLRS TX`) через ~30-60 секунд после старта стрима. DC уровни корректные (B=2.8V, C=0.2V — точно как теоретически), но edges на 420k размытые из-за storage time транзистора в hard saturation. Расчёт: R1=2.2kΩ даёт ib=1.2mA при необходимом 3.5µA — over-drive в 340x → storage time вырастает с 225ns datasheet до 1-2µs, что 40-80% bit time 2.38µs на 420k.

**Правило:** для UART > 230400 baud не использовать single-NPN inverter без speed-up cap или Baker clamp. Для дальнейших CRSF-каналов сразу брать 74HC14N или другой CMOS-инвертор.

**Проверка:** статический замер DC inversion ничего не докажет на скоростях. Нужен либо осциллограф, либо end-to-end test с реальным потребителем (ESP32 UART receiver валидирует фреймы).

---

### 2026-05-24 · 74HC14N Schmitt-trigger как фикс UART invert на 420k

Замена single-NPN на SN74HC14N (hex Schmitt-trigger inverter, DIP-14) полностью решила проблему. ESP32 валидирует CRSF, модуль остаётся в operating mode, бинд с дроном проходит. Использован один gate (pin 1 IN / pin 2 OUT), остальные 5 input pins (3, 5, 9, 11, 13) обязательно стянуты на GND через одну перемычку, output pins (4, 6, 8, 10, 12) — NC.

Schmitt-trigger вариант выбран вместо обычного 74HC04, потому что гистерезис на входе (~0.4-1V) дополнительно чистит фронты от RK3588 UART и от паразитной capacitance проводов.

Финальная схема в `docs/inverter-schematic.md`.

**Правило:** для любого UART invert на скоростях ≥ 230400 — сразу 74HC14 (Schmitt). Не экономить на CMOS-IC ради «одного транзистора».

**Проверка:** smoke-test через `hardware/crsf_smoke_test.py`. Критерий: 2+ минуты стрима без появления `ExpressLRS TX` WiFi сети.

---

### 2026-05-24 · UART_INVERTED в ELRS — ESP32-only hardware feature

Опция `UART_INVERTED` в ExpressLRS firmware работает ИСКЛЮЧИТЕЛЬНО на ESP32-based TX-модулях. Это build-time define, который конфигурирует hardware UART periphery ESP32 для приёма inverted-level сигнала — на чипе. Не runtime-видимая опция, в WebUI её обычно нет.

Для не-ESP32 модулей (STM32-based и т.д.) UART_INVERTED игнорируется, нужно делать hardware inversion снаружи.

**Правило:** перед попыткой UART-связи с ELRS-модулем проверять, какой у него MCU и какая прошивка. Если ESP32 + master firmware с UART_INVERTED=on → нужен hardware inverter ИЛИ пересборка прошивки с UART_INVERTED=off.

**Альтернатива hardware:** перепрошить ELRS через Configurator с снятой галкой "Invert TX". Тогда инвертор не нужен. В нашем проекте выбрали hardware-путь чтобы не трогать прошивку модуля.

---

### 2026-05-24 · ELRS таймаут config mode — 30-60 секунд без валидного CRSF

После подачи питания ELRS Ranger Micro ждёт ~30-60 секунд валидный CRSF на UART. Если за это окно не получил — автоматически поднимает WiFi-сеть `ExpressLRS TX` для конфигурации. Это тот самый сигнал «CRSF не валидируется».

Окно теста для отладки UART к модулю: после reset питания у тебя ~30 секунд чтобы запустить стрим. Если не успел — модуль уйдёт в config, надо передёргивать питание (red wire к pin 3 модуля на 3 секунды).

**Правило:** тестовый процесс UART-моста к ELRS — это «передёрнул питание модуля → быстро стартанул стрим → жди 2 минуты для подтверждения». Если WiFi не появилась — успех.

**Проверка:** телефон с открытым списком WiFi-сетей рядом во время теста.

---

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

---

### 2026-05-24 · /tmp на u2-pi — tmpfs, очищается при ребуте

Тестовые скрипты, сохранённые в `/tmp/` через heredoc (как привычно делать при отладке), пропадают после каждой перезагрузки. Постоянное место для hardware-тестов на u2-pi — `~/hardware/` (= `/home/ubuntu/hardware/`). Не требует sudo, переживает ребуты.

**Правило:** тестовые скрипты, которые могут понадобиться повторно, не хранить в `/tmp/`. Сохранять в репозитории (`hardware/`) и деплоить на Pi через `scp` в `~/hardware/`.

**Проверка:** после ребута Pi — `ls ~/hardware/` должен показывать сохранённые скрипты.

---

### 2026-05-22 (late night) · WebUI ELRS — это одна прокручиваемая страница, не несколько

В master-сборках ELRS (по крайней мере на commit 91b1ee) WebUI `http://10.0.0.1/` не имеет отдельной hardware-страницы. Есть три вкладки: **OPTIONS, WIFI, UPDATE**. Hardware-секция (CRSF Serial Pins, Radio Chip, Radio Power, и т.д.) находится **внизу OPTIONS-страницы** при прокрутке. Также там есть кнопки `UPLOAD target configuration` и `SAVE TARGET CONFIGURATION` для изменения pinout прямо через web.

**Правило:** при работе с WebUI ELRS — прокрутить OPTIONS-страницу до конца. Не ограничиваться видимой верхней частью.

**Проверка:** на странице должна быть видна секция "CRSF Serial Pins" с pin RX и pin TX.

---

### 2026-05-22 (late night) · Версия firmware ELRS — проверять первым делом

Шапка WebUI показывает версию firmware в формате `Firmware Rev. {branch} ({hash}) {band}`. Если branch = `master` — это самосборка с development ветки, **не stable release**. Поведение может отличаться от документированного.

**Правило:** перед любыми тестами CRSF к модулю — посмотреть версию firmware в шапке WebUI. Если master или git-hash — относиться к модулю как к unknown firmware и иметь в виду возможные regressions.

**Проверка:** Firmware Rev. на главной странице WebUI должна показывать понятную версию (3.x.x) для stable.

---

### 2026-05-22 (late night) · Drive contention в half-duplex single-pin CRSF — потенциальный блокер

ELRS TX модули обычно используют CRSF UART как half-duplex single-pin (RX pin == TX pin в hardware config). ESP32 переключает direction GPIO между приёмом команд и отправкой telemetry. Если подключить к этому пину OPi UART7 в стандартном push-pull режиме, который **непрерывно** драйвит линию — будут drive collisions с ESP32 telemetry output.

**Правило:** при подключении OPi (или любого Linux SBC) UART к single-pin half-duplex CRSF — ставить **резистор 1кΩ-4.7кΩ последовательно с TX** SBC. Это делает SBC "слабым" источником, ESP32 telemetry легко пересиливает.

**Проверка:** при тесте CRSF к ELRS TX модулю — если модуль не парсит правильно сформированные фреймы, и pinout верный, и GND общий, и polarity не инвертирована — добавить резистор и повторить.

---

### 2026-05-22 (late night) · GND через Dupont на header pin 6 OPi 5 Max — ненадёжно

В этой сессии continuity OPi pin 6 ↔ socket pin 4 не пищала через стандартный Dupont-коннектор на pin 6 header'а, несмотря на то что обе крайние точки = GND и провод цел. Перепайка чёрного провода напрямую на плату Pi (минуя Dupont) решила проблему.

**Правило:** для GND-связи между OPi 5 Max и внешним устройством — не полагаться только на Dupont-коннектор на header pin 6. Альтернативы: использовать другой GND pin (9, 14, 20, 25, 30, 34, 39), припаять напрямую к точке GND plane на плате Pi, или сменить Dupont на качественный с гарантированно хорошим обжимом.

**Проверка:** в continuity-тесте измерять "от пина header'а до металла другого конца провода", а не "от жилки до жилки". Это покрывает контакт Dupont↔header.

---

### 2026-05-22 (evening) · Не верить шёлкографии PCB без проверки документацией

На плате Ranger Micro есть сервисные пятаки `32_TX` / `32_RX`. По логике (имя + наличие в открытом доступе) они выглядят как «чистый неинвертированный UART к ESP32». На деле — оказалось, что ELRS firmware настраивает этот UART в режим `UART_INVERTED=true` (default для совместимости с радиостанциями типа FrSky QX7, TBS Tango 2, RadioMaster TX16S). Шёлкография говорит «вот UART ESP32», но **не говорит** «инвертированный или нет». Результат — припаялись правильно (electrically доказано через TX-spam), но LED модуля не реагирует на наш неинвертированный CRSF.

**Правило:** перед пайкой к сервисным пятакам ELRS / TBS Crossfire / R9 и других open-source RF-модулей — обязательно проверить в target-файле прошивки (на GitHub) что firmware ожидает на этом UART: invert или нет, full-duplex или half. То же касается debug-vs-CRSF UART: пятак может быть `serial_rx`/`serial_tx` для CRSF, а может быть UART0 ESP32 (общий с CP2102 для прошивки).

**Проверка:** GitHub-путь `ExpressLRS/ExpressLRS/src/hardware/TX/Radiomaster_<Module>_TX/` — там JSON/`.h` с `serial_rx`, `serial_tx`, `uart_invert`, `serial_half_duplex`. Полный контекст блокера — `docs/handoff/2026-05-22-evening-uart-invert-blocker.md`.

---

### 2026-05-22 (evening) · TX-spam + мультиметр DC = быстрый тест целостности 3.3V UART

Когда нужно проверить «доходит ли сигнал OPi UART до пятака приёмника после пайки» без осциллографа и без ответа от противоположной стороны: послать с OPi непрерывный байт-паттерн с большим количеством переходов (`b'\xAA' * 4096` в цикле write+flush), мерять DC-напряжение на целевом пятаке относительно GND, сравнить idle (без write) и spam (во время write). На 3.3V логике idle UART ≈ 3.2–3.3V (linе in idle high), на быстро меняющемся сигнале мультиметр DC показывает 0–2V среднее (зависит от duty cycle).

**Правило:** разница > 1V между idle и spam = OPi TX драйвит линию, провод имеет электрический контакт до пятака. Это НЕ подтверждает что сигнал корректно декодируется на той стороне (см. UART_INVERTED-блокер) — только физическую связь. Дешёвый sanity-test перед тем, как лезть в логические причины «нет ответа».

**Проверка:** одна цифра idle, одна spam, разница в одной точке (32_RX или RX-сторона цепи). Если разница близка к 0 — провод оборван, плохая пайка или GPIO не драйвит (sysfs ноды не активны, overlay не загрузился).

---

### 2026-05-22 (evening) · `stty` не поддерживает нестандартные baudrate (420 000 для CRSF)

CRSF использует 420 000 бод — нестандартная скорость, не входящая в POSIX-таблицу `stty`. Стандартный `stty -F /dev/ttyS7 420000 raw -echo` падает с `invalid argument '420000'` и не настраивает порт. Linux в принципе поддерживает arbitrary baudrate через `termios2` ioctl, но `stty` им не пользуется.

**Правило:** для нестандартных baudrate (включая 420k CRSF) использовать pyserial — она внутри вызывает `termios2`. `serial.Serial(port, 420000)` работает там, где `stty 420000` падает.

**Проверка:** `python3 -c "import serial; s=serial.Serial('/dev/ttyS7', 420000); print('ok'); s.close()"` печатает `ok` без exception.

---

### 2026-05-22 (evening) · `sudo python3 -c "..."` + запись в `/tmp` = PermissionError

При попытке `sudo python3 -c "...open('/tmp/file.bin','wb').write(data)"` падает `PermissionError: [Errno 13] Permission denied: '/tmp/file.bin'` даже когда процесс под root. Причина — AppArmor sandbox профиль для Python на Ubuntu 24.04 от joshua-riek (snap или дистрибутивный hardening): запись в `/tmp` из sandboxed Python заблокирована, несмотря на root-uid.

**Правило:** при необходимости сохранить бинарь через `sudo python3 -c "..."` — писать в `sys.stdout.buffer.write(data)` внутри Python, redirect `> ~/file.bin` снаружи sudo. Тогда файл создаёт shell от имени пользователя, AppArmor не вмешивается.

**Проверка:** `sudo python3 -c "import sys; sys.stdout.buffer.write(b'test')" > ~/test.bin && ls -la ~/test.bin` — файл создан с UID пользователя, не root.

---

### 2026-05-22 (late) · UART7 на Pi 5 Max архитектурно занят Bluetooth (AP6611)

После полного штатного reboot с overlay m1 loopback на пинах 29/38 показывает `in_waiting=0`, хотя `pinmux-pins` подтверждает привязку и `/dev/ttyS7` пишется без timeout. Причина: on-board Bluetooth-чип AP6611 штатно подключён к UART7 (m0-раскладка), служба `ap6611s-bluetooth.service` поднимает `brcm_patchram_plus` и держит `/dev/ttyS7` открытым. Overlay m1 переключает physical pinmux на пины 29/38, BT-чип становится недоступен, но патчер зависает и продолжает захват порта — наш Python-код тоже открывает порт, два клиента на одном UART-контроллере → конфликт. Race condition: первый тест после bringup может пройти (BT не успел захватить), штатный ребут — нет.

**Правило:** на платах RK3588 с on-board BT через UART (Pi 5 Max, Plus и подобных), прежде чем переназначать тот же UART через overlay — обязательно `systemctl disable --now + mask` для `bluetooth.service` и платформенного `*-bluetooth.service` (на Pi 5 Max — `ap6611s-bluetooth.service`).

**Проверка:** `sudo lsof /dev/ttyS7` сразу после ребута возвращает пусто; `systemctl is-active bluetooth.service ap6611s-bluetooth.service` показывает `inactive`. Полный контекст и команды восстановления — `docs/handoff/2026-05-22-late-uart7-bringup-complete.md`.

---

### 2026-05-22 (late) · `_BOOT_PATH=""` на joshua-riek ломает относительный `U_BOOT_FDT_OVERLAYS_DIR`

При попытке прописать persistent overlay через `U_BOOT_FDT_OVERLAYS_DIR="overlays/"` в `/etc/default/u-boot` (как в дефолтном шаблоне) скрипт `u-boot-update` тихо пропускает `fdtoverlays` — нет ошибки, в `extlinux.conf` остаётся только `fdtdir`. Причина: на joshua-riek образах `/boot` лежит на той же FS что и `/` (нет отдельной партиции), поэтому `u-boot-update` ставит `_BOOT_PATH=""`, и проверка `[ -f "${_BOOT_PATH}/${overlays_dir}/${dtbo}" ]` превращается в `[ -f "/overlays/..." ]` — путь от корня FS, где dtbo нет.

**Правило:** на joshua-riek (и любом образе с merged /boot+/) использовать **абсолютный** `U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"` и `U_BOOT_FDT_OVERLAYS` относительно `<kernel-version>/` подкаталога — тогда `u-boot-update` подставит актуальный `_VERSION` и dtbo обновится автоматически при апгрейде ядра.

**Проверка:** после `sudo u-boot-update` команда `grep fdtoverlays /boot/extlinux/extlinux.conf` под label `l0` показывает строку с абсолютным путём `/lib/firmware/<kernel>/.../*.dtbo`. Пусто → путь относительный или dtbo нет в `/lib/firmware/<kernel>/`. Полный разбор и TL;DR-команды — `docs/handoff/2026-05-22-late-uart7-bringup-complete.md`.

---

### 2026-05-22 (late) · Dupont-перемычки: подозревай контакт ПЕРВЫМ при странном loopback

В сессии bringup UART7 два независимых случая ложно-отрицательного loopback (overlay m2 на пинах 24/26 и overlay m1 на 29/38) каждый раз заставляли диагностировать программу — pinmux, скорости, права, race conditions — теряя часы. В обоих случаях виновник оказывался в перемычке: дешёвые Dupont female-female имеют плохой обжим, контакт пропадает при сгибе. Признаки: `in_waiting >> ожидание` + мусорные байты = RX плавает, ловит наводку 50 Гц; `in_waiting=0` полная тишина = TX в idle HIGH, RX тоже HIGH, наводок нет.

**Правило:** если loopback не проходит — **первое подозрение перемычка**, не программа. Прежде чем лезть в pinmux/скорости/драйверы — проверить контакт визуально и заменить перемычку на другую.

**Проверка:** "тест пальцем" — снять перемычку, открыть UART на пассивное чтение, прикоснуться пальцем к RX-пину. Живой RX за 5 секунд набирает десятки/сотни байт мусора от наводки 50 Гц через тело-антенну. Если 0 — проблема в программе или железе платы, не в перемычке.

---

### 2026-05-22 · UART7 на Orange Pi 5 Max работает через overlay m1, не m2

На Orange Pi 5 Max (kernel 6.1.0-1025-rockchip, joshua-riek Ubuntu 24.04) overlay `rk3588-uart7-m2.dtbo` активирует ноду `serial@feba0000`, но RX-пин остаётся `GPIO UNCLAIMED` — loopback не проходит ни на 420 000, ни на 9600 бод. Рабочий вариант — `rk3588-uart7-m1.dtbo`, физические пины 29 (TX) и 38 (RX), `pinmux-pins` подтверждает привязку `gpio3-16/17`. Подключение overlay через `U_BOOT_FDT_OVERLAYS` в `/etc/default/u-boot` молча игнорируется текущей версией `u-boot-menu`, пришлось править `/boot/extlinux/extlinux.conf` руками (правка помечена как auto-generated — открытый риск потери при обновлении ядра, см. Chunk D в HANDOFF).

**Правило:** для активации периферии RK3588 через device-tree overlay не доверять номерам пинов из стороннего туториала — всегда верифицировать через `sudo grep -ri uart7 /sys/kernel/debug/pinctrl/ | grep pinmux-pins` после загрузки и через loopback на 420k бод до пайки.

**Проверка:** `python3 -c 'import serial,time; s=serial.Serial("/dev/ttyS7",420000,timeout=2,write_timeout=2); s.reset_input_buffer(); s.write(b"TEST"); s.flush(); time.sleep(0.1); print(s.read(s.in_waiting))'` на u2-Pi с перемычкой 29↔38 должен вернуть `b'TEST'` и `in_waiting=4`.

---

### 2026-05-19 · Распиновка платы по фото без прозвонки

В сессии 2026-05-18 распиновку `video_out` на плате У-устройства зафиксировали в `docs/wiring.md` по одному фото без чёткой маркировки: белый=signal, жёлтый=shield. При пайке u1-переходника 2026-05-19 пятаки пересняли крупно, увидели на плате маркировку «+» (нижний пятак, жёлтый) и «−» (верхний пятак, белый), прозвонили мультиметром — оказалось обратное: **жёлтый=сигнал (CVBS), белый=GND**. `docs/wiring.md`, `docs/HANDOFF.md §7.4` и схема переходника исправлены. Сам спаянный переходник был сделан уже по правильной версии — юзер до коммита заметил расхождение по фото с маркировкой, пайки не пропали зря.

**Правило:** маркировка платы по одному фото без прозвонки — не источник истины для документа. Перед фиксацией distinct пин↔цвет↔сигнал в `docs/wiring.md` подтверждать мультиметром по конкретным пятакам, либо явно помечать запись `tentative, pending board check`.

**Проверка:** в commit-message правок `docs/wiring.md`, меняющих пин/цвет/сигнал, упоминать источник истины — `verified by continuity` или `verified by board silkscreen + photo + continuity`. Если правка идёт без свежей прозвонки — `tentative, pending board check`.

---

### 2026-05-18 (вечер) · Bench-инструмент эмулировал сценарий, которого в production нет

`bench/loopback.py` написан для закрытия §7.1 HANDOFF («auto-direction RS485 на 420k бод»). Архитектура: один Python-процесс, два потока, два USB-RS485 адаптера на одной Pi, три перемычки A↔A/B↔B/GND↔GND, pinger шлёт фрейм и ждёт echo. После 4 итераций фикса (`207ff66` adaptive deadline, `397ce65` cap+warning+flush, `060e52f` flush rollback, `23a994e` margin 2→20 мс) bench всё ещё давал нестабильные результаты — `echoer.bytes_received` скакал от 22 до 2073 байт между прогонами без изменений в коде/железе. В этот момент сделали raw тест без bench: `stty raw -echo` + `printf` 1000 байт в одном окне, `cat` в другом, 6 прогонов в обе стороны → **6/6 ровно 1000/1000 байт без потерь** на 1200 бод. Физика жива.

Только тогда увидели несоответствие: bench тестирует bidirectional ping-pong на одной RS485 шине через два адаптера на одной Pi. В production такого нет — `crsf_bridge.py` делает one-way streaming в каждую сторону (на u2-pi: ELRS Tx → Waveshare → bridge → UDP; на u1-pi: UDP → bridge → Waveshare → П1), между u1 и u2 IP-сеть, не общая шина. Auto-direction Waveshare на 420k в **одну** сторону — типичный CRSF use case, проверено индустрией. Bidirectional ping-pong через одну шину с двумя адаптерами — отдельный сценарий, и его нестабильность не блокирует production CRSF flow. 4 итерации фикса искали баги в скрипте, который мерил неактуальную для проекта нагрузку.

**Правило:** перед инвестицией в bench-инструмент явно описать (в module docstring): какой production data-flow он эмулирует и в чём отклонения. Если bench меряет нагрузку, которой в production нет — его результаты не могут служить gate-criterion для production-кода. Если хочется быть совсем уверенным в физике — параллельно с написанием скрипта сделать raw `stty` + `cat`/`printf` тест, это 30 секунд и снимает целый класс «призраков физики».

**Проверка:** в module-level docstring каждого `bench/*` скрипта должна быть секция «Соответствие production» с явным описанием отличий от реального flow. Если отличия есть и влияют на результат — секция «Limitations» с warning'ом (см. `bench/loopback.py` после `23a994e` как эталон).

---

### 2026-05-18 · crsf_bridge.py молча дропает входящий UDP пока UART закрыт

При smoke-тесте «UDP-пакет от партнёра дошёл или нет» через `nc -u` + `journalctl -u crsf-bridge@tx1 -f` ожидал увидеть `uart write failed` как индикатор приёма UDP. На самом деле в текущем коде `crsf_bridge.py` после `recvfrom` стоит `if data and ser is not None: ser.write(data)` — когда UART не открыт (адаптер ещё не подключён, активен retry-loop в `open_serial`), входящий UDP-пакет ЧИТАЕТСЯ из сокета и МОЛЧА выбрасывается. Никаких WARNING в журнале. Тест с «пустым» Pi (без Waveshare) даёт ложно-негативный результат: пакет реально прошёл сеть и ufw, но мы об этом не узнаем. Так появился phantom-bug «ufw блокирует 14551 на u2-pi» — на самом деле правила были в порядке, тест был просто невалиден.

**Правило:** для долгоживущих байтовых мостов с auto-reconnect — на каждую тихую ветку (drop пакета, EAGAIN на non-blocking IO, skip-без-записи) обязательно лог уровня DEBUG со счётчиком. Не INFO/WARNING (чтобы не спамить под нагрузкой), но достаточно чтобы `journalctl --priority=debug` или внутренняя статистика сразу показывали «работает, просто партнёр пустой». Симметрично — для smoke-тестов сетевых сервисов не доверять «тишине в логе», использовать `tcpdump`/`ss` либо явный echo-mode в самом приложении.

**Проверка:** после добавления DEBUG-логирования — `nc -u -w 1 <pi> 14550` без подключённого UART на принимающей стороне, потом `journalctl -u crsf-bridge@tx1 --priority=debug --since "1 min ago" | grep -c "udp.*drop"` должно вернуть ≥1.

---

### 2026-05-18 · scp с Windows: путаница окон между PowerShell и SSH-сессией

При попытке скопировать конфиг с NSU-pc на Pi запустил `scp C:\path\to\file.conf ubuntu@host:~/...` в терминале, где приглашение было `ubuntu@u1-pi:~$` (то есть внутри активной SSH-сессии). Bash увидел `C:\...` как удалённый-формат `<host>:<path>` из-за двоеточия, попытался открыть SSH на хост `C`, упал с `ssh: Could not resolve hostname c`. Повторял два раза, прежде чем понял, что окно не то. Та же ошибка ловится и для `Get-ChildItem`/`Copy-Item` в SSH-сессии, и для `nano`/`cat` Linux-команд в PowerShell.

**Правило:** scp/rsync с Windows-машины — ТОЛЬКО из локального PowerShell (приглашение `PS C:\...>`), никогда из SSH-сессии. При выдаче таких команд в мануале/чате — рядом явно «**в PowerShell**» или «**на Pi**». Перед каждым `scp` смотреть на префикс приглашения: `PS ` → можно, `user@host:~$` → открыть новое локальное PowerShell-окно.

**Проверка:** мнемоника на свою сторону — «scp идёт ОТ Windows К Linux, значит запускается ОТ Windows». Если ошибка `Could not resolve hostname c` (или любая односимвольная буква) при scp — это 100% знак, что путь начался с буквы диска и запущен из bash.

---
### 2026-05-18 · CRLF в shebang ломает запуск bash-скрипта на Linux после `git pull`

После `git pull` на u2-pi `./install.sh` не стартовал: `bash: ./install.sh: /bin/bash^M: bad interpreter: No such file or directory`. Причина: репо редактируется на Windows без `.gitattributes`, git хранил/чекаутил `install.sh` с CRLF, на Linux ядро при exec'е shebang-строки видит `#!/bin/bash\r` и ищет интерпретатор `/bin/bash^M` (которого нет). Разово лечилось `sed -i 's/\r$//' install.sh && chmod +x install.sh`, окончательно — `.gitattributes` с явными правилами EOL.

**Правило:** в любом репо, который редактируется на Windows и исполняется на Linux — обязателен `.gitattributes` с явным `text eol=lf` для shell/python и `text eol=crlf` для PowerShell. На `core.autocrlf` пользователя не полагаться (у каждого свой). Если файл закоммичен до добавления `.gitattributes` с неправильным EOL — `git add --renormalize . && git commit`.

**Проверка:** на Linux после `git pull` — `file install.sh` показывает `Bourne-Again shell script, ASCII text executable` БЕЗ суффикса `with CRLF line terminators`. Регрессия: `head -1 install.sh | xxd | grep -q '0d 0a'` должно ничего не вернуть (нет CRLF в первой строке).

---

### 2026-05-18 · wg-easy дефолт `AllowedIPs=0.0.0.0/0` на Windows-клиенте ломает локалку

Импорт сгенерированного wg-easy конфига в WireGuard for Windows (NSU-pc, peer `10.8.0.5`): дефолтный `AllowedIPs = 0.0.0.0/0` создал второй default route через туннель, локальная сеть и обычный интернет отвалились (весь трафик ушёл на VPS NL). Симметрично уроку от 2026-05-18 про Pi-клиент: дефолт wg-easy одинаково небезопасен с любой стороны, не только на Pi.

**Правило:** ЛЮБОЙ импортированный из wg-easy конфиг (Pi, Windows, Android — без разницы) править вручную перед подключением: `AllowedIPs = 10.8.0.0/24` (только VPN-подсеть), `PersistentKeepalive = 15`. Никогда не подключаться "из коробки".

**Проверка:** на Windows после подключения — `route print -4 | findstr "  0.0.0.0  "` должен показывать default route на физический gateway, не на WG-интерфейс. На Linux — `ip route show default` не должен указывать на `wg0`. Универсально: `wg show wg0 allowed-ips` — только `10.8.0.0/24`.

---

### 2026-05-18 · Pi 5 Max + joshua-riek: пустой SPI + только NVMe → splash виснет

Первая попытка загрузить Orange Pi 5 Max с NVMe (Ubuntu 24.04 от joshua-riek) висла на splash "Orange Pi" — Linux не догружался. Причина: SPL на NVMe не способен догрузить Linux без U-Boot в SPI — PCIe инициализируется именно там, а из коробки на Pi 5 Max SPI пустой. Решение: сначала загрузиться с SD с той же прошивкой, выполнить `sudo u-boot-install-mtd`, вынуть SD и грузиться с NVMe.

**Правило:** на Pi 5 Max (RK3588) при NVMe-only установке — обязательно сначала прошить SPI U-Boot'ом через SD + `u-boot-install-mtd`. Голый NVMe без U-Boot в SPI грузиться не может (PCIe инициализируется из SPI).

**Проверка:** после `u-boot-install-mtd` — `sudo dd if=/dev/mtd0 bs=1M count=16 status=none | md5sum` совпадает с MD5 исходного образа U-Boot (см. также соседний урок про Rockchip SPI offset).

---

### 2026-05-18 · Rockchip SPI: первые 32K служебные, реальный idbloader на 0x8000

При проверке прошивки SPI команда `head -c 16 /dev/mtd0` возвращала нули — выглядело как пустая/битая прошивка. На самом деле первые 32K на Rockchip SPI — служебная область, реальный idbloader начинается с offset `0x8000` с заголовком `RKNS`.

**Правило:** не делать вывод о целостности Rockchip SPI flash по первым байтам — нули в начале это нормально. Проверять MD5 целиком (`md5sum file.img` vs `sudo dd if=/dev/mtd0 bs=1M count=16 | md5sum`, `count` по реальному размеру SPI flash).

**Проверка:** обе хэш-суммы должны совпадать. Не совпадают — перепрошить через `u-boot-install-mtd`. Заодно валидировать header: `sudo dd if=/dev/mtd0 bs=1 skip=32768 count=4 status=none | xxd` должно показать `RKNS`.

---

### 2026-05-18 · wg-easy дефолты клиентского пира небезопасны для нашего сценария

При генерации клиентского конфига в веб-UI wg-easy по умолчанию вписывается `AllowedIPs = 0.0.0.0/0` и `PersistentKeepalive = 0`. Для нашего сценария (Orange Pi как обычный пир в /24 подсети моста, не дефолт-роут всего трафика) `0.0.0.0/0` отправляет в туннель **весь** трафик — ломает доступ к локальной сети и CPE710. `PersistentKeepalive = 0` отключает keepalive — NAT-таблица на пути за 60–180 секунд протухает, туннель тихо перестаёт работать без явной ошибки.

**Правило:** после скачивания конфига из wg-easy всегда править вручную: `AllowedIPs = 10.8.0.0/24` (или нужная подсеть VPN-моста, без `0.0.0.0/0`) и `PersistentKeepalive = 15`. Дефолтам wg-easy для этого проекта не доверять.

**Проверка:** `sudo wg show wg0 allowed-ips` — только VPN-подсеть, не `0.0.0.0/0`. После 60+ секунд молчания `ping` через туннель остаётся рабочим — keepalive держит NAT.

---

### 2026-05-18 · Orange Pi 5 Max имеет один 2.5GbE, не два

При планировании сетевой схемы предполагал у Pi 5 Max два Ethernet-порта (путал с Pi 5 Plus). На самом деле у Pi 5 Max — **один** 2.5GbE с именем `enP3p49s0` (на joshua-riek 24.04). План разделять трафик CPE710 / management по разным портам — невозможен на этой плате.

**Правило:** для Pi 5 Max закладывать один сетевой интерфейс. Перед редактированием netplan / `install.sh` IFACE-логики — всегда сверяться с `ip -br link`, а не с памятью про "Pi 5 имеет столько-то портов". Имя интерфейса на joshua-riek меняется от модели платы (`end0` на Pi 5, `enP3p49s0` на Pi 5 Max).

**Проверка:** `ip -br link | awk '$1 != "lo"'` на u2-pi показывает один интерфейс `enP3p49s0`. `install.sh` определяет IFACE автоматически (`ip -br link | awk '$2 == "UP"'`), переопределение — через `IFACE=...` env.

---

### 2026-05-18 · Waveshare USB-TO-RS485 (B) на CH343G → /dev/ttyACMx, не /dev/ttyUSBx

При подключении Waveshare USB-TO-RS485 (B) к Orange Pi 5 Max (Ubuntu 24.04) адаптер был распознан как USB CDC ACM device (драйвер `cdc_acm`), пришёл как `/dev/ttyACM0`, а не `/dev/ttyUSB0`. Vendor:Product = `1a86:55d3` (WCH CH343G). Прежние udev-правила и env-файлы `install.sh` ожидали `ttyUSB*` под CP2102N `10c4:ea60` — на CH343G не сработают вообще.

**Правило:** для CH343G использовать драйвер `cdc_acm` и имена `/dev/ttyACMx`; udev `SYMLINK+="ttyACM-CRSFx"`, env `SERIAL_DEV=/dev/ttyACM-CRSFx`. `ttyUSB*` валидно только для CP210x/CH340G — это другие чипы. При смене модели адаптера всегда сверяться с `dmesg` / `ls /dev/tty*`, не копировать имена из старых правил.

**Проверка:** после подключения адаптера — `ls /dev/ttyACM*` и `udevadm info -q property /dev/ttyACM0 | grep -E 'ID_USB_DRIVER|ID_VENDOR_ID|ID_MODEL_ID'` (ожидаем `cdc_acm`, `1a86`, `55d3`). Серийник конкретного адаптера на u2-pi — `5A98051690`. Пользователь должен быть в группе `dialout`: `groups ubuntu | grep -w dialout`.

---

### 2026-05-13 · `PackageNotFoundError: u1u2-bridge` при `importlib.metadata.version()`

При планировании CLI-флага `--version` собирался использовать `importlib.metadata.version("u1u2-bridge")`, но проверка показала `PackageNotFoundError`: в `pyproject.toml` не было `[build-system]`, поэтому `uv sync` ставил только зависимости, а сам проект не устанавливался как distribution. Исправлено добавлением `[build-system] requires = ["hatchling"]` и `[tool.hatch.build.targets.wheel] packages = ["common"]`, после чего `uv sync` поставил `u1u2-bridge==0.1.0` editable.

**Правило:** перед использованием `importlib.metadata.*` (в коде или ещё на этапе плана) — однострочной проверкой убедиться, что пакет реально установлен в `.venv`. Если нет — сначала `[build-system]` + `uv sync`, либо предусмотреть `try/except PackageNotFoundError` с фолбэком.

**Проверка:** `uv run python -c "from importlib.metadata import version; print(version('u1u2-bridge'))"` должно печатать актуальную версию, не падать. Регрессионный тест: `tests/unit/test_crsf_bridge.py::TestGetVersion::test_returns_nonempty_string`.

---

### 2026-05-13 · `uv trampoline failed to canonicalize script path` после переезда проекта

При перемещении папки проекта с `Desktop\files\` в `Documents\Projects\` команда `mypy` упала с ошибкой *uv trampoline failed to canonicalize script path*. Причина — на Windows внутри `.venv\Scripts\` лежат тонкие .exe-трамплины (`mypy.exe`, `pytest.exe`, и т.д.), внутри которых **жёстко вшит абсолютный путь** к месту установки. После переезда они указывают на несуществующий путь.

**Правило:** при переносе папки проекта между директориями — сначала сносить `.venv` (`Remove-Item -Recurse -Force .venv`), затем пересоздавать через `uv sync --all-groups` в новом месте. Не пытаться "перенести" виртуальное окружение целиком.

**Проверка:** обязательный прогон `.\verify.ps1` сразу после переезда. Если красное — `.venv` поломан, пересоздать.

---

<!--
Будущие реальные инциденты с железом и кодом. Кандидаты из HANDOFF:
- RS485 auto-direction на 420k бод (если не сработает) — §7.1
- Имя сетевого интерфейса в install.sh (end0 vs eth0) — §7.2
- udev ID для CH343G после получения адаптеров — §7.3
- WireGuard порт UDP/51820 — проход через CPE710 в bridge режиме — §7.6
-->
