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
| Статус CRSF-моста | `systemctl status crsf-bridge@tx1` |
| Логи CRSF live | `journalctl -u crsf-bridge@tx1 -f` |
| Статус видео | `systemctl status video-tx` (У2) или `video-rx` (У1) |
| Тест локальной сети | `ping -i 0.2 192.168.1.20` |
| Тест туннеля | `ping 10.10.0.2` (после WireGuard) |
| Проверка RKMPP | `gst-inspect-1.0 mpph264enc` |
| Preflight CRSF (без запуска моста) | `uv run python -m common.crsf_bridge --serial /dev/ttyUSB-CRSF1 --listen 0.0.0.0:14550 --peer 192.168.1.20:14550 --dry-run` |

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
