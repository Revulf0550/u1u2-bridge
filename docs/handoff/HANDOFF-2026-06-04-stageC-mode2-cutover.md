# HANDOFF → Этап C · переход на радио-мост (Режим №2) · u1u2-bridge · 2026-06-04

> Точка входа в новый чат. **Задача дня: подключиться к Wi-Fi мосту CPE710 (Режим №2) — с чистого листа.**
> База: **Режим №1 (туннель) — известно-рабочий, e2e подтверждён** (CRSF-управление и видео-конвейер живые). Железо совпадает с репо.
> §0: любая работа — после сверки с фактом (репо + железо), не по памяти.
> Этот файл СУПЕРСЕДИТ `HANDOFF-2026-06-04-stageC-day2.md` и `…-cutover-prep.md` — бери этот.

## СНАЧАЛА ПРОЧИТАЙ
- `docs/PLAN.md` — Этап A ✅, B ✅. **Этап C — текущий.**
- `CLAUDE.md` — Architecture + Lessons. `docs/baseline/` — НЕ редактировать.
- Памятка адресов/подключений: `u1u2-bridge-cheatsheet.html`.

## ШАГ 0 — §0-сверка (первым делом, через Claude Code, только чтение)
```
§0-аудит u1u2-bridge. Ничего не менять, не коммитить.
cd ~/u1u2-bridge && git --no-pager log --oneline -5 && git status -sb
ssh -i ~/.ssh/u1u2 ubuntu@10.8.0.6 'for u in crsf-bridge@p1 video-rx wg-quick@wg0; do echo "==$u=="; systemctl is-active $u; done'
ssh -i ~/.ssh/u1u2 ubuntu@10.8.0.7 'for u in crsf-bridge@elrs video-tx wg-quick@wg0; do echo "==$u=="; systemctl is-active $u; done'
grep -nE "Этап|✅|done" docs/PLAN.md | head
Верни сырой вывод.
```
Ожидаю: git `6b296bd`, `main…origin = 0/0`, все юниты `active`, Этап A/B = done, C — текущий.

## ⚠️ ТЕРМИНОЛОГИЯ (не путать)
- **радио-мост / CPE-линк** = беспроводной CPE710 (по воздуху).
- **crsf_bridge** = софт UART↔UDP на Pi. **сеть `192.168.1.x`** = адресация Режима №2 (≠ «по радио»: трафик может идти и по проводу/свитчу, если Pi не на разных концах радио).
- **ФАКТ ДО CUTOVER: транспорт = Режим №1 (туннель WG `10.8.0.x` через интернет).** CPE-радио в путь Pi НЕ вставлено. Радио проверено отдельно — пропускает IP (ping `.2↔.3` по воздуху).

## СОСТОЯНИЕ (факт, §0-сверено)
- **git = `6b296bd`**, main=origin (0/0). Незакоммичено только известное: `pyproject.toml` (M, чужое), untracked `docs/2026-05-24_*.png`, `handoff-2026-05-25/`.
- **Железо = Режим №1, совпадает с репо-дефолтом** (`TRANSPORT=tunnel`), кроме безвредной netplan-статики и заданных CPE-адресов.
- 4 юнита `active`: u1 `@p1`+`video-rx`+`wg`; u2 `@elrs`+`video-tx`+`wg`.
- **Mode-1 e2e подтверждён рабочим:** CRSF-управление (Crossfire) проходит насквозь Boxer→дрон; видео-конвейер несёт живые кадры на монитор u1.
- CRSF env: u1 `PEER=10.8.0.7:14552`, u2 `PEER=10.8.0.6:14552`, `LISTEN=0.0.0.0:14552`.
- Видео: дефолт скрипта `PEER_HOST=10.8.0.6` (override снят).
- netplan-статика (вторым адресом, +DHCP сохранён): u1 `192.168.1.20/24`, u2 `192.168.1.10/24` — на обеих, для Режима №2. **Не в репо** (живёт в `/etc/netplan/99-u1u2-bridge.yaml`).
- CPE: AP `192.168.1.2`, Client `192.168.1.3` (заданы со 2-го ПК; радио проверено — пропускает IP).

## ✅ ЗНАЯ-ГОДНАЯ РАБОЧАЯ СХЕМА (Режим №1, туннель) — НЕ ПОТЕРЯТЬ
*(verbatim из репо; истина — репо/скрипты)*

**Видео TX (u2)** — `video-tx.service` → `u2/video_tx.sh`:
```
v4l2src device=/dev/video0 ! image/jpeg,width=640,height=480,framerate=30/1 ! jpegdec
  ! videoconvert ! video/x-raw,format=NV12
  ! mpph264enc rc-mode=cbr bps=2500000 bps-max=3000000 gop=15 profile=66 level=40 header-mode=1
  ! h264parse config-interval=1 ! rtph264pay pt=96 mtu=1200 config-interval=1
  ! udpsink host=10.8.0.6 port=5600 sync=false async=false
```
Грабер: **Arkmicro `18ec:5555`, ТОЛЬКО 640×480 MJPG@30** (без `io-mode=4`). Env-дефолты: `PEER_HOST=10.8.0.6`, `PEER_PORT=5600`.

**Видео RX (u1)** — `video-rx.service` → `u1/video_rx.sh` (под `cage` от root):
```
cage -- gst-launch-1.0 -v
  udpsrc port=5600 caps="application/x-rtp,encoding-name=H264,payload=96,clock-rate=90000" buffer-size=2097152
  ! rtpjitterbuffer latency=50 drop-on-latency=false do-lost=true
  ! rtph264depay ! h264parse ! mppvideodec ! videoconvert ! waylandsink sync=false
```
`JITTER_LATENCY=50` (link-specific — **под радио перетюнить**). `/run/user/0` (0700 root) пересоздаётся tmpfiles ДО старта `video-rx`.

**CRSF (управление):** Boxer → u1 `/dev/ttyUSB0` (CH340 `1a86:7523`) → `crsf-bridge@p1` → UDP `:14552` → wg → `crsf-bridge@elrs` → u2 `/dev/ttyS7` (аппаратный UART7) → ELRS-TX → RF → дрон. Порт `14552`. `TRANSPORT=tunnel` → `PEER=10.8.0.x`.

**Транспорт-переключатель:** `install.sh TRANSPORT=tunnel|direct` (покрывает только CRSF-peer). **Видео НЕ покрыто** — peer в `video_tx.sh` (override через systemd). Это пробел → закрывает **Этап D**.

## ДАЛЬШЕ — ПЛАН ДНЯ

**1. Быстро подтвердить, что Режим №1 жив (база для сравнения):**
   - §0 (юниты `active`); по желанию — живой e2e: видео на мониторе u1 + CRSF forward >0 (`journalctl -u crsf-bridge@p1` → `uart->udp`, `@elrs` → `udp->uart`) + реакция дрона. Дрон — **только с явного ОК**.

**2. Перевести на радио-мост (Режим №2) — задача дня:**
   - **2a.** Поднять Режим №2-адресацию (процедура ниже; netplan-статика `.20/.10` уже стоит).
   - **2b. Cutover (провода):** Pi-u1 → порт `LAN` PoE-адаптера **CPE-AP**; Pi-u2 → порт `LAN` PoE-адаптера **CPE-Client**; CPE-коробки — только в порт `POE` своих адаптеров. **Pi должны быть на ПРОТИВОПОЛОЖНЫХ концах радио** — иначе трафик уйдёт по проводу, и радио не проверишь. **ARDOR остаётся в домашнем свитче** (сохраняет интернет/ассистента; теряет SSH к Pi — для проверки хватит монитора u1, либо ARDOR dual-home: Wi-Fi=интернет + Ethernet=мост для SSH).
   - **2c. Проверка по радио:** видео на мониторе u1 (⚠️ при выкл. дроне синий no-signal и фриз НЕОТЛИЧИМЫ → проверять с дроном/движением, либо считать RTP-пакеты / `ping .20↔.10` по радио с бенча). CRSF — реакция дрона. Перетюнить `JITTER_LATENCY` под радио (на туннеле было 50; радио быстрее — можно ниже).
   - **2d. Финализация в репо:** `sudo TRANSPORT=direct SKIP_NETPLAN=1 ./install.sh u1|u2` (CRSF) + **Этап D** (видео-peer в Режим №2) + зафиксировать CPE `.2/.3` и netplan-статику в доках + коммит. (Или оставить документировано, без коммита — по ситуации.)

### Процедура Режима №2 (документировано — для шага 2a; временно, НЕ в репо):
```
u1: sudo sed -i 's|^PEER=.*|PEER=192.168.1.10:14552|' /etc/u1u2-bridge/crsf-p1.env
u2: sudo sed -i 's|^PEER=.*|PEER=192.168.1.20:14552|' /etc/u1u2-bridge/crsf-elrs.env
u2 видео: /etc/systemd/system/video-tx.service.d/override.conf  →  [Service]\nEnvironment=PEER_HOST=192.168.1.20
затем: sudo systemctl daemon-reload && sudo systemctl restart crsf-bridge@p1 (u1) / crsf-bridge@elrs video-tx (u2)
Откат в Mode-1: PEER→10.8.0.x, удалить override, daemon-reload + restart.
```

## BACKLOG (после поля)
- Телеметрия на Boxer (back-channel = 0) — НЕ код, отдельная задача.
- B1-latency → полевой замер glass-to-glass на реальной дистанции (Этап C).
- Trim `CLAUDE.md` (59k>40k).

## ❗ НЕ ДЕЛАЙ
- **НЕ редеплоить `install.sh` без `TRANSPORT=… SKIP_NETPLAN=1`** — иначе CRSF env вернётся к `10.8.0.x` И install.sh напишет свой netplan-статик → конфликт с нашим `99-`файлом.
- **НЕ добавлять secondary-IP на Ethernet ARDOR при активном на нём интернете** — рвёт интернет (проверено). На cutover: интернет ARDOR по **Wi-Fi**, Ethernet — отдельно на мост (без gateway).
- **Pi на cutover — на разные концы радио**, иначе тест уйдёт по проводу (синий/фриз неотличимы без движения дрона).
- НЕ `kmssink` (VOP2 timeout) — только `cage`+`waylandsink`. НЕ убирать `videoconvert` перед `waylandsink` (чёрный на NV12). Грабер — только 640×480 MJPG, без `io-mode=4`.
- НЕ доверять старому `/opt` без редеплоя. `pyproject.toml` — чужое. `docs/baseline/` — не трогать.
- **ДРОН включать — ТОЛЬКО спросив пользователя ЯВНО.**
- git `-m`: трейлеры вторым `-m`. Длинные файлы — через `present_files`, не вставкой в терминал.
- `cd ~/...` в Bash-тулзе Claude Code резолвится в Windows-домашку — рабочая папка и так корень репо, `cd` не нужен.

## ТОПОЛОГИЯ / ДОСТУП
- u2=TX `ubuntu@10.8.0.7`, u1=RX+монитор `ubuntu@10.8.0.6`, ключ `~/.ssh/u1u2`, sudo NOPASSWD.
- До cutover SSH жив: WG `10.8.0.x` поверх домашнего свитча (Pi на `192.168.31.72`(u1)/`192.168.31.100`(u2) DHCP, iface `enP3p49s0`). **После cutover Pi теряют WG → SSH к Pi только с бенча** (ARDOR dual-home, либо монитор на Pi).
- ARDOR: Ethernet `192.168.31.150` (в свитч), WG-адаптер `NSU-pc`=`10.8.0.5`. `.50` НЕ нужен.
- Mode-2 адресация: u1 `192.168.1.20`, u2 `192.168.1.10`, CPE-AP `192.168.1.2`, CPE-Client `192.168.1.3`.
- CPE настраиваются с отдельного ПК (Pharos `192.168.0.254`; Claude Code там нет).
- Деплой: `sudo TRANSPORT={tunnel|direct} [SKIP_NETPLAN=1] [SKIP_VIDEO=1] [MODE=?] ./install.sh u1|u2` из `~/u1u2-bridge`. `MODE={bench|drone}` — **уточнить дефолт перед редеплоем**.

## ПРАВИЛА РАБОТЫ
- §0 аудит/план → diff → **НЕ коммить/менять без ОК**, поэтапно.
- Дозируй: один логический блок, жди подтверждения.
- Помечай «На u1:» / «На u2:» / «В PowerShell:» / «В Claude Code:» / «В Pharos UI:».
- Claude Code — для локальных команд/SSH/git; переключаться не молча.
- Монитор на u1. Русский.
