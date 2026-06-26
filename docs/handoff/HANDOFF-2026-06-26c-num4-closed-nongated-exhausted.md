# HANDOFF — 2026-06-26 (c) · #4 закрыт (код + реестр), не-гейтовая P3 исчерпана

> Преемник: `HANDOFF-2026-06-26b-p3-block-pushed.md` (старт-HEAD этой сессии `aacc1ed`).
> **Принцип: факт = подтверждён живой командой в ЭТОЙ сессии.** Память / компакт-саммари /
> приложенные к чату документы / `/mnt/project/` — допущение, помечать или проверять.
> Метки: `[RAW]` сырьё · `[RAW-md5]` md5-сверка · `[MEM]` память/прошлые хэндоффы · `[PI-TODO]` нужна живая Pi.
>
> Реестр находок — `docs/roadmap/task2-stack-audit.md` (синхронен с фактом на конец сессии, см. §1).
> Этот файл — рабочая обёртка: старт, что сделано, что осталось, инварианты.

---

## §0 — Состояние репозитория (подтверждено сырьём на конец сессии)

- **HEAD = `ea2523f`**. `[RAW]` (git status -sb на конец сессии: дерево чистое, синхрон).
- `## main...origin/main` без ahead/behind — всё запушено. `[RAW]`
- Серия этой сессии (2 коммита) поверх старт-HEAD `aacc1ed`:
  `78bd58c` → `ea2523f`.

**Старт нового чата:** `cd C:\Users\ARDOR\Documents\Projects\u1u2-bridge;
git --no-pager log --oneline -8; git status -sb` — §0-аудит. Ожидаемо HEAD = `ea2523f`,
синхрон, чисто — **ПРОВЕРИТЬ, не полагаться на хэш из этого файла**.

---

## §1 — Что сделано в этой сессии (Режим 1, WG on, рабочее железо НЕ трогалось)

Закрыт **#4** (последний не-гейтовый пункт реестра Задачи 2). Два коммита, прежним ритмом
(сырьё md5-сверенной копией в Downloads → view → diff на review → str_replace по содержимому →
стейдж по имени → пауза на `--cached --stat` → коммит → push).

1. **#4 — код** — `78bd58c` (`fix(smoke): RKMPP-чек под роль — u1 mppvideodec / u2 mpph264enc`).
   - Секция `RKMPP` в `smoke_test.sh` **безусловно** проверяла `mpph264enc` (энкодер) на обеих
     ролях. Гейта по MODE/ROLE не было (в отличие от RKMPP-чека в `install.sh:102` — там гейт
     `MODE==bench`; аналогия «как в install.sh» НЕ держится).
   - На u1 рантайм — `mppvideodec` (декодер, `video_rx.sh`), энкодер не используется.
   - Введён `RKMPP_ELEM` по ветке роли (u1=`mppvideodec`, u2=`mpph264enc`), симметрично
     `VIDEO_UNIT`/`CRSF_INST`. `gst-inspect-1.0 "$RKMPP_ELEM"` проверяет именно используемый ролью.
   - **Характер дефекта уточнён (реестр формулировал неточно):** был НЕ ложный FAIL, а
     **ложный PASS / missed-failure**. `gstreamer1.0-rockchip1` атомарен (enc+dec вместе); в
     краевом случае (есть enc, нет dec) u1 прошёл бы чек энкодера, **пропустив** падение
     `video-rx` в Restart-loop. u2 не изменился (там `mpph264enc` и был нужен).
   - shellcheck-безопасно (`RKMPP_ELEM` присваивается и используется — нет SC2034). Локально
     НЕ прогонялось (smoke — Linux-side; на Windows канон `verify.ps1`). [PI-TODO: при случае.]

2. **#4 — реестр** — `ea2523f` (`docs(roadmap): #4 РЕШЕНО 78bd58c — RKMPP-чек по роли + синхрон §2`).
   - Таблица P3 (строка 122): #4 → **✅ РЕШЕНО `78bd58c`** с уточнением характера (ложный PASS).
   - §2 пункт 7 «P3-пачка» свёрнут к факту: открыт только **ufw-asymmetry** (by-design, до
     трека D), остальное закрыто со ссылками (CI-divergence `35a37af`, bench-doc-stale
     `2b7e365`+`951f7ef`, transport-default by-design, #4 `78bd58c`).

---

## §2 — Состояние реестра: не-гейтовая часть ИСЧЕРПАНА

По `task2-stack-audit.md` (HEAD `ea2523f`) в Режиме 1 **без** drone-safety-гейта делать нечего:
- **Решено / by-design:** #1 (by-design), #3 (минор, осознанно оставлен), #4 (`78bd58c`),
  #8 (—), CI-divergence (`35a37af`), static-scope (by-design), ufw-asymmetry (by-design до
  трека D), transport-default (by-design), bench-doc-stale (`2b7e365`+`951f7ef`),
  P2-deployment-stale (баннер `9cc4efa`), P2-smoke-wg (`d1fd177`), P2-smoke-mode-blind
  (`e9c109d`), P2-planB (`af481cc`).
- **Единственный не-гейтовый остаток (крупный, отдельная сессия):** `docs/DEPLOYMENT.md` —
  **тело** переписать на канон. Баннер «частично устарел» (`9cc4efa`) уже прикрывает ловушку;
  тело на канон НЕ переписано — backlog. 5 осей расхождения зафиксированы в баннере и в
  реестре (инстансы `@tx1/tx2`→`@p1/@elrs`; порт `14550/14551`→`14552`; `/dev/ttyACM-*`+
  `setup_udev.sh` RS485-эра; WG `10.10.0.x`→`10.8.0.x`; «Pi 5»→«5 Max»/`enP3p49s0`).

---

## §3 — Что осталось — ВСЁ за drone-safety-гейтом (Режим 2, WG off, живая Pi)

Только Pi-сессия. Предусловие любой правки CRSF: **винты сняты + Boxer off** перед рестартом.

- **P1-overlay** — `install.sh:135` деплоит `rk3588-uart7-m1.dtbo` (pins 29/38) вместо боевого
  **m2** (pin 26, подтв. `gpio readall` 2026-06-13). **Предусловие правки** [PI-TODO]:
  подтвердить наличие `rk3588-uart7-m2.dtbo` в `/lib/firmware/$(uname -r)/.../overlay/`.
  БЕЗ него не чинить вслепую. Примирить коммент `:132` и футер `:417`.
- **P1-udev** — `setup_udev.sh` не вызывается из `install.sh` (только echo-напоминания).
  [PI-TODO]: `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` (ожид. нет файла) → решить:
  переписать `setup_udev.sh` под CH340/UART7 или удалить. (Кандидат: `setup_udev.sh:~190`
  печатает устаревшую restart-команду `@tx1/@tx2` вместо боевых `@p1/@elrs`.)
- **#7** — js0/evdev рассинхрон (`DEVICE` в `joystick.env` vs реальный узел), evtest-гейт. [PI-TODO].

**Задача 3** (A-to-Z сборка) — после устаканивания железа; обязана включить evtest-калибровку
`channels.default.toml`.

---

## §4 — Pi-чеклист (Режим 2, WG off, один транскрипт; [PI-TODO], НЕ закрыт)

- **P1-overlay (приоритет):** `cat /boot/extlinux/extlinux.conf`; `grep U_BOOT_FDT_OVERLAYS
  /etc/default/u-boot`; `ls /lib/firmware/$(uname -r)/.../overlay/ | grep uart7` → активный
  overlay И **существует ли `rk3588-uart7-m2.dtbo`** (предусловие правки `:135`).
  `gpio readall` (pin 26 vs 29/38).
- **P1-udev:** `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` (ожид. нет файла);
  `grep -n 'crsf-bridge@tx' setup_udev.sh` (ожид. устаревшая строка ~190).
- **CI-divergence / #4 verify:** при случае `make verify` на Pi — проверить, что shellcheck-цель
  работает И что обновлённый smoke RKMPP-чек по роли (`gst-inspect $RKMPP_ELEM`) проходит на u1.
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
- **Сырьё > саммари агента.** Целевые файлы читать **md5-сверенной копией в Downloads → drag →
  view**, НЕ через stdout агента (сворачивает в `+N lines`, путает номера строк).
- Вложения чата и `/mnt/project/` — СТАЛЕ. Работа — ТОЛЬКО по живому репо.
- **НОВЫЙ УРОК (эта сессия) — коммит идёт в PowerShell, не bash.** Финальный git-блок
  исполняется в PowerShell-консоли. `printf … > /tmp/commitmsg.txt; git commit -F` там НЕ
  работает (`printf` не cmdlet; `/tmp/` нет) → `commit -F` падает, `push` тихо говорит
  «up-to-date» (коммита нет, но stage остаётся — `M` в `status`, восстановимо). **Многострочные
  commit-сообщения — через два `-m`:** `git commit -m "subject" -m "body"`. Кириллица в
  аргументах PowerShell 7 проходит. (Инвариант против heredoc держится — это НЕ heredoc.)
  **Кандидат в `CLAUDE.md` Lessons.**

---

## §6 — Немедленный TODO на старте нового чата

1. **Режим 1 (WG on).** §0-аудит: `git --no-pager log --oneline -8; git status -sb`.
   Ожидаемо HEAD = `ea2523f`, синхрон, чисто (ПРОВЕРИТЬ).
2. Развилка (не-гейтовая P3 исчерпана — оба пути крупные, отдельные):
   - **Pi-сессия (Режим 2, WG off, drone-safety-гейт)** для P1-overlay / P1-udev / #7 —
     по §4 чеклисту. Смена канала. P1-overlay сначала read-only (предусловие m2.dtbo), потом правка.
   - **или `DEPLOYMENT.md` тело** (Режим 1, крупная док-правка на канон; баннер уже прикрывает).
3. Любую правку — прежним ритмом (§5). P1 + рестарты CRSF — только за drone-safety-гейтом.
4. (опц.) Занести урок про PowerShell-коммит (§5) в `CLAUDE.md` Lessons отдельным коммитом.
