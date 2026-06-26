# Задача 2 — Сквозной аудит стека u1u2-bridge (итог)

> **Назначение.** Накопительный реестр находок сквозного read-only аудита кодовой базы
> u1u2-bridge + приоритизация правок. Собран по живому репо на HEAD `a60872a`
> (синхрон с `origin/main`, дерево чистое на момент аудита).
>
> **Метки источника** (дисциплина проекта): `[RAW]` — прочитано целиком/диапазонами;
> `[RAW-grep]` — из выгруженного grep, отфильтровано самостоятельно; `[RAW-md5]` —
> целостность копии сверена md5; `[MEM]` — память/прошлые хэндоффы; `[PI-TODO]` —
> требует подтверждения на живой Pi (не закрыто). `[AGENT]`-саммари в итог НЕ включались.
>
> **Граница аудита:** read-only. Всё **каталогизировано, не исправлено**. Правки —
> отдельным scoped-решением; P1 + правки u2/UART7 — за drone-safety-гейтом.
> Код в этой серии сессий **не исполнялся** — все вердикты статические.

---

## §0 — База аудита (что прочитано сырьём)

Покрытие по блокам (серия git-аудита `399c883`→`6bad9f0`→`6d1eba9`→`a60872a`):

| Артефакт | Покрытие | Метод |
|---|---|---|
| `common/crsf_bridge.py`, видео-пайплайны | блок 1 | `[RAW]` (25c) |
| `install.sh` §2/§5/§6/§7 (udev/копирование/env), `smoke_test.sh` (частично) | блок 2 | `[RAW]` (25d) |
| `systemd`-юниты, plan B | блок 3 | `[RAW]` (25e) |
| `Makefile`, `verify.ps1`, `format.ps1`, `install.sh` §2b/§3/§4/§7c, WG-трекинг | блок 4 | `[RAW]` (25f) |
| `install.sh` §1/§8/§9/§10/§11 | блок 5 | `[RAW]` (эта сессия) |
| `bench/` (`crsf_udp_source.py`, `loopback.py`), `hardware/` (2 теста + README) | блок 5 | `[RAW]` + `[RAW-md5]` |
| `smoke_test.sh` целиком | блок 5 | `[RAW]` (md5 `f8da8677…`, 160 строк) |
| `docs/HANDOFF.md`, `docs/DEPLOYMENT.md` | блок 5 | `[RAW-grep]` (шапки + маркеры стале) |
| `tests/unit/` (состав) | блок 5 | инвентарь `[RAW]`, содержимое — пропущено по решению |

`install.sh` — целиком на диске, `md5 38f684099e51ad7390f59a0fe10b59c3` = HEAD, последний
коммит, тронувший его, — `7def5d8` (2026-06-13); всё после — только `docs/`.

---

## §1 — Реестр находок

### P1 — блокеры деплоя (за drone-safety-гейтом)

#### P1-overlay — `install.sh:135` деплоит overlay `m1` вместо боевого `m2`
- `[RAW]` `install.sh:135` регистрирует `rk3588-uart7-m1.dtbo`; коммент `:132` и футер `:417`
  («пины 29/38 → REBOOT») согласованы с `m1` — §2b внутренне непротиворечив.
- Раскол — с §7-комментом `:267–268` (`ttyS7 = UART7 m2 → pin 26`, проверено `gpio readall`
  2026-06-13) и с `hardware/README.md` («overlay UART7-**M2**»). Боевая Pi работает на m2.
- `[RAW]` источник раскола: `7def5d8` примирил коммент+`CLAUDE.md` на m2, **а код `:135`
  оставил на m1** — частичная правка (коммент ≠ код).
- **Следствие:** свежий `install.sh u2` зарегистрирует m1 → после reboot UART7 встанет на
  пины 29/38, НЕ на боевой pin 26. **install.sh не воспроизводит полевую конфигурацию.**
- **Правка:** `:135` `m1→m2`, примирить `:132`/`:417`. **Предусловие** `[PI-TODO]`:
  подтвердить наличие `rk3588-uart7-m2.dtbo` в `/lib/firmware/.../overlay/`.

#### P1-udev — `setup_udev.sh` осиротел
- `[RAW]` `install.sh §8` (стр.306–308): генерация правил вынесена в `setup_udev.sh`,
  но сам скрипт **не вызывается** — только echo-напоминания. Гарантии, что оператор
  запустит, нет.
- u1-путь намеренно **не зависит от udev** (`:316`: CH340 даёт `SerialNumber=0` →
  symlink невозможен → `crsf-p1.env` берёт `/dev/ttyUSB0` напрямую). Находка касается
  содержимого `setup_udev.sh` для прочего железа (RS485-эра → CH340/UART7).
- **Правка/предусловие** `[PI-TODO]`: `ls -l /etc/udev/rules.d/90-u1u2-uart.rules`
  (ожид. нет файла); решить — переписать `setup_udev.sh` под CH340/UART7 или удалить.

### P2 — реальные дефекты (диагностика / не за гейтом, кроме рестартов CRSF)

#### P2-planB — `install.sh §5` не копирует 3 модуля → краш-луп `joystick-to-crsf`
- `channel_map.py` + `crsf_telemetry.py` + `telemetry_logger.py` не входят в §5-копирование
  → `joystick-to-crsf.service` на drone-u1 падает в Restart-loop (детали — 25e §2).
- **Усилено сырьём:** `install.sh:373` `[RAW]` enable-ит именно `joystick-to-crsf` (тот
  самый краш-луп-юнит); инвентарь `tests/unit/` `[RAW]` показал `test_channel_map.py`,
  `test_crsf_telemetry.py`, `test_telemetry_logger.py` → модули **существуют и покрыты
  тестами** ⇒ это **deploy-gap**, не «модулей нет».
- **Правка:** добавить 3 модуля в §5-копирование. Любой рестарт CRSF — за drone-гейтом.

#### P2-smoke-wg — `smoke_test.sh` пингует мёртвую подсеть 10.10.0.x
- `[RAW]` `smoke_test.sh:~25/31` `PEER_IP_WG=10.10.0.2/10.10.0.1` — проектный overlay-WG
  (не развёрнут). Живой стек — **10.8.0.x**.
- **Подтверждено сырьём:** `docs/HANDOFF.md §6:942` `[RAW-grep]` — боевой WG = wg-easy VPS
  `95.140.147.108`, u2-pi `10.8.0.7`, u1-pi `10.8.0.6`, `AllowedIPs 10.8.0.0/24`.
- Логика `:~121–130`: `wg0` поднят (на 10.8.0.x) → ping 10.10.0.x не пройдёт → **ложный
  FAIL** постдеплойного smoke. `PEER_IP` (direct, 192.168.1.x) — корректен.
- **Правка:** `:25/31` → 10.8.0.x (или параметризовать из env/`TRANSPORT`).

#### P2-smoke-mode-blind — `smoke_test.sh` слеп к MODE → ложный FAIL на drone-u1 *(НОВОЕ)*
- `[RAW]` `smoke_test.sh` принимает **только ROLE**; для u1 жёстко `CRSF_INST=p1` →
  проверяет `crsf-bridge@p1` активным + `SERIAL_DEV` из `crsf-p1.env`.
- Но `install.sh §11:372–378` `[RAW]` в **drone+u1** поднимает `joystick-to-crsf`
  (не `crsf-bridge@p1`), а §8:310 — «UART-адаптер не нужен» → `crsf-p1.env`/serial может
  отсутствовать by design.
- **Следствие:** `smoke_test.sh u1` после drone-деплоя даёт **ложный FAIL** на CRSF-юните
  + serial-проверке. Тот же класс, что P2-smoke-wg, но отдельный артефакт.
- **Правка:** добавить MODE-параметр/детект, ветвить `joystick-to-crsf` vs `crsf-bridge@p1`.

#### P2-deployment-stale — `docs/DEPLOYMENT.md` без баннера, насквозь стале *(НОВОЕ)*
- **СТАТУС:** РЕШЕНО баннером (коммит `9cc4efa`). Уточнение: не «насквозь
  стале» — док гибрид, §4 (`install.sh`) валидный канон, стале только ручные
  env/udev-шаги §5/§6. Тело переписано на канон коммитом c4aced9.
- `[RAW-grep]` активный runbook **без депрекейт-дисклеймера**, противоречит канону
  `install.sh` по всем осям:
  - инстансы `crsf-bridge@tx1/tx2` (канон `p1/elrs`);
  - порты `14550/14551` (канон `14552`);
  - WG `10.10.0.x` (живое `10.8.0.x`);
  - устройства `/dev/ttyACM-CRSF1/2` + `setup_udev.sh` (RS485-эра);
  - «Orange Pi 5» (не «5 Max»).
- **Ловушка:** идущий по DEPLOYMENT.md вместо `install.sh` соберёт несовместимый env.
- **Правка:** добавить депрекейт-баннер по образцу `docs/HANDOFF.md` **или** переписать
  на канон. (Не за гейтом — доки.)

> **Корректировка плана [MEM]:** `docs/HANDOFF.md` **уже** депрекейт-баннерован
> (`:3`, 2026-05-22; NB `:5` 2026-06-13 — UART7-M2/pin26 ВЕРНЫ). При этом §6/§7.1
> (стр.940–967, 1017–1028) — **живой полевой лог** (bench-WG 10.8.0.x, §7.1 RS485
> РЕШЁН). Релейблить весь док «историческим» — **ошибка**: он гибрид. Действие —
> **ничего** (баннер достаточен); опц. мигрировать §6/§7.1 в `CLAUDE.md`.

### P3 — наблюдения (не блокеры)

| ID | Суть | Источник | Правка |
|---|---|---|---|
| #1 | RKMPP-чек гейтится `MODE==bench` (`install.sh:102`) | `[RAW]` | — (by design) |
| #3 | `netplan apply\|\|true` (`:200`) — упавший netplan не оборвёт install | `[RAW]` | минор |
| #4 | smoke проверяет `mpph264enc` (энкодер) на u1 (роль только декод) | `[RAW]` | ✅ РЕШЕНО `78bd58c` — `RKMPP_ELEM` по роли (u1 `mppvideodec` / u2 `mpph264enc`). Был не ложный FAIL, а ложный PASS: битый декодер на u1 прошёл бы чек энкодера, пропустив падение `video-rx` |
| #7 | js0/evdev рассинхрон — `DEVICE` в `joystick.env` vs реальный узел | `[PI-TODO]` | evtest-гейт |
| #8 | незамапленный канал = 992 | `[MEM]` | — |
| CI-divergence | `make verify` без shellcheck (слабее `verify.ps1`) | `[RAW]` | ✅ РЕШЕНО `35a37af` — shellcheck-цель в Makefile + в зависимостях verify |
| static-scope | bench/hardware вне ruff/mypy | `[RAW]` | **ЗАКРЫТО как by-design** (см. ниже) |
| ufw-asymmetry | `§7c` даёт u1 video-allow (5600), не CRSF-allow (14552) | `[RAW]` | by-design: каждый узел открывает порт того, что ПРИНИМАЕТ (u2←CRSF 14552, u1←видео 5600). u1 CRSF-allow не нужен до обратной телеметрии (трек D), тогда добавить |
| transport-default | `:56` `TRANSPORT=tunnel` дефолт; поле = direct | `[RAW]` | by-design: дефолт tunnel осознан, защищён авто-SKIP_NETPLAN (`:63`) + объяснён в шапке install.sh. Оператор поля задаёт `TRANSPORT=direct` явно |
| bench-doc-stale | докстринги bench/hardware: `192.168.31.100` (чужая подсеть, 3 файла), порт `14550` в `crsf_udp_source.py` (канон 14552) | `[RAW]` | ✅ РЕШЕНО `2b7e365` (hardware → `<u2-pi-ip>`) + `951f7ef` (порт 14552) |

**P3-static-scope — закрыто by-design:** `loopback.py:62` `[RAW]` прямым текстом
(«инструмент, не production-код»); чистые хелперы `compute_echo_deadline`/
`compute_period_cap` покрыты `tests/unit/test_loopback.py` (в scope), с регрессией
`207ff66` на инвариант `cap ≥ deadline`; `hardware/`-скрипты standalone scp-деплоятся в
`~/hardware/` (self-contained). Остаточный минор: `bench/crsf_udp_source.py` импортит
API из `common` (`build_rc_frame`, channel-константы), напрямую не в mypy-scope.

---

## §2 — Приоритизация правок (для блока правок, scoped)

> Порядок — по риску для деплоя/полёта. Все правки — **после** аудита, отдельными
> scoped-коммитами (никогда `git add -A`; `diff --cached --stat` перед каждым).

1. **P1-overlay** — `[PI-TODO]` проверить `rk3588-uart7-m2.dtbo` → `install.sh:135 m1→m2`
   + примирить `:132`/`:417`. **Drone-safety-гейт.**
2. **P1-udev** — `[PI-TODO]` статус `90-u1u2-uart.rules` → переписать `setup_udev.sh`
   под CH340/UART7 или удалить. **Drone-safety-гейт.**
3. **P2-planB** — добавить 3 модуля в `install.sh §5`. Рестарт CRSF — **за гейтом**.
4. **P2-smoke-wg** — `smoke_test.sh` 10.10→10.8 (или параметризовать). Не за гейтом.
5. **P2-smoke-mode-blind** — MODE-осведомлённость в `smoke_test.sh`. Не за гейтом.
6. **P2-deployment-stale** — ✅ ЗАКРЫТО: баннер 9cc4efa + тело переписано c4aced9.
7. **P3-пачка** — ufw-asymmetry (u1 CRSF-allow, до трека D). Остальное закрыто:
   CI-divergence `35a37af`, bench-doc-stale `2b7e365`+`951f7ef`, transport-default
   (by-design), #4 декодер-чек u1 `78bd58c`.

---

## §3 — Подтверждённая сильная инженерия (перенос знания)

- **`common/crsf_bridge.py`:** 64 KiB UDP-буферы (критично при Wi-Fi-джиттере), 8N1
  неблокирующее, авто-реконнект UART, signal→стоп-флаг (без `os._exit`).
- **`install.sh`:** гарды `SKIP_APT`/`SKIP_VIDEO`/`SKIP_NETPLAN`; авто-iface (UP-фильтр
  + ручной override); `TRANSPORT` — единый источник истины (env CRSF+видео деривятся);
  UFW строго аддитивно (никогда `enable`/смены default-policy — урок 2026-05-24/06-05);
  dialout-group чек; cage+waylandsink через `tmpfiles.d` (kmssink убит VOP2, hw-подтв.
  2026-06-04).
- **`verify.ps1`:** честный fail-fast 5-стадийный гейт, shellcheck рекурсивно по всем `.sh`.
- **`smoke_test.sh`:** ANSI гейтится `[[ -t 1 ]]`; серийный ping `-c 3 -W 1`; `SERIAL_DEV`
  из env (не хардкод); WG-чек = warn-skip при отсутствии wg0.
- **`bench/loopback.py`:** честный докстринг bench≠production; инвариант `cap ≥ deadline`
  (регрессия `207ff66`).
- **`bench/crsf_udp_source.py`:** drone-safety встроена — `sweep` форсит AUX1 в low
  (не армится), `arm-toggle` явно требует снять винты.
- **WG-секреты:** реальные конфиги/ключи gitignored, tracked только шаблон.

---

## §4 — Pi-чеклист (перенос, не закрыто; Режим 2, WG off, один транскрипт)

`[PI-TODO]` — живая Pi в этой серии не затрагивалась:
- **P1-overlay:** `cat /boot/extlinux/extlinux.conf`; `grep U_BOOT_FDT_OVERLAYS
  /etc/default/u-boot`; `ls /lib/firmware/$(uname -r)/.../overlay/ | grep uart7` →
  активный overlay И **существует ли `rk3588-uart7-m2.dtbo`** (предусловие правки `:135`).
- **P1-udev:** `ls -l /etc/udev/rules.d/90-u1u2-uart.rules` (ожид. нет файла).
- **P2-smoke-wg:** `ip -br addr show wg0` (ожид. 10.8.0.x, НЕ 10.10.0.x).
- **P3 #7:** `ls /dev/input/`, `evtest` → `DEVICE` в `joystick.env` указывает на реальный
  evdev-узел (он же — evtest-гейт калибровки `channels.default.toml`).
- **Рантайм (25c §4):** `lsusb`; `v4l2-ctl --list-formats` (Arkmicro 640×480 MJPG);
  `ip -br link` (ожид. `enP3p49s0`); `systemctl is-active` сервисов; `udp_drop`, RSSI/LQ,
  clock-skew (~52 мин на u2).

---

## Приложение — границы знания

- **Код не исполнялся** — ни `verify.ps1`/`ruff`/`mypy`/`pytest`/`shellcheck`, ни рантайм.
  Все вердикты — статическое ревью.
- **Security не аудирован:** открытый UDP без фильтрации source в `crsf_bridge`/
  `joystick_to_crsf`; P3-ufw-asymmetry латентен. Отдельная тема.
- **Полный список tracked-файлов** сырьём не верифицирован целиком (WG-файл один —
  `docs/wg-template.conf` — подтверждён `[RAW-grep]`).
- **`docs/wiring-opi5max.md`** в этой сессии не читан: по `[MEM]` TX/RX-таблица помечена
  невалидной (трек D), но баннер HANDOFF.md шлёт к нему как к истине — **сверить при
  аудите того дока**.
- **Живая Pi не затрагивалась** — все `[PI-TODO]` открыты.
