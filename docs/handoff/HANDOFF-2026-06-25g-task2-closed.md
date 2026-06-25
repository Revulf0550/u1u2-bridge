# HANDOFF — 2026-06-25 (g) · Задача 2 ЗАКРЫТА → реестр в `docs/roadmap/`

> Преемник: `HANDOFF-2026-06-25f-task2-block4-ci-network-wg.md` (коммит `a60872a`).
> **Принцип: факт = подтверждён живой командой в ЭТОЙ сессии.** Память / компакт-саммари /
> приложенные к чату документы / `/mnt/project/` — допущение, помечать или проверять.
> Метки: `[RAW]` прочитано сырьём · `[RAW-grep]` греп, отфильтрован сам · `[RAW-md5]` md5-сверка ·
> `[MEM]` память/прошлые хэндоффы · `[PI-TODO]` требует живой Pi (не закрыто).
>
> **Содержательный реестр находок НЕ дублируется здесь** — он в `docs/roadmap/task2-stack-audit.md`
> (коммит `ca0e509`). Этот файл — рабочая обёртка: старт, инварианты, открытые пробелы, next-steps.

---

## §0 — Состояние репозитория

- HEAD на старте след. чату = **хэш этого хэндофф-коммита (25g)**; под ним `ca0e509`
  (итог Задачи 2), `a60872a` (25f). **ПРОВЕРИТЬ `git log`/`status`, не полагаться.**
- Дерево на момент написания чистое, синхрон с `origin/main` `[RAW]` (после пуша `ca0e509`).
- `install.sh` целиком на диске у Claude в прошлой сессии: `md5 38f684099e51ad7390f59a0fe10b59c3`
  = HEAD; последний коммит, тронувший его — `7def5d8` (2026-06-13).

---

## §1 — Что сделано

- **Задача 2 (сквозной read-only аудит стека) ЗАКРЫТА.** Серия git-аудита:
  `399c883`→`6bad9f0`→`6d1eba9`→`a60872a` (блоки 1–4) + **`ca0e509`** (сводный реестр в roadmap).
- Покрыто сырьём: `crsf_bridge.py`, видео-пайплайны, `install.sh` целиком (§1–§11 + §2b/§7b/§7c),
  `bench/`, `hardware/`, `smoke_test.sh`, `Makefile`/`verify.ps1`/`format.ps1`, маркеры
  `docs/HANDOFF.md`/`DEPLOYMENT.md`, инвентарь `tests/unit/`.
- **P2-planB подтверждён сырьём в финале:** `install.sh §5` (стр.206–217) копирует только
  `crsf_bridge.py` + (drone) `crsf.py` + (drone-u1) `joystick_to_crsf.py`. Трёх модулей
  `channel_map.py`/`crsf_telemetry.py`/`telemetry_logger.py` в списке НЕТ.

---

## §2 — Открытые verify-пробелы (закрыть в новом чате до правок)

1. **`ls common/` не делался** — существование 3 plan-B модулей сильно-выведено (ссылки из
   `§7`-env, тестов, bench-импортов), но не наблюдалось прямо. **Предусловие правки P2-planB.**
2. **`tests/unit/` содержимое не читано** (пропущено по решению) — «покрыты тестами» = вывод
   из имён файлов, не из чтения. Если нужно строго — прочитать 9 модулей сырьём.
3. **Live-Pi не затрагивалась** — все `[PI-TODO]` (§5) открыты.

---

## §3 — Реестр находок (КРАТКО; детали + источники + правки — в `docs/roadmap/task2-stack-audit.md`)

- **P1 (за drone-гейтом):** overlay `m1→m2` `install.sh:135`; осиротевший `setup_udev.sh`.
- **P2:** planB (3 модуля не в §5); smoke-wg (10.10→10.8); smoke-mode-blind; deployment-stale.
- **P3:** CI-divergence; ufw-asymmetry; transport-default; bench-doc-stale; #1/#3/#4/#7/#8.
  static-scope — **закрыт by-design**.
- **Коррекция [MEM]:** `docs/HANDOFF.md` уже депрекейт-баннерован и наполовину живой (§6/§7.1) —
  НЕ релейблить «историческим».

---

## §4 — Next-steps (выбрать в новом чате)

1. **Блок правок** — по приоритизации §2 roadmap-файла. Порядок: P1-overlay → P1-udev →
   P2-planB → P2-smoke-wg → P2-smoke-mode-blind → P2-deployment-stale → P3-пачка.
   P1 + любые рестарты CRSF — **за drone-safety-гейтом**. P2-smoke/deployment — не за гейтом.
   Каждая правка — отдельный scoped-коммит (`diff --cached --stat` перед каждым).
2. **Pi-чеклист (§5)** — Режим 2 (WG off), один транскрипт. Главное предусловие: подтвердить
   `rk3588-uart7-m2.dtbo` (без него P1-overlay не чинить вслепую).
3. **Задача 3** (A-to-Z сборка) — после правок + устаканивания железа; обязана включить
   evtest-калибровку `channels.default.toml` (гейт подтверждён сырьём: `install.sh:250–252`).

---

## §5 — Pi-чеклист (Режим 2, WG off, один транскрипт; НЕ закрыт)

- **P1-overlay (приоритет):** `cat /boot/extlinux/extlinux.conf`; `grep U_BOOT_FDT_OVERLAYS
  /etc/default/u-boot`; `ls /lib/firmware/$(uname -r)/device-tree/rockchip/overlay/ | grep uart7`
  → активный overlay И **существует ли `rk3588-uart7-m2.dtbo`**.
- **P1-udev:** `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` (ожид. нет файла).
- **P2-smoke-wg:** `ip -br addr show wg0` (ожид. 10.8.0.x, НЕ 10.10.0.x).
- **P3 #7:** `ls /dev/input/`, `evtest` → `DEVICE` в `joystick.env` = реальный evdev-узел.
- **Рантайм (25c §4):** `lsusb`; `v4l2-ctl --list-formats` (Arkmicro 640×480 MJPG); `ip -br link`
  (ожид. `enP3p49s0`); `systemctl is-active` сервисов; `udp_drop`, RSSI/LQ, clock-skew (~52 мин u2).

---

## §6 — Рабочие инварианты (не менять)

- Язык — русский. SSH всегда `ssh -i ~/.ssh/u1u2 ubuntu@<ip>`.
- **Drone-safety gate:** винты сняты + Boxer off перед любым рестартом CRSF-сервисов; явное
  разрешение оператора на каждое питание дрона.
- **Два канала ARDOR:** Claude Code (WG on, репо/git/SSH по туннелю) ⟂ батч-PowerShell-транскрипт
  (WG off, мост `192.168.1.x`). Kill-switch `AllowedIPs=0.0.0.0/0` — параллельного доступа нет.
  Переключение инструментов — анонсировать.
- §0-аудит (git + live-сервисы) ПЕРЕД любыми мутациями/хэндоффом. Транспорт — по `PEER=` в env,
  НЕ по `systemctl is-active`. Серийный ping (`-c 4`+) за радио — одиночный врёт на холодном ARP.
- Scoped-коммиты: НИКОГДА `git add -A`; `diff --cached --stat` перед каждым; форвард-онли.
- Файлы хэндоффа/скриптов — генерировать на стороне Claude, отдавать скачиванием, не heredoc.
- Сырьё > саммари агента (агент мислейблит). `view` усекает середину >16 KB — читать диапазонами.
- Вложения чата и `/mnt/project/` — СТАЛЕ. Аудит/работа — ТОЛЬКО по живому репо.

---

## §7 — Немедленный TODO на старте нового чата

1. **Режим 1 (WG on).** `cd C:\Users\ARDOR\Documents\Projects\u1u2-bridge;
   git --no-pager log --oneline -5; git status -sb` — §0-аудит. Ожидаемо HEAD = хэш 25g-коммита,
   синхрон, чисто (ПРОВЕРИТЬ).
2. **`ls common/`** (закрыть пробел §2.1) — подтвердить наличие `channel_map.py`,
   `crsf_telemetry.py`, `telemetry_logger.py`, `crsf.py`, `joystick_to_crsf.py`.
3. Выбрать ветку §4 (правки / Pi-чеклист / Задача 3) и идти по приоритизации roadmap.
