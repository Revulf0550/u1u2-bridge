# CLAUDE.md

> Живая память проекта. Эволюционирует с каждым PR и инцидентом.
> Принцип: если факт можно получить через `cat`, `ls`, `grep` — он не здесь.

---

## Process

- **Перед любым хэндоффом / передачей в новый чат — сначала ПОЛНЫЙ АУДИТ:**
  перечитать релевантные прошлые чаты и сверить с фактическим состоянием
  системы (репо, железо), и только потом резюмировать. Хэндофф «по памяти»
  без сверки запрещён. Цель — не потерять рабочие конфигурации, ключевые
  решения и **допущенные ошибки** (чтобы не повторять). Аудит уже однажды
  спас хэндофф: черновик гнал чинить `kmssink`, мёртвый на этой плате.

---

## Project Context

- **Продукт:** беспроводная замена 8-жильного кабеля между двумя устройствами FPV-наземки (У1 — мастер-пульт с **RadioMaster Boxer ELRS** (заменил TX12) + видео-передатчиком к очкам, У2 — выносная база с 2× ELRS-передатчиками и VRX). Дистанция до 1 км, через готовый Wi-Fi PtP мост TP-Link CPE710.
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
- **Адресация двухслойная (проектная).** Локально: `192.168.1.0/24` (CPE710 LAN). Туннель: `10.10.0.0/24` (WireGuard поверх). После разворачивания CPE710 — env-файлы переключить с `192.168.1.x` на `10.10.0.x`. **Текущее состояние (2026-06-05):** Режим №2: cutover на CPE-радио ВЫПОЛНЕН (рантаймом), обе Pi на 192.168.1.x по радио, CRSF+видео+дрон подтверждены live; install.sh это пока НЕ воспроизводит (2d); WG-off обязателен для моста.
- **WireGuard `PersistentKeepalive = 15`** на клиентской стороне. Без него NAT-таблица протухает (для CPE710 — собственного NAT'а; для bench-WG через интернет — NAT'а домашнего роутера).
- **MTU зависит от транспорта (env `MTU` в `video_tx.sh`).** Дефолт `rtph264pay mtu=1200` — под bench (wg через интернет, RTT 180 мс). Для CPE710 PtP (короткий линк, RTT 3–7 мс) поднимать до `1400` — оставляем 100 байт на Wi-Fi headers + WireGuard 60–100 байт overhead.

### Архитектурный roadmap для подключения пульта

Два варианта подключения пульта: №1 CRSF через JR-bay (текущий), №2 USB-HID (план B, «будем делать»). Детали и статусы — в `docs/roadmap/`: joystick-2-usb-hid.md, ctrl-channel.md, jitter-latency-tuning.md, production-hardening.md.

### GStreamer — низкая латентность

- **Только `mpph264enc` / `mppvideodec`** на Orange Pi 5 (аппаратный H.264 через VPU RK3588). Не `v4l2h264enc` (медленнее на 7–10 мс). Зависимость: пакет `gstreamer1.0-rockchip1` из репо joshua-riek.
- **`profile=66`** (Baseline, нет B-кадров) задаётся property энкодера, **не** capsfilter'ом `video/x-h264,profile=baseline` — последний роняет caps-негоциацию (mpph264enc отдаёт `Baseline` с заглавной, см. Lessons & Incidents 2026-06-03). GOP=15 для быстрого recovery после потерь.
- **`rtpjitterbuffer latency=<env> drop-on-latency=false do-lost=true`** под транспорт. Дефолт `latency=500` в `video_rx.sh` (env `JITTER_LATENCY`) — под bench-WG через интернет (RTT 180 мс). Для CPE710 PtP (3–7 мс) снижать до 30–50 — это основной knob для glass-to-glass latency. `drop-on-latency=false`: пакеты приходят пачками, дропать поздние смысла нет.
- **HDMI вывод через `cage + waylandsink sync=false`.** `kmssink` на joshua-riek + RK3588 сломан VOP2-багами (`wait pd0 off timeout`, `unexpected power on pd5`) — не использовать. cage — headless Wayland-композитор; `install.sh` разворачивает `/run/user/0` через `tmpfiles.d` и держит u1 на `multi-user.target` без display-manager'а.
- **`v4l2src` без `io-mode=`.** Дефолт GStreamer (mmap) — самый совместимый. `io-mode=4` (userptr) известно ломается на дешёвых UVC (EasyCAP-клоны); ставить только при доказанном выигрыше латенции на конкретной модели грабера, не по умолчанию.
- **`udpsink sync=false async=false`** — иначе GStreamer пытается синхронизировать по часам, добавляет задержку.

### Hardware и периферия

- **udev-правила для стабильных имён USB-устройств.** `/dev/ttyUSB-CRSF1`, `/dev/ttyUSB-CRSF2` через `SYMLINK+=` по серийному номеру чипа. Никогда не использовать `/dev/ttyUSB0`/`ttyUSB1` в env-файлах — порядок меняется при перезагрузке.
- **USB↔RS485 auto-direction.** Полагаемся на аппаратное переключение TX-detect (Waveshare на SP485EEN). Если на 420k бод не сработает — fallback на ручное управление через RTS + `fcntl.ioctl(TIOCSRS485)`. Открытый вопрос, см. `docs/HANDOFF.md` §7.1.
- **Сетевой интерфейс Orange Pi 5 (joshua-riek) — `end0` на Pi 5, `enP3p49s0` на Pi 5 Max.** В Armbian может быть `eth0` или `enp1s0`. `install.sh` определяет имя автоматически через `ip -br link | awk '$1 != "lo" && $2 == "UP" {print $1; exit}'`. **Текущий стенд (2026-06-03):** u2-pi = Pi 5 Max, iface `enP3p49s0`.

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
| Статус CRSF-моста | `systemctl status crsf-bridge@p1` (u1) / `crsf-bridge@elrs` (u2) |
| Логи CRSF live | `journalctl -u crsf-bridge@p1 -f` (u1) / `crsf-bridge@elrs -f` (u2) |
| Статус видео | `systemctl status video-tx` (У2) или `video-rx` (У1) |
| Тест локальной сети | `ping -i 0.2 192.168.1.20` |
| Тест туннеля | `ping 10.10.0.2` (после WireGuard) |
| Проверка RKMPP | `gst-inspect-1.0 mpph264enc` |
| Preflight CRSF (без запуска моста) | `uv run python -m common.crsf_bridge --serial /dev/ttyUSB-CRSF1 --listen 0.0.0.0:14552 --peer 192.168.1.20:14552 --dry-run` |
| Валидация env-файла CRSF | `uv run python -m common.crsf_bridge --check-config /etc/u1u2-bridge/crsf-p1.env` (u1) / `crsf-elrs.env` (u2) |

### Зависимости (Python, локально)

| Что | Команда |
|---|---|
| Установить | `uv sync --all-groups` |
| Добавить runtime-dep | `uv add <package>` |
| Добавить dev-dep | `uv add --dev <package>` |

---

## Протокол хэндоффа (обязательный гейт)

Память по умолчанию УСТАРЕВШАЯ: компакт-саммари, снимок /mnt/project, «помню из сессии» отстают от репо. Перед ЛЮБЫМ хэндоффом — сначала факт, потом текст.

ГЕЙТ (вывод на руках ДО первой строки хэндоффа):
1. git: HEAD + `status -sb` — что в origin.
2. live: `is-active` 6 юнитов + рантайм-конфиг (env PEER, video §7b/override) — SSH через Claude Code (WG-on) или §0-батч PowerShell (WG-off).
3. история: `conversation_search` по последним релевантным чатам — закрытые этапы, решения, коммиты.
4. стале-флаг: явно отметить, какие in-context артефакты отстают.

Хэндофф собирается ИЗ выводов 1–4; каждое крупное утверждение — с источником (git/live/chat). Факт недоступен → запросить §0 у пользователя и ЖДАТЬ; «по памяти» не писать.

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

> Закрытые/исторические инциденты (bring-up UART7/ELRS/прошивка, SPI/NVMe, packaging, scp/CRLF и пр.) вынесены в `docs/LESSONS-ARCHIVE.md`.

### 2026-06-06 · u1 не поднимает Ethernet-линк напрямую в CPE-AP — нужен свитч на Конце A
u1 (RK3588 GMAC) не линкуется напрямую в LAN-порт пассивного PoE-адаптера CPE-AP даже с заведомо рабочими кабелями (доказано перебором). ARDOR и u2 линкуются в свои CPE напрямую без проблем → несовместимость авто-негоциации именно сетевухи u1 ↔ пассивный PoE CPE-AP. Мини-свитч (активный партнёр по линку) поднимает линк и делит один LAN-порт между u1 и ARDOR.
**Правило:** на Конце A держать мини-свитч между LAN-портом PoE-адаптера CPE-AP и {u1 + ARDOR} — постоянно, в поле тоже. Технику включать ТОЛЬКО в порт LAN адаптера, никогда в POE / в сам CPE (пассивное напряжение спалит NIC). Конец B (u2 → CPE-Client) — напрямую.
**Проверка:** лампа линка на порту u1 горит, ssh ubuntu@192.168.1.20 отвечает. Нет линка u1 при живых u2/ARDOR → u1 идёт мимо свитча.

---

### 2026-06-06 · Почти все «отказы» — провода/USB-контакт, не софт
Серия инцидентов этой сессии оказалась физикой, не кодом: u1 CH340 не определялся (dmesg error -71) из-за плохого USB-переходника; ARDOR не видел мост — донгл Ethernet 3 не воткнут (пропал из ipconfig целиком); u2 video-tx в crash-loop без подключённого грабера (/dev/video0 отсутствовал); u1 «недоступен, но шлёт CRSF» — полу-битый Ethernet при перетыках на Конце A.
**Правило:** при любом «отказе» проверять физику ПЕРВОЙ, до софта — на Pi: lsusb / ls /dev/{video0,ttyUSB0,ttyS7}; на ARDOR: Get-NetAdapter (донгл при выдёргивании пропадает целиком, не «отключён»); лампы линка. Сервисный crash-loop без устройства = подключить устройство, а не чинить юнит.
**Проверка:** перед правкой конфига/кода — устройство присутствует, донгл в ipconfig с .50, линк горит. Нет — это физика.

---

### 2026-06-06 · Хэндофф собран по памяти — перепроверка нашла, что код уже в GitHub
Хэндофф писался из памяти/компакт-саммари: код показан как «pending codify», хотя Этапы 2d/D давно запушены (HEAD 51bfa84), переключатель — готовый switch-mode.ps1. Правило 5 поймало постфактум. Паттерн повторяется: аудит идёт ПОСЛЕ черновика.
**Правило:** хэндофф собирается ТОЛЬКО из свежего факта (git HEAD/status + live is-active 6 юнитов + conversation_search), не из памяти/саммари/снимка /mnt/project — они отстают на итерации. Аудит — предусловие, не проверка после. Каждое крупное утверждение помечать источником (git/live/chat).
**Проверка:** нет свежего §0-вывода на руках → хэндофф не начинать.

---

### 2026-06-05 · video.env писался только в direct → дыра переключателя режимов
install.sh §7b писал /etc/u1u2-bridge/video.env (видео-peer u2) только при TRANSPORT=direct; в tunnel полагался на fallback PEER_HOST=10.8.0.6 в video_tx.sh. При switch direct→tunnel старый video.env=192.168.1.20 оставался на диске и уводил видео не туда.
**Правило:** peer-адрес (CRSF и видео) писать в env для ВСЕХ транспортов из единого источника ($CRSF_PEER), не полагаясь на неявный fallback в скрипте. Смена TRANSPORT обязана перезаписывать ВСЕ peer-конфиги, а не только CRSF.
**Проверка:** после install.sh TRANSPORT=X на u2 — cat /etc/u1u2-bridge/video.env показывает адрес u1 для режима X (direct→192.168.1.20, tunnel→10.8.0.6).

---

### 2026-06-05 · netplan Pi location-adaptive → switcher netplan НЕ трогает
На обеих Pi два netplan: 99-u1u2-bridge.yaml (статика 192.168.1.x на zz-all-en) + 50-cloud-init.yaml (dhcp4:true на en*/eth*). Мёрджатся по ключу → интерфейс имеет И статику, И DHCP. На мосту (DHCP-сервера нет) живёт статика; дома DHCP даёт интернет+маршрут для WG, статика висит безвредным вторым адресом. Поэтому переключение №1↔№2 не требует менять netplan.
**Правило:** switch-mode.ps1 деплоит install.sh с SKIP_NETPLAN=1 в ОБОИХ режимах — netplan не трогать (иначе риск lockout безмониторной u2). Сеть адаптируется к месту сама.
**Проверка:** ls /etc/netplan/ = 50-cloud-init.yaml + 99-u1u2-bridge.yaml; на мосту ip route без default, дома — с default от DHCP.

---

### 2026-06-05 · Скачанный .ps1 блокируется ExecutionPolicy (Mark-of-the-Web)
switch-mode.ps1, полученный скачиванием, нёс Zone.Identifier (MOTW) → при RemoteSigned PowerShell отказал: "not digitally signed ... cannot run". Не баг скрипта.
**Правило:** ps1-файлы, доставленные скачиванием, разблокировать Unblock-File .\script.ps1 перед запуском (или отдавать ops-скрипты записью в репо через Claude Code, минуя загрузку — тогда MOTW нет). Системную ExecutionPolicy не менять.
**Проверка:** Get-Item .\script.ps1 -Stream Zone.Identifier после Unblock-File бросает "stream not found"; скрипт запускается.

---

### 2026-06-05 · WG on/off — взаимоисключающие режимы (мост vs интернет)
ARDOR ходит в интернет/к ассистенту/в Claude Code через WireGuard. WG-on = есть интернет+ассистент+Claude Code, но kill-switch режет мост 192.168.1.x; WG-off = мост доступен, но Claude Code/ассистент недоступны.
**Правило:** для моста — БАТЧ: WG-off → команды в обычном PowerShell с Start-Transcript → WG-on → прислать транскрипт ассистенту. Claude Code (нужен интернет) — только репо/git при WG-on. (Дополняет урок про «Общий сбой» от kill-switch.)
**Проверка:** при поднятом WG ssh/ping на 192.168.1.x не идут; команды к Pi гонять только при WG-off, фиксируя вывод в файл.

---

### 2026-06-05 · install.sh обрывался оффлайн на apt → флаг SKIP_APT
install.sh §1 гнал apt update/install (нужен интернет) каждый запуск; Pi в Режиме №2 и в поле — без интернета → set -e обрывал скрипт.
**Правило:** Режим №2 / поле = оффлайн-среда; install.sh обязан запускаться оффлайн. Редеплой там: sudo SKIP_APT=1 ... ./install.sh (пакеты уже стоят), RKMPP-проверка остаётся.
**Проверка:** sudo TRANSPORT=direct SKIP_NETPLAN=1 SKIP_APT=1 ... ./install.sh без сети; в логе «SKIP_APT: пропускаю apt».

---

### 2026-06-05 · install.sh не рестартит сервисы → редеплой не применяет конфиг к running
В install.sh нет ни одного systemctl restart, только enable --now (= no-op на активном юните). Редеплой кладёт env/юниты на диск, но живые сервисы крутят старый конфиг до ручного restart/ребута.
**Правило:** редеплой неразрушающий, но НЕ применяет новый конфиг к работающим сервисам — нужен явный systemctl restart (моргнёт CRSF → дрон ВЫКЛ) или ребут.
**Проверка:** после редеплоя сверять pgrep -af gst-launch | grep host= и journalctl — отражают ли новый peer.

---

### 2026-06-05 · Оффлайн-деплой на Pi = git archive + scp (клон на Pi устарел)
Клоны ~/u1u2-bridge на обеих Pi застряли на a8573d6 и не подтягиваются (нет интернета на мосту). Запуск клонского install.sh = старый код + apt-облом.
**Правило:** не запускать install.sh из устаревшего клона. Деплой текущего HEAD: git archive --format=tar HEAD → scp → свежий ~/u1u2-deploy → ./install.sh с SKIP_APT.
**Проверка:** перед запуском убедиться, что разворачиваемый код = HEAD; после — grep маркеров в /opt (udp_drop, waylandsink, 640).

---

### 2026-06-05 · WG kill-switch режет локальный мост (ping/ssh «Общий сбой»)
WireGuard на ARDOR с AllowedIPs=0.0.0.0/0 ставит WFP-фильтр, режущий весь не-туннельный трафик, включая 192.168.1.x. Симптом: интерфейс Up, IP Preferred, маршрут верный — а ping/ssh дают «Общий сбой» (не таймаут).
**Правило:** для работы с локальным мостом WG деактивировать; «Общий сбой» (не «таймаут») = локальный фильтр/маршрут, не сеть.
**Проверка:** при выключенном WG `ping -S <local-ip> <peer>` проходит; при включённом — «Общий сбой».

---

### 2026-06-05 · UFW тихо режет SSH после смены источника (cutover на мост)
После cutover ARDOR пошёл к u2 с нового 192.168.1.50; u2 UFW (active) пускал 22 только с 10.8.0.x/192.168.31.x → SSH timeout при живом ping. Та же болезнь, что 2026-05-24, но на порту 22.
**Правило:** при смене источника открывать UFW на приёмнике под новый source для КАЖДОГО порта (данные И 22); проверять факт (ssh/поток), не is-active.
**Проверка:** `ssh ... ubuntu@<bridge-ip>` отвечает; `ufw status | grep 22` содержит подсеть моста.

---

### 2026-06-05 · Откат в рабочий режим может требовать физического префикса
После физического cutover откат в WG-режим (№1) требует сперва вернуть кабели Pi в сеть с интернетом — на мосту интернета нет, WG не встанет.
**Правило:** в процедуре отката проверять транспортные предпосылки узла (есть путь к endpoint?), не только конфиг.
**Проверка:** перед `wg-quick up` — `ping <endpoint>` с узла проходит.

---

### 2026-06-05 · Не верить маленькому tcpdump-сэмплу при оценке RTP
`-c 10` за ~100 мс попал в межкадровый промежуток (23-байтные пакеты) → ложная тревога «видео мёртвое»; счёт за ≥5 c показал здоровый поток.
**Правило:** оценка RTP-видео — счёт пакетов / гистограмма размеров за ≥5 c, не `-c 10`.
**Проверка:** `timeout 10 tcpdump -ni any udp port 5600 | wc -l` даёт сотни+ пакетов.

---

### 2026-06-05 · CBR маскирует no-signal (поток ≠ живой контент)
Поток ~2.5 Mbps идёт и на статичной no-signal картинке; наличие RTP не доказывает живого видео.
**Правило:** «живой контент» подтверждать движением/дроном на мониторе, не фактом наличия потока.
**Проверка:** картинка на мониторе u1 меняется при движении в кадре дрона.

---

### 2026-06-04 · cage от root под systemd работает без VT/PAM-обвязки

A2: проверяли, заведётся ли `video-rx.service` (cage+waylandsink) в service-mode на `multi-user.target`, где `getty@tty1` держит VT1, а графического seat0 нет. Минимальный юнит (точная копия рендера: `Type=simple` + `ExecStart=…cage -- gst-launch…`, `XDG_RUNTIME_DIR=/run/user/0`) стартовал и вывел картинку на HDMI. В журнале единственная ошибка `[libseat] logind.c: Could not get primary session for user: No data available` — НЕкритична: wlroots падает на builtin/direct backend и берёт DRM-master напрямую от root (`fuser /dev/dri/card0` показывает cage). `fgconsole` остаётся =1, но KMS-вывод cage перекрывает текстовую консоль. Ни `TTYPath`, ни `StandardInput=tty`, ни `PAMName=login`, ни `Conflicts=getty@tty1` не понадобились.

**Правило:** на joshua-riek + RK3588 для headless cage под systemd достаточно минимального юнита от root с `XDG_RUNTIME_DIR=/run/user/0`. Ошибку `libseat logind: Could not get primary session` игнорировать (fallback на builtin backend). VT/PAM-обвязку добавлять только если экран чёрный/мусор/остаётся текстовая консоль — здесь не потребовалось.

**Проверка:** после `systemctl start <cage-unit>` — `systemctl show <unit> -p NRestarts --value` = 0 (нет петли) И `sudo fuser -v /dev/dri/card0` показывает `cage` как держателя DRM-master. Картинку на HDMI подтверждать глазами (caps-негоциация `waylandsink` ≠ пиксели на экране, см. соседний урок про NV12).

---

### 2026-06-04 · `waylandsink` не ест NV12 напрямую — `videoconvert` обязателен

Микро-выигрыш «убрать `videoconvert` перед `waylandsink` в `video_rx.sh`» отметён: на live (`videotestsrc`) без него — чёрный экран. `mppvideodec` отдаёт `NV12`, но `waylandsink` согласует только `RGBx` (видно в `-v`: с `videoconvert` появляется `GstWaylandSink.sink caps … format=RGBx`, без него строки caps синка нет, при этом `not-negotiated` не печатается — тихий caps-разрыв). Не пробовать повторно.

**Правило:** в RX-цепочке RK3588 `mppvideodec ! videoconvert ! waylandsink` — `videoconvert` (NV12→RGBx) обязателен, не удалять ради латенси.

**Проверка:** `grep "GstWaylandSink.*sink: caps" rx.log` непусто (format=RGBx). Пусто при живом pipeline без ошибок → caps-разрыв, на мониторе чёрный экран.

---

### 2026-06-03 · `! video/x-h264,profile=baseline` после `mpph264enc` вешает pipeline

В `u2/video_tx.sh` capsfilter `video/x-h264,profile=baseline` стоял сразу после `mpph264enc`. Энкодер отдаёт caps с `profile=Baseline` (с заглавной), фильтр требует `baseline` (строчная) → caps-негоциация молча падает, pipeline переходит в PLAYING без ошибки, downstream-пады без caps, `udpsink` отправляет 0 пакетов. Две сессии ушли на ложные гипотезы (RKMPP завис, wg сломан, MTU, грабер сломан) пока не догадались убрать capsfilter.

**Правило:** за `mpph264enc`/`mppvideodec` НЕ ставить жёсткий `video/x-h264,profile=...` capsfilter — профиль задаётся property энкодера (`profile=66`), capsfilter запрещён. Мета-правило: 0 пакетов на `udpsink` без ошибок в логе + downstream-пады без caps в `GST_DEBUG=4` → искать caps-разрыв в capsfilter перед синком, а не в сети.

**Проверка:** `sudo tcpdump -i wg0 'udp port 5600' -c 20` на TX-стороне ловит пакеты ≤2 сек после старта pipeline. Если 0 пакетов и нет ошибок в логе — caps-разрыв перед udpsink.

---

### 2026-06-03 · «RKMPP-энкодер застрял после перезапусков» — ложный след

Гипотеза «за 6+ перезапусков gst-launch RKMPP не освободил ресурсы, нужен reboot u2» отъела часы. После `sudo reboot u2` поведение идентичное: caps есть, пакетов нет. Реальная причина — `profile=Baseline` vs `baseline` capsfilter (см. соседний урок).

**Правило:** RKMPP encoder/decoder не «застревают» между запусками `gst-launch`. Перед перезагрузкой или обвинением аппаратного кодека сначала проверить caps-негоциацию: `GST_DEBUG=4`, искать `not-negotiated` или отсутствие caps на src-падах downstream.

**Проверка:** `GST_DEBUG=4 gst-launch-1.0 ... 2>&1 | grep -E 'not-negotiated|caps = NULL'` — при здоровом pipeline пусто.

---

### 2026-06-03 · kmssink не работает на joshua-riek + RK3588 (VOP2 driver bugs)

`kmssink force-modesetting=true` под sudo на `multi-user.target` падает с ошибками VOP2-драйвера в dmesg: `*ERROR* wait pd0 off timeout`, `*ERROR* unexpected power on pd5`, `i2c read err`. Картинки на HDMI нет, `gst-launch` своих ошибок не пишет. Это противоречит ранее зафиксированному правилу «kmssink — самая короткая цепочка для HDMI на Orange Pi 5» в Architecture/GStreamer этого же файла; раздел Architecture обновлён в этом же коммите.

**Правило:** на joshua-riek + RK3588 для HDMI-вывода — `cage -- gst-launch-1.0 ... ! waylandsink sync=false` (headless Wayland-композитор). `kmssink` не использовать до восстановления VOP2-драйвера в апстриме.

**Проверка:** `journalctl -k --since '5 min ago' | grep -iE 'vop2|wait pd0 off timeout|unexpected power on pd5'` — пусто после старта video-rx.

---

### 2026-06-03 · `waylandsink` требует `sync=false` на высоколатентном линке

При приёме RTP H.264 через wg-туннель (RTT 180 мс) `waylandsink` без `sync=false` дропает кадры — clock-sync считает все пакеты опоздавшими относительно PTS. С `sync=false` рендерит сразу по приходу декодированного буфера.

**Правило:** `waylandsink sync=false` для любого realtime-приёма UDP RTP. `sync=true` оставлять только для воспроизведения локальных файлов, где PTS осмыслен относительно clock'а.

**Проверка:** `GST_DEBUG=basesink:4 ./video_rx.sh 2>&1 | grep -ciE 'rendering too late|qos|drop'` = 0 за 10 секунд устойчивого приёма.

---

### 2026-06-03 · UVC-грабер Arkmicro 18ec:5555 — EasyCAP-клон, не MS2130

В HANDOFF.md был записан MS2130 (HDMI capture). По факту подключён Arkmicro 18ec:5555 «USB2.0 PC CAMERA» — дешёвый EasyCAP-клон с CVBS-входом. Чип отдаёт только 640x480 MJPG, YUYV не поддерживает, `VIDIOC_ENUMSTD` возвращает `Inappropriate ioctl for device`, UVC Extension Controls для PAL/NTSC switch нет. Дефолт `VIDEO_W/H/FPS` в `video_tx.sh` стоял 720/576/25 (PAL) — давал `not-negotiated` без понятной ошибки.

**Правило:** перед написанием GStreamer-pipeline под USB UVC — `lsusb` (vendor:product) + `v4l2-ctl --device=/dev/videoN --list-formats-ext` (реальные форматы и резолюшены). Дефолты в скриптах ставить по факту устройства, не по предполагаемой модели из BOM.

**Проверка:** `v4l2-ctl --device=$VIDEO_DEV --list-formats-ext | grep -E 'Pixel Format|Size'` показывает поддерживаемые комбинации до запуска pipeline.

---

### 2026-06-03 · `io-mode=4` (userptr) в `v4l2src` убран превентивно

В `video_tx.sh` стоял `v4l2src device=$DEV io-mode=4` исторически из MS2130-туториалов. Это известно проблемная опция для дешёвых UVC: userptr-buffers требуют от драйвера поддержки, которой у клонов EasyCAP часто нет. В live на Arkmicro 18ec:5555 с `io-mode=4` не проверяли — убрали в рамках стабилизации pipeline. Без `io-mode` рабочая цепочка собирается, кадры идут.

**Правило:** не задавать `io-mode` у `v4l2src` без необходимости — пусть GStreamer выбирает по capabilities устройства (обычно mmap). `io-mode=4` (userptr) или `io-mode=2` (mmap) ставить только при доказанном выигрыше латенции на конкретной модели грабера.

**Проверка:** `gst-launch-1.0 v4l2src device=$VIDEO_DEV num-buffers=10 ! fakesink` без `io-mode` отрабатывает за <1 сек.

---

### 2026-06-03 · `udpsrc.src caps = ...` в логе ≠ реально полученный пакет

GStreamer печатает declared `caps = ...` для `udpsrc.src` сразу при переходе в `PLAYING`, **до** получения данных — это контракт элемента, не доказательство приёма. Видели лог `udpsrc.src caps = ... PAYLOAD=H264 ...`, считали что пакеты приходят — на самом деле было 0 пакетов на интерфейсе. По этому ложному следу несколько раз искали проблему ниже по pipeline (depayloader / decoder).

**Правило:** при диагностике сетевых GStreamer-pipeline первый шаг — `tcpdump -i <iface> 'udp port <port>' -c 20` на обеих сторонах. Только после этого смотреть лог GStreamer. Declared caps в логе не означают, что данные реально приходят.

**Проверка:** на TX и RX независимо `tcpdump -i wg0 'udp port 5600' -c 20` ловит пакеты ≤2 сек после старта pipeline. Только потом верить `udpsrc.src caps` в логе.

---

### 2026-06-03 · Фактический транспорт стенда ≠ install.sh-дизайн (192.168.1.x)

Реальная конфигурация на 2026-06-03: u1-pi LAN `192.168.31.72` / wg `10.8.0.6`, u2-pi LAN `192.168.31.100` / wg `10.8.0.7`, iface `enP3p49s0` (Pi 5 Max), CPE710 PtP-мост ещё не развёрнут — трафик идёт через домашний роутер и интернет-WG-сервер (RTT 180 мс). `install.sh` всё ещё пишет `192.168.1.x` в netplan и env-файлы CRSF — это будущий CPE710-дизайн (Этап 3), не bug. Раздел Architecture/Сеть аннотирован в этом же коммите.

**Правило:** в bench-фазе деплоить `install.sh` с `SKIP_NETPLAN=1 PEER_IP_OVERRIDE=10.8.0.X` (X — wg-адрес peer'а). Не пытаться «починить» 192.168.1.x в install.sh пока CPE710 не развёрнут. После разворачивания CPE710 — снять override, дефолты сработают как задумано.

**Проверка:** `ip -br addr show enP3p49s0` и `wg show wg0` не должны содержать `192.168.1.x` в bench-фазе. После CPE710: `ping -i 0.2 192.168.1.X` (peer) отвечает <2 мс.

---

### 2026-05-25 · Цвета линий на тёмной теме сливаются с фоном

В диаграммах распайки переходника Boxer→u1 GND-линии `#444441` на фоне `#1a1a18` визуально сливались — разница `#2A` контраста недостаточна для тёмной темы Edge. Несколько итераций SVG было потрачено на подбор палитры пока не дошло.

**Правило:** для нейтральных линий (GND, leader lines) использовать gray-400 (`#888780`) mid-tone — видимо в обоих режимах. Для семантических сигналов — mid-tone из палитры (green-400/500 `#3B6D11`/`#639922`, coral-400 `#D85A30`, blue-400/600 `#185FA5`/`#378ADD`). Фон в standalone SVG задаётся явным `<rect fill="#1a1a18">` для корректного открытия в Edge с force-dark.

**Проверка:** мысленный тест — каждый элемент должен быть виден на полностью чёрном фоне. Если разница яркости элемента и фона < `#40` — переделать.

---

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

### 2026-05-18 · crsf_bridge.py молча дропает входящий UDP пока UART закрыт

При smoke-тесте «UDP-пакет от партнёра дошёл или нет» через `nc -u` + `journalctl -u crsf-bridge@tx1 -f` ожидал увидеть `uart write failed` как индикатор приёма UDP. На самом деле в текущем коде `crsf_bridge.py` после `recvfrom` стоит `if data and ser is not None: ser.write(data)` — когда UART не открыт (адаптер ещё не подключён, активен retry-loop в `open_serial`), входящий UDP-пакет ЧИТАЕТСЯ из сокета и МОЛЧА выбрасывается. Никаких WARNING в журнале. Тест с «пустым» Pi (без Waveshare) даёт ложно-негативный результат: пакет реально прошёл сеть и ufw, но мы об этом не узнаем. Так появился phantom-bug «ufw блокирует 14551 на u2-pi» — на самом деле правила были в порядке, тест был просто невалиден.

**Правило:** для долгоживущих байтовых мостов с auto-reconnect — на каждую тихую ветку (drop пакета, EAGAIN на non-blocking IO, skip-без-записи) обязательно лог уровня DEBUG со счётчиком. Не INFO/WARNING (чтобы не спамить под нагрузкой), но достаточно чтобы `journalctl --priority=debug` или внутренняя статистика сразу показывали «работает, просто партнёр пустой». Симметрично — для smoke-тестов сетевых сервисов не доверять «тишине в логе», использовать `tcpdump`/`ss` либо явный echo-mode в самом приложении.

**Проверка:** после добавления DEBUG-логирования — `nc -u -w 1 <pi> 14550` без подключённого UART на принимающей стороне, потом `journalctl -u crsf-bridge@tx1 --priority=debug --since "1 min ago" | grep -c "udp.*drop"` должно вернуть ≥1.

---

### 2026-05-27 · CRSF от Boxer JR-bay дошёл до дрона end-to-end

Этап 1 закрыт: Boxer JR-bay pin 5 → SN74HC14N → CH340G → /dev/ttyUSB0 → crsf-bridge@p1 на u1-pi → UDP 14552 через WireGuard → crsf-bridge@elrs на u2-pi → /dev/ttyS7 → SN74HC14N → ELRS Ranger Micro → дрон бинднут, ARM работает. Поток 6500–6800 B/s, ровно соответствует CRSF RC_CHANNELS_PACKED @ 250 Hz (26 байт × 250 = 6500). Telemetry обратно физически отрезана (TX-провод CH340G не подключен) — это осознанный выбор, можно вернуть позже двусторонней проводкой через тот же SN74HC14N.

**Правило:** при добавлении нового UART-канала повторять паттерн: env-файл в `/etc/u1u2-bridge/crsf-<name>.env` → UFW allow порт/udp с комментарием → `systemctl enable --now crsf-bridge@<name>.service` → проверить `journalctl` на наличие строк статистики `uart->udp` / `udp->uart`.

**Проверка:** `journalctl -u crsf-bridge@<name>.service --since '30 sec ago' | grep -E 'uart->udp|udp->uart'`.

---

### 2026-05-27 · Ubuntu 24.04 sshd через socket activation — ssh.socket важнее ssh.service

После загрузки u1-pi после долгого простоя `ssh ubuntu@10.8.0.6` дал `Connection refused`, при этом `ping 10.8.0.6` отвечал нормально. На самой Pi `systemctl status ssh` показал `ssh.service: disabled; inactive (dead)` и в TriggeredBy строке — `ssh.socket`. То есть в Ubuntu 24.04 sshd запускается через **socket activation**: реальный listener на :22 — это `ssh.socket`, а `ssh.service` стартует только когда socket принял соединение. Если `ssh.socket` не enabled на boot — порт 22 никто не слушает, отсюда RST.

**Правило:** для надёжного sshd после ребута на Ubuntu 24+ всегда оба:
sudo systemctl enable --now ssh.socket
sudo systemctl enable ssh.service
systemctl is-enabled ssh.socket ssh.service   # обе строки → "enabled"

**Проверка после ребута:** `ss -ltn | grep ':22'` должен показать `LISTEN 0 ... 0.0.0.0:22`.

---

<!--
Будущие реальные инциденты с железом и кодом. Кандидаты из HANDOFF:
- RS485 auto-direction на 420k бод (если не сработает) — §7.1
- Имя сетевого интерфейса в install.sh (end0 vs eth0) — §7.2
- udev ID для CH343G после получения адаптеров — §7.3
- WireGuard порт UDP/51820 — проход через CPE710 в bridge режиме — §7.6
-->
