# HANDOFF — 2026-06-25 (d) · Задача 2 блок 2: install.sh / setup_udev.sh / smoke_test.sh аудированы (по живому)

> Преемник: `HANDOFF-2026-06-25c-task2-crsf-video-audited.md` (коммит `399c883`).
> **Принцип: факт = подтверждён живой командой в ЭТОЙ сессии.** Память / компакт-саммари /
> «помню» / приложенные к чату документы / `/mnt/project/` — допущение, помечать или проверять.
> Весь фактаж ниже — из live-чтения файлов репо (HEAD `399c883`) через Claude Code (Режим 1, WG on),
> выгрузка `cp <file> ~/Downloads/` → перетаскивание в чат → `view`. НЕ из памяти, НЕ из вложений.
>
> Метки источников в тексте:
> `[RAW]` — прочитано мной целиком через `view` в этой сессии (первичный факт).
> `[RAW-grep]` — в выгруженном grep-файле, который я открыл через `view`.
> `[DOC]` — doc-утверждение внутри `[RAW-grep]` (факт, что так написано в доке, ≠ факт о железе).
> `[AGENT]` — только саммари агента Claude Code, сырым НЕ видел → пере-сверить.
> `[MEM]` — память / прошлые хэндоффы / прошлые чаты.
> `[PI-TODO]` — требует подтверждения на живой Pi (в Pi-чеклист §5, НЕ закрыто).

---

## §0 — Состояние репозитория

- HEAD `399c883` `[RAW]` (верхняя строка `git log`, видел сырым). `## main...origin/main` без
  ahead/behind, дерево чистое `[RAW-grep]` (`audit-14552.txt:2`, видел сырым).
- Сессия **read-only**: 0 коммитов, 0 мутаций. Агент по моей просьбе ничего не писал/коммитил.
  → HEAD неизменен с начала сессии. **Следующий чат всё равно ре-верифицирует §0 как всегда.**
- `399c883` = коммит самого 25c-хэндоффа поверх `3857abb`. Цепочка консистентна, хвоста нет.

---

## §1 — Что закрыто в блоке 2

Задача 2 = полный сквозной аудит стека → итог в `docs/roadmap/`. Блок 1 (CRSF+видео код) закрыт
в 25c. **Этот блок закрыл деплой-ось: `install.sh`, `setup_udev.sh`, `smoke_test.sh`** — все
прочитаны ЦЕЛИКОМ сырьём.

### Метод (держать)
- `cp <file> ~/Downloads/` → перетащить в чат → `view`. Свёрнутый stdout Claude Code (`+N lines`) =
  саммари агента = ДОПУЩЕНИЕ, не код. `install.sh` при `view` усёк середину (строки 200–222) —
  переоткрыл явным `view_range`, иначе пропустил бы секции 5–6. **Всегда проверять, что файл
  прочитан без пробелов.**

### Прочитанные файлы и вердикты
| Файл | Вердикт |
|---|---|
| `install.sh` (419 строк) `[RAW]` | Боевая логика деплоя корректна (TRANSPORT, env, ufw, cage/tmpfiles, launch). **Одна P1** (overlay m1≠m2) + P2/P3, см. §2. |
| `setup_udev.sh` (~230 строк) `[RAW]` | Код качественный, но обслуживает **выкинутую RS485-архитектуру**. **P1-udev**, см. §2. |
| `smoke_test.sh` (~180 строк) `[RAW]` | На каноне `@p1`/`@elrs`, env-чтение `SERIAL_DEV`. **Одна P2** (пингует мёртвую `10.10.0.x`), см. §2. |

### Порты — закрыты СЫРЬЁМ (пометка «со слов агента» из 25c снята)
- **14552 = единственный боевой канон.** `[RAW-grep]` (`audit-14552.txt`): `install.sh:236
  CRSF_PORT=14552`, `install.sh:298` ufw, `docs/baseline/u1/crsf-p1.env` + `u2/crsf-elrs.env`
  `LISTEN=0.0.0.0:14552`+`PEER=…:14552`. В `crsf_bridge.py`/`@.service`/видео — порта НЕТ (берётся из env). ✓
- **14550/14551 — только вне боевого рантайма.** `[RAW-grep]` (`audit-1455x.txt`): докстринг/help
  `crsf_bridge.py`, bench, `tests/unit/`, стале-доки (`HANDOFF.md`/`DEPLOYMENT.md`), историч.
  хэндоффы. **Ноль** в `install.sh`/baseline-env/`@.service`/видео. ✓ (это P3 #1 из 25c — косметика.)

---

## §2 — Реестр находок Задачи 2 (накопительный, обновлён блоком 2)

> Все находки **каталогизированы, НЕ исправлены** — аудит read-only. Правки = отдельное
> scoped-решение ПОСЛЕ закрытия всех блоков. P1-overlay и setup_udev трогают u2/UART7 →
> за drone-safety-гейтом.

### P1-overlay — install.sh §2b регистрирует НЕ тот UART7-overlay (m1 вместо боевого m2)
Два слоя.

**Слой 1 — неверный overlay (высокая уверенность).**
- `install.sh:135` `[RAW]`: `U_BOOT_FDT_OVERLAYS="…/rk3588-uart7-m1.dtbo"` (комм. 132/417: «pins 29/38, m1»).
- `install.sh:267` `[RAW]` (комментарий ТОГО ЖЕ файла): «ttyS7 = UART7 overlay **m2** → pin 26 …
  m1 (pin 29/38) **неактивен → трек D**». → внутреннее противоречие файла, сырьём.
- Боевое = **m2/pin 26**: `[RAW-grep]` (`audit-uart7-overlay.txt`) `BASELINE.md:26`
  «`rk3588-uart7-m2.dtbo` (UART7_TX_M2) pin 26»; `2026-05-24-inverter-working-uart7-m2-pin26.md:49`
  «overlay изменён с m1 на m2»; `extlinux.conf` содержит m2 (бэкап `.bak`). Плюс `[MEM]`
  «pin 26 = GPIO1_B5 = UART7_TX overlay m2, confirmed on physical board, not to be re-litigated».
- История `[RAW-grep]`: `git log -S 'rk3588-uart7-m1' -- install.sh` = **один** коммит `d8c4e33`,
  с тех пор не менялся → HEAD до сих пор m1. m2 в `install.sh` **нет нигде** (только в доках).

**Слой 2 — m1 пишется в, вероятно, ИГНОРИРУЕМЫЙ конфиг (сильное указание, не финал).**
- `[RAW-grep]` `LESSONS-ARCHIVE.md:183` + `wiring-opi5max.md:108`: `U_BOOT_FDT_OVERLAYS` в
  `/etc/default/u-boot` **молча игнорируется** `u-boot-menu` на этой плате; рабочая правка живёт в
  `/boot/extlinux/extlinux.conf` (правилась руками).
- НО `install.sh:114` `[RAW]` (комментарий §2b) утверждает обратное: путь работает с фиксом
  абсолютного пути (`_BOOT_PATH=""` quirk). **Конфликт install.sh ↔ LESSONS-ARCHIVE.** Что реально
  активно — `[PI-TODO]`.

**Не «просто перепутали m1/m2» — ловушка для будущей правки:**
- m1-эра (~05-22): m1 = TX+RX пины 29/38, **loopback работает** (отсюда «m1 рабочий» в архиве — это правда **для loopback**).
- m2-эра (05-24→сейчас): нужен **только TX**, инвертор SN74HC14N физически на **pin 26** = UART7_TX = **m2**
  (RX остаётся UNCLAIMED — для TX-only неважно, RX/телеметрия = трек D). `[RAW-grep]`+`[MEM]`.
- Текущая истина = **m2/pin 26**. install.sh и LESSONS-ARCHIVE застряли в m1-эре.

**Impact:** чистый `install.sh u2` НЕ воспроизведёт рабочий UART7-TX. Класс «репо ≠ живое» —
прямая мишень disaster-recovery (Уровень 1, коммит `6239d68`). **P1.**

### P1-udev — `setup_udev.sh` осиротел при смене архитектуры RS485→CH340/UART7
- Скрипт целиком про **Waveshare USB-TO-RS485 (B) / WCH CH343G `1a86:55d3` / драйвер `cdc_acm` /
  `/dev/ttyACMx` / symlinks `ttyACM-CRSF1`+`ttyACM-CRSF2` / ДВА адаптера**. `[RAW]`
- Это был **рабочий** инструмент RS485-бенча (май 2026: серийники зарегистрированы на обеих Pi —
  `5A98051690`/`5A7C185549`/`5A98058254`). `[MEM, чат 2026-05-18]` Затем «**RS485 removed from
  architecture**» `[MEM, сводка 2026-06-05]` → скрипт осиротел.
- Боевая истина `[RAW install.sh §7]`+`[MEM]`: u1 = **CH340 `1a86:7523` → `/dev/ttyUSB0` напрямую**
  (SerialNumber=0 → symlink в принципе невозможен); u2 = **аппаратный UART7 `/dev/ttyS7`** (не USB).
  Ни одному боевому узлу `setup_udev.sh` не соответствует.
- **Активная дезинформация (реальный вред, не просто мёртвый код):**
  - `install.sh:20` `[RAW]` зовёт `sudo ./setup_udev.sh` как живой шаг установки.
  - Шапка `smoke_test.sh` `[RAW]` велит его запускать.
  - `setup_udev.sh:190` `[RAW]` печатает оператору `systemctl restart crsf-bridge@tx1
    crsf-bridge@tx2` → таких юнитов нет (`@p1`/`@elrs`) → «Unit not found», ложный отказ.
- **Решение delete-vs-retain — за пользователем** (CH343G/ttyACM-машинерию теоретически можно
  оживить под будущий RS485-CTRL канал из `docs/roadmap/`, но as-written она про CRSF1/CRSF2,
  которые теперь CH340/UART7). Живые ссылки выше неверны СЕЙЧАС в любом случае. **P1.**
- `[PI-TODO]`: `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` — ожидаемо отсутствует на текущих узлах.

### P2-smoke-wg — smoke_test пингует мёртвую WG-подсеть `10.10.0.x`
- `[RAW]` `smoke_test.sh`: `PEER_IP_WG="10.10.0.2"` (u1) / `"10.10.0.1"` (u2).
- Боевое WG = **`10.8.0.x`**: u1=`10.8.0.6`, u2=`10.8.0.7` `[RAW install.sh §7 tunnel]` +
  `[MEM wg-easy, VPS 95.140.147.108]`. Ошибка двойная: подсеть (`10.10`≠`10.8`) И хост.
- Логика: `if ip link show wg0` поднят → `ping $PEER_IP_WG` → при неответе **FAIL**. → при WG on
  (tunnel/бенч) **ложный FAIL на исправном туннеле** (пингует несуществующий адрес).
- Сейчас **дремлет**: поле в Режиме 2 (WG off) → ветка `warn`-skip, безвредно. Активная
  дезинформация при WG on. Корень — недочист stageB (`10.10→10.8` пропущен). **P2.**

### P2-planB — install.sh §5 в drone-режиме не копирует модули, нужные joystick
- `install.sh:212–217` `[RAW]`: `MODE=drone` копирует в `/opt` `crsf.py` (обе роли) +
  `joystick_to_crsf.py` (u1), но **НЕ** `channel_map.py`.
- `install.sh:240–246` `[RAW]` (`joystick.env`): задаёт `CHANNEL_MAP_PATH=…/channels.toml` +
  `TELEMETRY_LOG_INTERVAL_SEC`/`TELEMETRY_STALE_SEC` → косвенно подразумевает, что
  `channel_map.py` И `telemetry_logger.py` нужны в рантайме — ни один не копируется в §5.
- **Impact:** вероятный ImportError при деплое drone-u1. Источник: `[RAW]` install.sh +
  `[AGENT/MEM]` про граф импортов (`joystick_to_crsf.py` НЕ читан). **P2, закрыть в блоке plan B.**

### P3 — наблюдения, не блокеры
1. `[RAW]` install.sh §2: RKMPP-проверка под `MODE==bench`, но `video-tx` (нужен RKMPP) стартует
   на u2 при `!SKIP_VIDEO` **независимо от MODE** (стр. 382). В `drone`+u2 видео без проверки
   энкодера. Чище — гейтить проверку по `SKIP_VIDEO`.
2. `[RAW]` install.sh §3: авто-iface = первый `UP` не-lo; при >1 UP выбор по порядку. Смягчено `IFACE=`.
3. `[RAW]` install.sh §4: `netplan apply || true` глотает ошибки netplan.
4. `[RAW]` smoke_test: `gst-inspect mpph264enc` (ЭНКОДЕР) проверяется на обеих ролях, но u1
   ДЕКОДИРУЕТ (`mppvideodec`). Работает как прокси наличия пакета `gstreamer1.0-rockchip1`
   (enc+dec из одного пакета), семантически u1 надо бы проверять декодер. Низкий.
5. `[RAW]` install.sh: `MODE` не описан в шапке опц-env (стр. 25–40). Косметика-док.
6. `[AGENT + стале /mnt/project]` `common/systemd/crsf-bridge@.service:4–5`: комменты-примеры
   `@tx1/@tx2`. Сырьём НЕ видел → пере-сверить в блоке systemd. P3-косметика.

---

## §3 — Подтверждённая сильная инженерия (перенос знания, НЕ находки)

- **install.sh — TRANSPORT единый источник истины** для CRSF-peer (§7) И видео-peer (§7b, пишется
  в ОБОИХ режимах) `[RAW]` → закрывает split-режим и старую дыру зашитого видео-peer.
- **Авто-`SKIP_NETPLAN` в tunnel** `[RAW]` — анти-lockout (не переписывает LAN-netplan).
- **UFW строго аддитивно**: `ufw allow` idempotent, без `enable`, без смены default-policy, только
  `direct`, под `command -v ufw` `[RAW]`.
- **`SKIP_APT`/`SKIP_VIDEO`** гарды для оффлайн-поля / бенча без grabber `[RAW]`.
- **Idempotency**: UART7-маркер `# u1u2-bridge UART7`, `channels.toml` не затирается (сохранение
  калибровки), tmpfiles `/run/user/0` `[RAW]`.
- **Финальный echo транспорт-aware** `${CRSF_PEER%%:*}` `[RAW + MEM 2026-06-12 Phase C]`.
- **smoke_test хорошее**: serial ping `-c 3 -W 1` (не одиночный); env-чтение `SERIAL_DEV` (не
  хардкод); WG-skip без FAIL на бенче (логика верна — неверен только адрес внутри); ANSI только
  при `-t 1`; независимые проверки + сводка `[RAW]`.
- **setup_udev качество кода высокое** (snapshot/diff_one_new/extract_usb_attrs, idempotent,
  `udevadm settle`, ModemManager-ignore) — но обслуживает удалённое железо `[RAW]`.

---

## §4 — Очередь аудита (осталось, всё по живому репо)

- **systemd-юниты сырьём (СЛЕДУЮЩИЙ блок):** `common/systemd/crsf-bridge@.service` (закрыть
  P3 #6 tx1/tx2-комменты), `common/systemd/joystick-to-crsf.service` (НЕ читан).
  `video-tx.service`/`video-rx.service` — читаны в 25c.
- **CI-оснастка:** `Makefile`, `verify.ps1`, `format.ps1`.
- **Сеть:** netplan (внутри install.sh; отдельных файлов в репо нет — проверить), ufw (в install.sh
  §7c), WireGuard wg0-конфиги (вероятно вне репо — wg-easy VPS `95.140.147.108`, u1=`10.8.0.6`,
  u2=`10.8.0.7` `[MEM]`).
- **Тестовая оснастка:** `bench/` (`crsf_udp_source.py`, `loopback.py`), `hardware/`
  (`crsf_jitter_test.py`, `crsf_smoke_test.py`).
- **plan B группой:** `common/joystick_to_crsf.py` (резолвит P2-planB), `common/telemetry_logger.py`,
  `common/channels.default.toml` (дочитать тело — arm-семантика, это 25c P3 #5 `_scale_switch`
  unconfirmed), `common/channel_map.py` (пере-подтвердить роль plan B), `docs/roadmap/joystick-2-usb-hid.md`.
- `tests/unit/` (9 модулей) — на усмотрение.
- Стале-доки `docs/HANDOFF.md`, `docs/DEPLOYMENT.md` (`10.10.0.x`, CP2102N, tx1/tx2) — пометить
  «исторические» отдельным решением, НЕ в рамках аудита.

---

## §5 — Pi-чеклист (один транскрипт, Режим 2 WG off, ПОД конкретный список)

Аудит кода Pi НЕ требует. Эти пункты код подтвердить не может — собрать одним батчем
(WG off → `Start-Transcript` → выполнить → WG on → прислать файл), НЕ вхолостую:
- **P1-overlay:** `cat /boot/extlinux/extlinux.conf`; `grep U_BOOT_FDT_OVERLAYS /etc/default/u-boot`;
  `ls /lib/firmware/$(uname -r)/device-tree/rockchip/overlay/ | grep uart7` → какой overlay реально активен.
- **P1-udev:** `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` (ожидаемо: нет файла на текущих узлах).
- **Из 25c §4:** `lsusb` + `v4l2-ctl --list-formats` (реально ли Arkmicro только 640×480 MJPG);
  `ip -br link` (имя iface, ожидаемо `enP3p49s0`); `systemctl is-active` 6 сервисов; развёрнутые
  `/etc/u1u2-bridge/*.env` (мог править человек); рантайм `udp_drop`, RSSI/LQ, clock-skew (~52 мин на u2).

---

## §6 — Рабочие инварианты (перенос из 25c, не менять)

- Язык — русский. SSH всегда `ssh -i ~/.ssh/u1u2 ubuntu@<ip>`.
- **Drone-safety gate:** пропеллеры сняты + Boxer off перед любым рестартом CRSF-сервисов; явное
  разрешение оператора на каждое питание дрона.
- **Два канала ARDOR:** Claude Code (WG on, репо/git/SSH по туннелю) ⟂ батч-PowerShell-транскрипт
  (WG off, мост `192.168.1.x`). Kill-switch `AllowedIPs=0.0.0.0/0` — параллельного доступа нет.
  Переключение инструментов — анонсировать.
- Серийный ping (`-n 4`+/`-Count 2`+) за радио обязателен — одиночный врёт на холодном ARP.
- §0-аудит (git + live-сервисы) ПЕРЕД любыми мутациями/хэндоффом. Транспорт — по `PEER=` в env,
  НЕ по `systemctl is-active`.
- Scoped-коммиты: НИКОГДА `git add -A`; diff-review перед каждым; форвард-онли.
- Файлы хэндоффа/скриптов — генерировать на стороне Claude, отдавать скачиванием, не heredoc.
- Старый 8-жильный кабель из проекта вычищен — НЕ упоминать как контекст.
- **Урок процесса:** Claude Code сворачивает многострочный stdout. Для аудита кода — выгружать
  файл в чат (`cp ~/Downloads/` → перетащить → `view`), НЕ полагаться на саммари агента. `view`
  тоже может усечь середину — проверять полноту, дочитывать `view_range`.
- **Вложения чата и `/mnt/project/` — СТАЛЕ.** Аудит ТОЛЬКО по живому репо.

---

## §7 — Немедленный TODO на старте следующего чата

1. **Режим 1 (WG on).** `cd C:\Users\ARDOR\Documents\Projects\u1u2-bridge;
   git --no-pager log --oneline -5; git status -sb` — §0-аудит. Ожидаемо HEAD `399c883`, синхрон,
   чисто (ПРОВЕРИТЬ, не полагаться). Если статус свернётся — выгрузить в файл (как в этом чате).
2. **Продолжить Задачу 2: systemd-юниты сырьём** — `crsf-bridge@.service` + `joystick-to-crsf.service`
   через `cp ~/Downloads/` → `view`. Закрыть P3 #6.
3. Далее по §4: CI-оснастка → сеть → bench/hardware → plan B группой → tests.
4. Живая Pi — только под список §5, одним батчем.
5. Когда все блоки закрыты — сводный итог Задачи 2 → `docs/roadmap/` (scoped-коммит): реестр
   находок §2 + приоритизация правок.
6. **Задача 3** (A-to-Z инструкция сборки) — ПОСЛЕ Задачи 2 и устаканивания железа.

---

## Приложение — состояние блока 1 (из 25c, в этой сессии НЕ пере-проверялось)

CRSF+видео код аудирован статическим ревью, корректен **в границах**: `crsf_bridge.py` (459),
`crsf.py` (100), `crsf_telemetry.py` (~330), `channel_map.py` (397), `video_tx.sh`, `video_rx.sh`,
`video-tx/rx.service`, `switch-mode.ps1`. **Границы:** только чтение HEAD — НЕ запускались
`verify.ps1`/`mypy`/`pytest`/`shellcheck`; код НЕ исполнялся; security НЕ аудирован (пример:
`crsf_bridge.recvfrom` не фильтрует source-адрес — открытый UDP примет CRSF от любого хоста сети);
живая Pi НЕ затрагивалась. Детали — в 25c §1.
