# HANDOFF — 2026-06-26 (d) · DEPLOYMENT.md на канон + 2 урока

> Преемник: `HANDOFF-2026-06-26c-num4-closed-nongated-exhausted.md` (старт-HEAD этой сессии `9f52ea4`).
> **Принцип: факт = подтверждён живой командой в ЭТОЙ сессии.** Память / компакт-саммари /
> приложенные к чату документы / `/mnt/project/` — допущение, помечать или проверять.
> Метки: `[RAW]` сырьё · `[RAW-grep]` греп-сверка · `[RAW-md5]` md5-сверка · `[MEM]` память/прошлые
> хэндоффы · `[PI-TODO]` нужна живая Pi.
>
> Реестр находок — `docs/roadmap/task2-stack-audit.md`.

---

## §0 — Состояние репозитория (подтверждено сырьём в PowerShell на конец сессии)

- **HEAD = `f54ac3c`**. `[RAW]` (git status -sb: дерево чистое, синхрон).
- `## main...origin/main` без ahead/behind — всё запушено. `[RAW]`
- Серия этой сессии (3 коммита) поверх старт-HEAD `9f52ea4`:
  `c4aced9` → `27502c0` → `f54ac3c`.

**Старт нового чата:** `cd C:\Users\ARDOR\Documents\Projects\u1u2-bridge;
git --no-pager log --oneline -5; git status -sb` — §0-аудит. Ожидаемо HEAD = `f54ac3c`,
синхрон, чисто — **ПРОВЕРИТЬ, не полагаться на хэш из этого файла.**

---

## §1 — Что сделано в этой сессии (Режим 1, WG on, рабочее железо НЕ трогалось)

Закрыта backlog-часть **P2-deployment-stale**. Три коммита, прежним ритмом
(сырьё md5-сверенной копией в Downloads → view → diff на review → правка по содержимому →
стейдж по имени → пауза на `--cached --stat` → коммит в PowerShell → push).

1. **DEPLOYMENT.md — тело** — `c4aced9`
   (`docs(deploy): тело DEPLOYMENT.md на канон (был RS485-стале)`), +163/−124.
   - §4-хвост→§9 переписаны с двухканальной RS485-эры на одноканальную архитектуру.
   - Оси канона (из baseline env `docs/baseline/u1/crsf-p1.env`, `u2/crsf-elrs.env` —
     побайтовый эталон tunnel-снимка 2026-06-04, + `install.sh`):
     - CRSF-инстанс — один на роль: `crsf-bridge@p1` (u1) / `crsf-bridge@elrs` (u2).
       Пары `@tx1/@tx2` больше нет.
     - UDP-порт CRSF: `14552` (был `14550/14551`).
     - Serial: u1 — CH340 напрямую `/dev/ttyUSB0` (SerialNumber=0 → symlink невозможен);
       u2 — UART7 `/dev/ttyS7` (overlay m2, pin 26). udev-symlink'ов `/dev/ttyACM-*` нет.
     - WG (bench): `10.8.0.0/24` (u1 `10.8.0.6`, u2 `10.8.0.7`), был `10.10.0.x`.
     - Транспорт двухрежимный через `TRANSPORT`: `tunnel` (WG `10.8.0.x`) /
       `direct` (CPE710 LAN `192.168.1.x`). Не хардкодить подсеть.
   - §5 переписан целиком: udev для текущего железа не нужен (объяснено почему).
     `setup_udev.sh` помечен как RS485-реликт, не запускается.
   - §5.3 рестарт CRSF — с явным drone-safety gate (винты сняты + Boxer off).
   - §7 (smoke) — обобщён БЕЗ выдуманного `[OK]`-вывода: точный формат вывода smoke_test.sh
     в этой сессии сырьём не видели; отослали к самому скрипту. Включает RKMPP-элемент по роли
     (u1 `mppvideodec` / u2 `mpph264enc` — отражён #4-фикс).
   - Баннер: «частично устарел» → «приведён к канону 2026-06-26».
   - Верифицирован `[RAW-grep]`: 0 вхождений `14550/14551`, `10.10.0.x`; остаточные
     `@tx*`/`ttyACM` — только в депрекейт-контексте («больше нет», «не запускается»).
     Канон-токены на месте (`@p1/@elrs` ×15, `14552` ×3, `ttyUSB0`/`ttyS7` ×12, `10.8.0.x` ×16).
   - НЕ закоммичено вслепую: §1–§3 DEPLOYMENT.md перенесены дословно (были верны).

2. **Реестр** — `27502c0`
   (`docs(roadmap): P2-deployment-stale закрыт — тело переписано c4aced9`), +2/−2.
   - Статус-буллет: «Тело на канон не переписано — backlog» → «Тело переписано на канон
     коммитом c4aced9».
   - §2 пункт 6: «баннер/переписать» → «✅ ЗАКРЫТО: баннер 9cc4efa + тело переписано c4aced9».

3. **CLAUDE.md Lessons** — `f54ac3c`
   (`docs(CLAUDE): +2 урока 2026-06-26 — PowerShell/agent git-workflow`), +10.
   - Урок 1: PowerShell-коммит невидим Claude Code до перечитки git (ложное «M» —
     пересинхрон через `git log`; проверка `git cat-file -t <hash>`).
   - Урок 2: многострочный коммит в PowerShell — два `-m`, не heredoc/printf
     (проверка `git log -1 --format='%s%n%b'`).

---

## §2 — Состояние реестра: не-гейтовая часть ИСЧЕРПАНА

Вся не-гейтовая часть Задачи 2 закрыта/by-design. P2-deployment-stale (последний крупный
не-гейтовый остаток) теперь ЗАКРЫТ полностью (баннер `9cc4efa` + тело `c4aced9` + реестр `27502c0`).

В Режиме 1 без drone-safety-гейта по реестру делать нечего.

---

## §3 — Что осталось — ВСЁ за drone-safety-гейтом (Режим 2, WG off, живая Pi)

Только Pi-сессия. Предусловие любой правки CRSF: **винты сняты + Boxer off** перед рестартом.

- **P1-overlay** — `install.sh:135` деплоит `rk3588-uart7-m1.dtbo` (pins 29/38) вместо боевого
  **m2** (pin 26, подтв. `gpio readall` 2026-06-13). **Предусловие правки** [PI-TODO]:
  подтвердить наличие `rk3588-uart7-m2.dtbo` в `/lib/firmware/$(uname -r)/.../overlay/`.
  БЕЗ него не чинить вслепую. Примирить коммент `:132` и футер `:417`.
- **P1-udev** — `setup_udev.sh` не вызывается из `install.sh` (только echo-напоминания).
  [PI-TODO]: `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` (ожид. нет файла) → решить:
  переписать `setup_udev.sh` под CH340/UART7 или удалить. *(DEPLOYMENT.md §5 от исхода уже
  не зависит — runbook udev-шаг исключил.)*
- **#7** — js0/evdev рассинхрон: `DEVICE` в `joystick.env` (режим drone на u1, сервис
  `joystick-to-crsf`) может не совпадать с реальным evdev-узлом (узлы `js*`/`event*` плавают
  между перезагрузками). Диагностика/калибровка — `evtest` на живой u1 с воткнутым джойстиком.
  Это же — evtest-гейт калибровки `channels.default.toml`. [PI-TODO].

**Задача 3** (A-to-Z сборка) — после устаканивания железа; обязана включить evtest-калибровку
`channels.default.toml`.

---

## §4 — Pi-чеклист (Режим 2, WG off, один транскрипт; [PI-TODO], НЕ закрыт)

- **P1-overlay (приоритет):** `cat /boot/extlinux/extlinux.conf`; `grep U_BOOT_FDT_OVERLAYS
  /etc/default/u-boot`; `ls /lib/firmware/$(uname -r)/.../overlay/ | grep uart7` → активный
  overlay И **существует ли `rk3588-uart7-m2.dtbo`** (предусловие правки `:135`).
  `gpio readall` (pin 26 vs 29/38).
- **P1-udev:** `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` (ожид. нет файла).
- **#7:** `ls /dev/input/`, `evtest` → `DEVICE` в `joystick.env` = реальный evdev-узел
  (он же — evtest-гейт калибровки `channels.default.toml`).
- **Рантайм:** `lsusb`; `v4l2-ctl --list-formats` (Arkmicro 640×480 MJPG); `ip -br link`
  (ожид. `enP3p49s0`); транспорт — по `PEER=` в env, НЕ по `systemctl is-active`.

---

## §5 — Рабочие инварианты (не менять)

- Язык — русский. SSH всегда `ssh -i ~/.ssh/u1u2 ubuntu@<ip>`.
- **Два канала ARDOR:** Claude Code (WG on, Режим 1, репо/git/SSH) ⟂ батч-PowerShell (WG off,
  Режим 2, мост `192.168.1.x`). Kill-switch `AllowedIPs=0.0.0.0/0` — параллельного доступа нет.
  Переключение анонсировать.
- **Drone-safety gate:** винты сняты + Boxer off перед любым рестартом CRSF-сервисов.
- §0-аудит (git + при Pi-работе live) ПЕРЕД любыми мутациями/хэндоффом. Транспорт — по `PEER=` в env.
- Scoped-коммиты: НИКОГДА `git add -A`; `diff --cached --stat` перед каждым; форвард-онли.
- **Ритм правки:** сырьё → diff на review → str_replace по содержимому (НЕ по номерам строк) →
  `git diff` → стейдж по имени → пауза на `--cached --stat` → коммит → пауза → push с «ок».
  Один логический блок за раз.
- **Сырьё > саммари агента.** Целевые файлы читать md5-сверенной копией в Downloads → drag →
  view, НЕ через stdout агента (сворачивает в `+N lines`, путает номера строк).
- Вложения чата и `/mnt/project/` — СТАЛЕ. Работа — ТОЛЬКО по живому репо.
- **Коммит идёт в PowerShell, не bash.** Многострочные commit-сообщения — через два `-m`:
  `git commit -m "subject" -m "body"`. НЕ heredoc/printf (`printf`/`/tmp/` в PowerShell нет).
  Кириллица в аргументах PowerShell 7 проходит.
- **НОВЫЙ УРОК (эта сессия): PowerShell-коммит невидим Claude Code до перечитки git.** После
  каждого PowerShell-коммита давать агенту `git log --oneline -2` на пересинхрон, прежде чем
  доверять его «M / не закоммичено». Проверка реальности объекта: `git cat-file -t <hash>`.
  (Занесено в CLAUDE.md Lessons коммитом `f54ac3c`.)

---

## §6 — Немедленный TODO на старте нового чата

1. **Режим 1 (WG on).** §0-аудит: `git --no-pager log --oneline -5; git status -sb`.
   Ожидаемо HEAD = `f54ac3c`, синхрон, чисто (ПРОВЕРИТЬ).
2. Осталось ВСЁ за drone-safety-гейтом (Режим 2, WG off, живая Pi, винты сняты + Boxer off):
   P1-overlay / P1-udev / #7 — по §4 чеклисту. Смена канала (анонсировать).
   - P1-overlay сначала read-only (предусловие: существует ли `rk3588-uart7-m2.dtbo`),
     потом правка `install.sh:135` m1→m2.
   - #7: `evtest` на живой u1 с джойстиком — `DEVICE` в `joystick.env` vs реальный evdev-узел.
3. Любую правку — прежним ритмом (§5). P1 + рестарты CRSF — только за drone-safety-гейтом.
4. (опц.) Закоммитить этот хэндофф в `docs/handoff/` отдельным коммитом, если нужен в репо.
