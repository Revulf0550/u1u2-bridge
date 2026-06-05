# HANDOFF → Этап C · 2d ВЫПОЛНЕН (Режим №2 кодифицирован в install.sh + проверен живьём) · перед Этапом D · u1u2-bridge · 2026-06-05

> Точка входа в новый чат. **2d ВЫПОЛНЕН:** install.sh воспроизводит Режим №2 (`TRANSPORT=direct`), запускается оффлайн (`SKIP_APT`), running-конфиг = кодифицированному, вариант B (видео-peer через `EnvironmentFile`) проверен живьём (картинка + управление подтверждены пользователем).
> **Следующее:** Этап D (переключатель Режим №1↔№2 одной командой) · `JITTER_LATENCY` под радио · опц. ребут-тест на `direct`.
> §0: любая работа — после сверки с фактом (репо + железо), не по памяти.
> Этот файл СУПЕРСЕДИТ `HANDOFF-2026-06-05-stageC-mode2-cutover-DONE.md`.

---

## ⚠️ ДОСТУП (ИСПРАВЛЕНО — старый хэндофф врал про WG)

**ARDOR ходит в интернет / к ассистенту / в Claude Code ЧЕРЕЗ WireGuard.** Поэтому WG-состояния ВЗАИМОИСКЛЮЧАЮЩИЕ:
- **WG ВКЛЮЧЁН** → интернет + ассистент + Claude Code есть, **НО** kill-switch (`AllowedIPs 0.0.0.0/0`) режет мост `192.168.1.x` → до Pi не достучаться.
- **WG ВЫКЛЮЧЕН** → мост `192.168.1.x` доступен (SSH к Pi), **НО** нет интернета → Claude Code не работает.

(Старый хэндофф стр.15 ошибочно утверждал, что интернет/ассистент не зависят от WG — **НЕВЕРНО**.)

**Рабочий паттерн для моста = БАТЧ:** WG-off → команды в обычном PowerShell с `Start-Transcript` → WG-on → прислать транскрипт ассистенту. **Claude Code (нужен интернет) — только для репо/git при WG-on.**

SSH к Pi: `ssh -i ~/.ssh/u1u2 ubuntu@192.168.1.20` (u1) / `ubuntu@192.168.1.10` (u2), sudo NOPASSWD.

---

## ШАГ 0 — §0-сверка (БАТЧ, PowerShell, WG-OFF; ТОЛЬКО ЧТЕНИЕ)

> WG выключить → выполнить в обычном PowerShell → WG включить → прислать файл. Claude Code тут не годится (нет инета при WG-off).

```powershell
Start-Transcript -Path $HOME\Desktop\s0-audit.txt -Force
$REPO="$HOME\Documents\Projects\u1u2-bridge"; $K="$HOME\.ssh\u1u2"
git -C $REPO --no-pager log --oneline -5; git -C $REPO status -sb
ping -n 4 192.168.1.20
ping -n 4 192.168.1.10
ssh -i $K -o ConnectTimeout=8 ubuntu@192.168.1.20 'hostname; ip -4 -br addr; for u in crsf-bridge@p1 video-rx wg-quick@wg0; do echo ==$u==; systemctl is-active $u; done; echo --crsf-send--; journalctl -u crsf-bridge@p1 -n 2 --no-pager'
ssh -i $K -o ConnectTimeout=8 ubuntu@192.168.1.10 'hostname; ip -4 -br addr; for u in crsf-bridge@elrs video-tx wg-quick@wg0; do echo ==$u==; systemctl is-active $u; done; echo --crsf-recv--; journalctl -u crsf-bridge@elrs -n 2 --no-pager'
Stop-Transcript
```

**Ожидаю (факт на конец 2026-06-05):**
- git HEAD = коммит ЭТОГО хэндоффа; `main...origin = 0/0`; незакоммичено только `M pyproject.toml` (чужое) + старые untracked (PNG, прошлые хэндоффы).
- ping `.20` 0% (<1 мс, провод через свитч), `.10` 0% (~2 мс, радио; первый пакет может быть всплеском).
- u1 (`u1-pi`): `enP3p49s0 192.168.1.20/24`, `wg0 10.8.0.6` (active без handshake — норма Режима №2); `crsf-bridge@p1` + `video-rx` + `wg-quick@wg0` = `active`.
- u2 (`u2-pi`): `enP3p49s0 192.168.1.10/24`, `wg0 10.8.0.7`; `crsf-bridge@elrs` + `video-tx` + `wg-quick@wg0` = `active`.
- CRSF: `uart->udp` (u1) ≈ `udp->uart` (u2), `udp_drop=0` на обоих (симметрия = сквозной CRSF через радио). **Темп зависит от пакетрейта Boxer** (видели ~19 KB/s и ~10.7 KB/s в разных замерах) — важно, что симметрично и `drop=0`, а не абсолютное число.

---

## ⚠️ ТЕРМИНОЛОГИЯ
- **Режим №2 / direct / радио** = ТЕКУЩИЙ боевой. Pi на CPE710 по воздуху, сеть `192.168.1.x`, без WG в тракте. RTT ~2 мс.
- **Режим №1 / tunnel** = WG `10.8.0.x` через интернет (RTT ~180 мс) — известно-рабочая база, точка отката. Требует Pi в домашнем свитче (нужен интернет).

---

## СОСТОЯНИЕ (факт, сверено живьём 2026-06-05)

**2d ВЫПОЛНЕН.** Что сделано и проверено:

- **Код (запушено, `main...origin=0/0`):**
  - `2482b7f` — `feat(install): 2d — codify Mode 2 (direct): video.env peer + UFW allows`
  - `8f139fc` — `feat(install): add SKIP_APT for offline/field redeploy`
- **install.sh в `TRANSPORT=direct` теперь воспроизводит Режим №2:**
  - CRSF-peer: u1 `PEER=192.168.1.10:14552`, u2 `PEER=192.168.1.20:14552`.
  - netplan-статику `.20/.10` (но при редеплое использовать `SKIP_NETPLAN=1` — см. НЕ ДЕЛАЙ).
  - **§7b** — на u2 пишет `/etc/u1u2-bridge/video.env` с `PEER_HOST=192.168.1.20`; в `tunnel` файл НЕ пишет (видео берёт fallback `10.8.0.6` из `video_tx.sh`). `video-tx.service` получил `EnvironmentFile=-/etc/u1u2-bridge/video.env`.
  - **§7c** — аддитивные `ufw allow` ТОЛЬКО в `direct` (u2: `14552/udp from 192.168.1.20` + `22/tcp from 192.168.1.0/24`; u1: `5600/udp from 192.168.1.10`). Без `ufw enable`, без смены default-policy, под `command -v ufw`.
  - **`SKIP_APT=1`** — пропуск `apt` для оффлайн-запуска (Режим №2 / поле).
  - Ветка `tunnel` байт-цела: CRSF-env совпадает с `docs/baseline/`.
- **Редеплой выполнен оффлайн и неразрушающе:** `git archive HEAD` → scp → `~/u1u2-deploy` → `sudo TRANSPORT=direct SKIP_NETPLAN=1 SKIP_APT=1 SKIP_VIDEO=1 MODE=bench ./install.sh u1|u2`. Сервисы НЕ моргнули (в install.sh нет `restart`).
- **Running-конфиг приведён к кодифицированному:** на u2 убран `override.conf`, рестартнуты `crsf-bridge@elrs` + `video-tx`. **Вариант B доказан вживую:** запущенный `video-tx` шлёт на `host=192.168.1.20`, источник — `video.env` (override удалён). CRSF после рестарта симметричный, `udp_drop=0`.
- **Подтверждено пользователем live:** картинка есть, управление есть.

**Текущая боевая конфигурация (Режим №2, hardware-proven):**
- **CRSF:** Boxer → u1 `/dev/ttyUSB0` (CH340) → `crsf-bridge@p1` → UDP `192.168.1.10:14552` → радио → `crsf-bridge@elrs` → u2 `/dev/ttyS7` (UART7) → ELRS-TX → RF → дрон. `crsf-elrs.env` PEER теперь `192.168.1.20` (telemetry-цель, обратный поток пока 0).
- **Видео:** u2 `video_tx.sh` (грабер 640×480 MJPG, `mpph264enc cbr bps=2500000 gop=15 profile=66`, `PEER_HOST` из `video.env`=`192.168.1.20`) → UDP `192.168.1.20:5600` → радио → u1 `video_rx.sh` (`cage`+`waylandsink`, `JITTER_LATENCY=50`).
- env-файлы (факт): u1 `crsf-p1.env` PEER=`192.168.1.10:14552`; u2 `crsf-elrs.env` PEER=`192.168.1.20:14552`, `video.env` PEER_HOST=`192.168.1.20`.

---

## ❌ ПЛАН ДАЛЬШЕ (приоритет)

1. **Этап D — переключатель Режим №1↔№2 одной командой/флагом.** Теперь проще: видео-peer параметризован (вариант B), есть `SKIP_APT`.
   **⚠️ Дыра, которую Этап D ОБЯЗАН закрыть:** в `tunnel` install.sh НЕ пишет `video.env` → видео берёт fallback `10.8.0.6`. При переключении `direct→tunnel` старый `video.env=192.168.1.20` останется на диске и уведёт видео не туда. Switcher в `tunnel` должен ЛИБО писать `video.env` с WG-адресом u1 (`10.8.0.6`), ЛИБО удалять `video.env`.
2. **`JITTER_LATENCY=50`** тюнилось под WG 180 мс. Под радио ~2 мс можно опустить (порог дропов был ~10 мс). Перемерить на ЖИВОМ видео (с движением/дроном — «живой контент», не факт наличия RTP).
3. **(Опц.) Ребут-тест на `direct`** (как B3 был для tunnel) — power-cycle survival в Режиме №2. **Риск:** у u2 нет монитора — если не загрузится, восстановление сложное (вернуть в домашний свитч / подключить монитор). Делать осознанно.
4. **Обратный CRSF-peer (telemetry)** — backlog. Когда появится обратный поток, проверить `crsf-elrs.env` PEER=`192.168.1.20` (уже стоит).
5. **Trim CLAUDE.md** (был ~59k, цель <40k).
6. **Cleanup на Pi:** удалить `~/deploy.tar` и `~/u1u2-deploy` на обеих Pi (мусор от редеплоя; рабочая система их не использует).

---

## 🔙 ОТКАТ В РЕЖИМ №1 (WireGuard)

1. **Физика:** обе Pi → обратно в **домашний свитч** (WG требует интернета, которого на мосту нет).
2. **Софт (предпочтительно через install.sh, а не ручной sed):**
   - редеплой `TRANSPORT=tunnel` (авто-`SKIP_NETPLAN`) на обеих Pi → CRSF-env вернётся к `10.8.0.x` (== `docs/baseline/`).
   - ⚠️ Видео: в tunnel `video.env` НЕ пишется → на u2 удалить `/etc/u1u2-bridge/video.env`, чтобы `video_tx.sh` взял fallback `10.8.0.6`. (Иначе видео останется на `.20`.) Затем `daemon-reload` + рестарт `video-tx` (дрон выкл).
   - рестарт `crsf-bridge@p1`/`@elrs` чтобы подхватить tunnel-peer (дрон выкл) или ребут.
3. **ARDOR:** включить WireGuard `NSU-pc` → Pi видны по `10.8.0.6/.7`.
4. UFW-direct-правила аддитивны — Режим №1 не ломают, удалять не нужно.

---

## 📦 ДЕПЛОЙ (оффлайн, Режим №2) — проверенный метод

- **Клоны `~/u1u2-bridge` на Pi устарели (`a8573d6`) и НЕ pull-ятся** (нет интернета на мосту). **НЕ запускать клонский install.sh** (старый код + apt-облом).
- **Текущий деплой:** на ARDOR `git -C <repo> archive --format=tar -o deploy.tar HEAD` → `scp` на Pi → распаковать в свежий `~/u1u2-deploy` → `cd ~/u1u2-deploy && sudo TRANSPORT=direct SKIP_NETPLAN=1 SKIP_APT=1 [SKIP_VIDEO=1] MODE=bench ./install.sh u1|u2`.
- **install.sh без `restart`** → после редеплоя конфиг лежит на диске, но running-сервисы крутят старый до **ручного `systemctl restart`** (моргнёт CRSF → дрон ВЫКЛ) или ребута.
- `MODE` по умолчанию = `bench` (= текущий: управление с Boxer → `crsf-bridge@p1`). `MODE=drone` = USB-джойстик → `joystick-to-crsf` (не наш случай).

---

## УРОКИ СЕССИИ (новые — внесены в CLAUDE.md этим коммитом)
1. WG on/off — взаимоисключающие режимы (мост vs интернет/ассистент) → батч-режим для моста. (Дополняет урок про «Общий сбой» от kill-switch, уже бывший в CLAUDE.md.)
2. install.sh падал оффлайн на `apt` → добавлен `SKIP_APT` (Режим №2/поле = оффлайн).
3. install.sh не рестартит сервисы → редеплой неразрушающий, но конфиг к running не применяет (нужен restart/ребут).
4. Оффлайн-деплой = `git archive HEAD` + scp (клон на Pi устарел и не pull-ится).

(Уроки «RTP ≠ живой контент» и «CBR маскирует no-signal» уже в CLAUDE.md от 429062f — НЕ дублируем.)

---

## ❗ НЕ ДЕЛАЙ
- **НЕ запускать install.sh без `SKIP_NETPLAN=1` в `direct`** — иначе перепишет netplan-статику → риск lockout.
- **НЕ запускать install.sh без `SKIP_APT=1` на мосту** — `apt` упадёт без интернета, скрипт оборвётся.
- **WG на ARDOR держать ВЫКЛЮЧЕННЫМ при работе с мостом** (kill-switch). Включать только для Режима №1 / git-работы.
- **НЕ запускать клонский (`a8573d6`) install.sh на Pi** — деплоить только текущий HEAD через `git archive`.
- НЕ `kmssink` (VOP2 timeout) — только `cage`+`waylandsink`; НЕ убирать `videoconvert` (чёрный на NV12). Грабер — 640×480 MJPG, без `io-mode=4`.
- **ДРОН включать / рестартить CRSF при армед — ТОЛЬКО спросив пользователя ЯВНО.** Рестарт `@elrs`/`@p1` рвёт управление на ~2 с.
- `pyproject.toml` — чужое, не трогать. `docs/baseline/` — снимок, не трогать.
- В Claude Code Bash-тулзе НЕ `cd ~/...` (резолвится в Windows-домашку). Длинные файлы — через файл-артефакт, не вставкой в терминал.

---

## ТОПОЛОГИЯ / ДОСТУП
- u1 = RX + монитор, `192.168.1.20`; u2 = TX, `192.168.1.10`. Ключ `~/.ssh/u1u2`, sudo NOPASSWD. SSH только при WG-off.
- ARDOR: встроенный `Ethernet` `192.168.31.150` (дом, интернет — но идёт через WG); USB-NIC `Ethernet 3` `192.168.1.50` (мост, без gateway). WG `NSU-pc` `10.8.0.5` — выключать для моста.
- CPE-AP `192.168.1.2`, CPE-Client `192.168.1.3`; Pharos UI с отдельного ПК `192.168.0.254`.
- Pi на ПРОТИВОПОЛОЖНЫХ концах радио (иначе трафик уйдёт по проводу).

## ПРАВИЛА РАБОТЫ
- §0 аудит/план → diff → **НЕ коммить/менять без ОК**, поэтапно.
- Дозируй: один логический блок, жди подтверждения.
- В начале шага — карта подключений (где Pi, WG on/off, что трогаем). Помечай «На u1:» / «На u2:» / «В PowerShell:» / «В Claude Code:».
- Claude Code — для локальных команд/git при WG-on; батч-PowerShell — для моста при WG-off. Переключаться не молча.
- Монитор на u1. Язык — русский.
