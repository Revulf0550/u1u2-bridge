# HANDOFF — 2026-06-25 (e) · Задача 2 блок 3: systemd-юниты + plan B группа аудированы (по живому)

> Преемник: `HANDOFF-2026-06-25d-task2-block2-install-udev-smoke.md` (закоммичен в начале этой
> сессии как `6bad9f0`).
> **Принцип: факт = подтверждён живой командой в ЭТОЙ сессии.** Память / компакт-саммари /
> «помню» / приложенные к чату документы / `/mnt/project/` — допущение, помечать или проверять.
> Весь фактаж ниже — из live-чтения файлов репо через Claude Code (Режим 1, WG on),
> выгрузка `cp <file> ~/Downloads/` → перетаскивание в чат → `view`. НЕ из памяти, НЕ из `/mnt/project`.
>
> Метки источников:
> `[RAW]` — прочитано мной целиком через `view` в ЭТОЙ сессии (первичный факт).
> `[RAW-grep]` — в выгруженном grep-выводе, открытом через `view`/инлайн.
> `[RAW-md5]` — целостность копии подтверждена `md5sum` (копия = рабочее дерево).
> `[AGENT]` — только саммари агента Claude Code, сырьём НЕ видел → пере-сверить.
> `[MEM]` — память / прошлые хэндоффы / прошлые чаты.
> `[PI-TODO]` — требует подтверждения на живой Pi (Pi-чеклист §5, НЕ закрыто).

---

## §0 — Состояние репозитория

- **HEAD `6bad9f0`** `[RAW]` (`git log --oneline -3` сырым): `docs(handoff): 2026-06-25d …`
  поверх `399c883` (25c). Запушено: `399c883..6bad9f0  main -> main` `[RAW]`.
- `## main...origin/main`, дерево чистое, синхрон `[RAW]` (`git status -sb` сырым после push).
- **Ход сессии:** в начале был один untracked — сам 25d-хэндофф; застейджен **точечно**
  (`git add <file>`, НЕ `-A`), `diff --cached --stat` = 1 файл / +242 `[RAW]`, закоммичен `6bad9f0`,
  запушен. **После этого — read-only:** 0 коммитов, 0 мутаций до конца сессии.
- Следствие для tracked-файлов: дерево чистое → **рабочая копия == HEAD `6bad9f0`**, поэтому
  выгруженные `cp`-копии = HEAD-версии. **Следующий чат всё равно ре-верифицирует §0 как всегда.**

---

## §1 — Что закрыто в этой сессии (блок 3 + plan B)

Задача 2 = полный сквозной аудит стека → итог в `docs/roadmap/`. Блок 1 (CRSF+видео) = 25c,
блок 2 (install/udev/smoke) = 25d. **Эта сессия закрыла: блок 3 (systemd-юниты) + группу plan B.**

### Прочитано СЫРЬЁМ за сессию
| Файл | Метод | Вердикт |
|---|---|---|
| `common/systemd/crsf-bridge@.service` (31) | `[RAW]` view | Тело чистое, инварианты ок. Закрыт **P3 #6**. |
| `common/systemd/joystick-to-crsf.service` (27) | `[RAW]` view | Тело чистое. Новый **P3 js0/evdev**. |
| `common/joystick_to_crsf.py` (587) | `[RAW]` view ×3 диапазона | Качество высокое. **Закрывает+расширяет P2-planB** (top-level импорты). |
| `install.sh` §5–§7 (стр. 206–276) | `[RAW]`+`[RAW-md5]` `38f68409…` | §5-копирование = ядро вердикта P2-planB. Бонусы 14552 / env-имена сырьём. |
| `common/channel_map.py` (396) | `[RAW]` view ×3 + `[RAW-md5]` `e87100bb…` | Корректен. **Закрыт 25c P3 #5** (`_scale_switch`). Новый **P3 «незамапл.=992»**. |
| `common/channels.default.toml` | `[RAW]` (инлайн целиком) | Дефолт структурно safe. **evtest-гейт** в реестр. |
| `common/crsf_telemetry.py` | `[RAW]` (инлайн целиком) | RX-парсер, safety-neutral, корректен. |
| `common/telemetry_logger.py` | `[RAW]` (инлайн целиком) | Диагност-логгер, safety-neutral, корректен. |

> `crsf.py` (100) — читан в 25c, в этой сессии НЕ перечитывался.
> Полнота списка `.service` (что их ровно 6 tracked, из них 4 боевых юнита) — `[AGENT]`
> (`git ls-files '*.service'` свернулся; сырьём видел 3 имени, но все 4 целевых юнита
> подтверждены независимо разными шагами). При финальной сборке реестра — добить выгрузкой.

### Метод (держать)
`cp <file> ~/Downloads/` → перетащить → `view`. Свёрнутый stdout Claude Code (`+N lines`) =
саммари агента = ДОПУЩЕНИЕ. `view` усекает середину при >16 KB — читать диапазонами,
проверять полноту. `joystick_to_crsf.py`/`channel_map.py` читались по 3 диапазона.

---

## §2 — Реестр находок Задачи 2 (накопительный, обновлён блоком 3)

> Аудит read-only: всё **каталогизировано, НЕ исправлено**. Правки = отдельное scoped-решение
> ПОСЛЕ всех блоков. P1-overlay/setup_udev и любые правки u2/UART7 — за drone-safety-гейтом.

### P1-overlay — install.sh §2b регистрирует m1 вместо боевого m2 — **БЕЗ ИЗМЕНЕНИЙ (25d)**
Статус прежний. **В этой сессии §2b (стр. 111–158) сырьём НЕ перечитан.** Мимоходом подтверждён
сырьём только §7-комментарий `install.sh:267–268` `[RAW]`: «ttyS7 = UART7 overlay **m2** → pin 26
(GPIO1_B5), проверено `gpio readall` 2026-06-13; RX = m1 pin 29/38 неактивен → трек D». Это
совпадает с боевой истиной m2 и с внутренним противоречием файла, что зафиксировал 25d.
**Перепроверка §2b (m1) сырьём — открыта**, см. §4. Финал активного overlay — `[PI-TODO]` (§5).

### P1-udev — `setup_udev.sh` осиротел (RS485→CH340/UART7) — **БЕЗ ИЗМЕНЕНИЙ (25d)**
Не трогалось в этой сессии. Статус и `[PI-TODO]` прежние.

### P2-smoke-wg — smoke_test пингует мёртвую `10.10.0.x` — **БЕЗ ИЗМЕНЕНИЙ (25d)**
Не трогалось.

### P2-planB — **ЗАКРЫТ КАК НАХОДКА, РАСШИРЕН. Подтверждён сырьём двусторонне.**
**Было (25d):** install.sh §5 не копирует `channel_map.py`; косвенно нужны ещё модули.
**Стало (сырьём ЭТОЙ сессии):**
- `joystick_to_crsf.py:48–63` `[RAW]` — top-level hard-импорты (исполняются ДО `main()`):
  `common.channel_map`, `common.crsf`, `common.crsf_telemetry`, `common.telemetry_logger`.
  (`evdev` — НЕ top-level: lazy `import` внутри `open_device:275`, потому модуль грузится на Windows.)
- Транзитивно: `crsf_telemetry.py` `[RAW]` → `from common.crsf import CRSF_SYNC_FC, crc8`;
  `telemetry_logger.py` `[RAW]` → `from common.crsf_telemetry import …`.
- `install.sh §5` (стр. 206–217) `[RAW]` кладёт в `/opt/u1u2-bridge/common/`:
  `crsf_bridge.py` (209, всегда), `crsf.py` (213, drone), `joystick_to_crsf.py` (215, drone+u1).
  **НЕ кладёт нигде:** `channel_map.py`, `crsf_telemetry.py`, `telemetry_logger.py`.
- **Вывод:** `python3 -m common.joystick_to_crsf` падает на стр. 48
  (`from common.channel_map import …`) с `ModuleNotFoundError` **до `main()`** → юнит не стартует →
  systemd `Restart=always` = краш-луп. **Блокер деплоя drone-u1.**
- **Недостают ТРИ `.py`-модуля** (не один): `channel_map`, `crsf_telemetry`, `telemetry_logger`.
- **`channels.toml` тут НИ ПРИ ЧЁМ:** он `.toml` (soft → legacy fallback), копируется идемпотентно
  `install.sh:250–251` `[RAW]`. ImportError случается раньше, чем код читает toml.
- **Правка (для блока правок):** добавить 3× `install -m 0644 "$REPO/common/{channel_map,
  crsf_telemetry,telemetry_logger}.py" /opt/u1u2-bridge/common/` в §5 под `MODE=drone && ROLE=u1`.
  Namespace-package (`-m common.X`) работает без `__init__.py` на 3.12 — проблема только в файлах.

### P3 — наблюдения, не блокеры (накопительно)
1–6 — из 25d (RKMPP-гейт по MODE; авто-iface; `netplan apply||true`; smoke проверяет энкодер на
   u1; `MODE` не в шапке опц-env; **#6 закрыт — см. ниже**).
- **#6 — ЗАКРЫТ сырьём.** `crsf-bridge@.service:4–5` `[RAW]` действительно даёт примеры `@tx1/@tx2`
  + `EnvironmentFile=…/crsf-%i.env`. Боевой канон = `@p1/@elrs`: подтверждён сырьём дважды —
  `git ls-files` показал `docs/baseline/u1/crsf-bridge@p1.service`+`crsf-p1.env`, и `install.sh §7`
  генерирует `crsf-p1.env` (259) / `crsf-elrs.env` (269) `[RAW]`. Комменты устарели (класс «доки в
  m1/tx1-эре»), но это **доккоммент, не исполняется** → косметика. Функциональный двойник той же
  ошибки — `setup_udev.sh:190` (печатает `@tx1/@tx2` оператору) — отдельно в P1-udev.
- **#7 (новое) — js0/evdev рассинхрон. `[RAW]` трёхсторонне.** Код работает через **evdev**
  (`joystick_to_crsf`: `--device` default `/dev/input/event0`, `open_device`→`evdev.InputDevice`);
  `joystick.env:241` `DEVICE=/dev/input/event0`; а юнит `joystick-to-crsf.service:7`
  `After=dev-input-js0.device` — это **joydev** (`/dev/input/js0`), другой интерфейс. Семантический
  рассинхрон. Вдобавок `After=device` избыточен — код сам реконнектится (`_try_reopen` backoff).
  Низкий приоритет, не блокер (js0 и eventN udev создаёт ~одновременно).
- **#8 (новое) — channel_map: незамапленный канал = 992 (MID), не failsafe-low. `[RAW]`.**
  `apply_mapping:227` инициализирует все 16 в `CRSF_CH_MID`; незамапленные слоты так и остаются
  992 (документировано by design, стр. 221–222). `load_config` НЕ требует обязательного присутствия
  throttle/arm → валидный-но-неполный (или пустой) конфиг проходит. **Риск:** забытый throttle-канал
  сядет на 992 = ~полугаз, НЕ idle(172). Для AUX/arm 992 обычно безопасно (arm-диапазон FC выше).
  Edge: требует ошибки конфига. **Дефолт НЕ триггерит** (см. evtest-гейт). Низкий приоритет.

### Гейт (не P-находка) — evtest-калибровка channels.default.toml
`channels.default.toml` `[RAW]` сам кричит в шапке и у КАЖДОГО свича: все
`min_raw/max_raw/center_raw/source` = **BEST-GUESS** по стандарту EdgeTX joystick mode; обязательна
калибровка `evtest /dev/input/eventN` на живом TX12 (сборки шлют 0..65535 ИЛИ 0..1023 ИЛИ ±32768;
3pos может приходить как `ABS_HAT0Y` −1/0/1 → тогда `source="ABS_HAT0Y", low_raw=-1, high_raw=1`).
**Ключевое:** failsafe-безопасность СТРУКТУРНА (зависит от *наличия* `center_raw`/`kind`, не от
точных чисел) → guess бьёт по точности управления, не по disarm/idle. Это **гейт для Задачи 3**
(build-guide обязан включить evtest-шаг), НЕ баг кода.

---

## §3 — Подтверждённая сильная инженерия (перенос знания, сырьём этой сессии)

- **install.sh `[RAW]`:** `CRSF_PORT=14552` (236) — канон 14552 теперь сырьём; `CRSF_PEER` из
  `TRANSPORT` (231–235, единый источник истины); `channels.toml` idempotent (250–255, не затирает
  калибровку). Env-имена `crsf-p1.env`/`crsf-elrs.env` генерируются сырьём → укрепляют `@p1/@elrs`.
- **joystick_to_crsf.py `[RAW]`:** lazy `evdev` (Windows-dev грузит модуль); failsafe-дисциплина —
  отвал device → CRSF не шлётся → FC failsafe; reconnect → `_failsafe_channels` (центр/disarm), не
  стреляет устаревшим стиком; select-loop с RX-телеметрией в приоритете; битый channel-map →
  WARNING+legacy linear, не падает.
- **channel_map.py `[RAW]`:** `_scale_switch` (25c P3 #5 закрыт) — 3pos пороги, 2pos/momentary
  `1811 if raw else 172`; failsafe замапленного свича = 172 (disarm-safe). `load_config` ловит
  **коллизии каналов** (axis/switch, `used_channels`); `_require_int` отвергает `bool`
  (`channel=true→1`); typo-детект unknown keys; единый `ChannelMapError`.
- **crsf_telemetry.py `[RAW]`:** робастный ресинк (bad sync/len/CRC → drop+resync, unknown type →
  consume, буфер не растёт); строгие декодеры (длины 10/8/15/6); RSSI `uint8×-1→−dBm`; TX-power
  enum с `-1`-маркером (не падает на новом enum); flight-mode `errors="replace"`.
- **telemetry_logger.py `[RAW]`:** без внутреннего таймера (`maybe_log(now)` → тестируемо);
  `_last_emit_ts=-inf` (первый вызов сразу); stale → поле сбрасывается ЦЕЛИКОМ в `{stale,age_s}`
  (старые данные опаснее отсутствия).

---

## §4 — Очередь аудита (осталось, всё по живому репо)

Из §4 25d минус закрытое (systemd + plan B группа):
- **CI-оснастка (следующий блок):** `Makefile`, `verify.ps1`, `format.ps1`.
- **Сеть:** `install.sh §3` (авто-iface), `§4` (netplan, в этой сессии НЕ читан сырьём — читал §5–§7),
  `§7c` (ufw), WireGuard wg0-конфиги (вероятно вне репо — wg-easy VPS `95.140.147.108`,
  u1=`10.8.0.6`, u2=`10.8.0.7` `[MEM]`).
- **install.sh §2b (P1-overlay) — перепроверить m1 сырьём** (в этой сессии не читан; 25d-факт `[RAW]`
  устарел по давности → ре-верифицировать, либо принять 25d как есть scoped-решением).
- **install.sh §1/§8–§11** (зависимости, udev-вызов, cage/wayland §9, sysctl §10, запуск §11) —
  частично `[MEM 25d]`, сырьём в этой сессии не читаны.
- **Тестовая оснастка:** `bench/` (`crsf_udp_source.py`, `loopback.py`), `hardware/`
  (`crsf_jitter_test.py`, `crsf_smoke_test.py`).
- `tests/unit/` (9 модулей) — на усмотрение.
- Стале-доки `docs/HANDOFF.md`, `docs/DEPLOYMENT.md` — пометить «исторические» отдельным решением.

---

## §5 — Pi-чеклист (один транскрипт, Режим 2 WG off, ПОД конкретный список) — перенос 25d

В этой сессии на живую Pi НЕ ходили. Список без изменений:
- **P1-overlay:** `cat /boot/extlinux/extlinux.conf`; `grep U_BOOT_FDT_OVERLAYS /etc/default/u-boot`;
  `ls /lib/firmware/$(uname -r)/device-tree/rockchip/overlay/ | grep uart7` → какой overlay активен.
- **P1-udev:** `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` (ожидаемо: нет файла).
- **P3 #7 (новое):** на живой Pi проверить, под каким узлом TX12 виден — `ls /dev/input/`
  (есть ли `js0` и `event0`), `evtest` → подтвердить, что `DEVICE` в `joystick.env` указывает на
  реальный evdev-узел (это же — evtest-гейт калибровки channels.toml).
- **Из 25c §4:** `lsusb` + `v4l2-ctl --list-formats` (реально ли Arkmicro 640×480 MJPG);
  `ip -br link` (имя iface, ожид. `enP3p49s0`); `systemctl is-active` 6 сервисов; развёрнутые
  `/etc/u1u2-bridge/*.env`; рантайм `udp_drop`, RSSI/LQ, clock-skew (~52 мин на u2).

---

## §6 — Рабочие инварианты (перенос из 25d, не менять)

- Язык — русский. SSH всегда `ssh -i ~/.ssh/u1u2 ubuntu@<ip>`.
- **Drone-safety gate:** пропеллеры сняты + Boxer off перед любым рестартом CRSF-сервисов; явное
  разрешение оператора на каждое питание дрона.
- **Два канала ARDOR:** Claude Code (WG on, репо/git/SSH по туннелю) ⟂ батч-PowerShell-транскрипт
  (WG off, мост `192.168.1.x`). Kill-switch `AllowedIPs=0.0.0.0/0` — параллельного доступа нет.
  Переключение инструментов — анонсировать.
- Серийный ping (`-n 4`+/`-Count 2`+) за радио обязателен — одиночный врёт на холодном ARP.
- §0-аудит (git + live-сервисы) ПЕРЕД любыми мутациями/хэндоффом. Транспорт — по `PEER=` в env,
  НЕ по `systemctl is-active`.
- Scoped-коммиты: НИКОГДА `git add -A`; `diff --cached --stat` перед каждым; форвард-онли.
  (В этой сессии так и коммитили 25d-хэндофф.)
- Файлы хэндоффа/скриптов — генерировать на стороне Claude, отдавать скачиванием, не heredoc.
- Старый 8-жильный кабель из проекта вычищен — НЕ упоминать как контекст.
- **Урок stdout:** Claude Code сворачивает многострочный stdout (`git ls-files`, `git grep` в этой
  сессии свернулись). Для аудита — выгружать файл (`cp ~/Downloads/` → перетащить → `view`), НЕ
  полагаться на саммари. `view` тоже усекает середину — читать диапазонами, проверять полноту.
- **Вложения чата и `/mnt/project/` — СТАЛЕ.** Аудит ТОЛЬКО по живому репо.
- **Агентские реплики «тот же файл, что выгружали ранее в этой сессии» — НЕТОЧНЫ** (агент путал
  выгрузки 25d с текущим чатом). Каждый файл читать с нуля, привязку к версии — через чистый §0
  (дерево чистое → копия = HEAD) или `md5`.

---

## §7 — Немедленный TODO на старте следующего чата

1. **Режим 1 (WG on).** `cd C:\Users\ARDOR\Documents\Projects\u1u2-bridge;
   git --no-pager log --oneline -5; git status -sb` — §0-аудит. Ожидаемо **HEAD `6bad9f0`**, синхрон,
   чисто (ПРОВЕРИТЬ, не полагаться; память может отставать). Если статус свернётся — выгрузить в файл.
2. **Продолжить Задачу 2: CI-оснастка сырьём** — `Makefile`, `verify.ps1`, `format.ps1`
   (`cp ~/Downloads/` → `view`).
3. Далее по §4: сеть (install.sh §3/§4/§7c + WG) → bench/hardware → tests. Решить отдельно:
   перечитывать ли install.sh §2b (P1-overlay) сырьём или принять 25d-факт scoped-решением.
4. Живая Pi — только под список §5, одним батчем (WG off → `Start-Transcript` → WG on → файл).
5. Когда все блоки закрыты — **сводный итог Задачи 2 → `docs/roadmap/`** (scoped-коммит): реестр §2
   + приоритизация правок (P1-overlay/P1-udev/P2-smoke-wg/P2-planB + P3-список).
6. **Задача 3** (A-to-Z инструкция сборки) — ПОСЛЕ Задачи 2 и устаканивания железа; обязана
   включить evtest-калибровку channels.toml (см. гейт §2).

---

## Приложение — границы знания (честные оговорки)

- **md5-сверка:** для `install.sh` (`38f68409…`) и `channel_map.py` (`e87100bb…`) копия сверена
  `[RAW-md5]`. Для `crsf-bridge@.service`, `joystick-to-crsf.service`, `joystick_to_crsf.py`,
  `channels.default.toml`, `crsf_telemetry.py`, `telemetry_logger.py` — md5 НЕ сверялся; привязка к
  `6bad9f0` держится на чистом §0 (дерево чистое → рабочая копия = HEAD). Содержимое прочитано целиком.
- **Код НЕ исполнялся** в этой сессии: ни `verify.ps1`/`mypy`/`pytest`/`shellcheck`, ни рантайм.
  Все вердикты — статическое ревью. P2-planB (ImportError) выведен из импорт-графа, не из запуска.
- **Security не аудирован** (наследуется из 25c): напр., `joystick_to_crsf` слушает UDP
  (`open_udp_bidir`) и `crsf_bridge` — без фильтрации source-адреса (открытый UDP примет от любого
  хоста сети). Отдельная тема.
- **Полнота `.service`-списка = `[AGENT]`** (см. §1).
- **Живая Pi не затрагивалась** — все `[PI-TODO]` открыты.
