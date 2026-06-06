# HANDOFF → Этап D ВЫПОЛНЕН (переключатель режимов готов и live-доказан) · перед ПОЛЕВЫМИ ТЕСТАМИ С ДРОНОМ · u1u2-bridge · 2026-06-05

> Точка входа в новый чат. **Этап D ВЫПОЛНЕН:** `install.sh` — корректный переключатель транспорта (закрыта дыра `video.env`, §7b пишет видео-peer в обоих режимах), `switch-mode.ps1` — переключение Режим №1↔№2 одной командой, само-тест switcher'а прошёл live и неразрушающе.
> **Следующее (для этого чата): ПОЛЕВЫЕ ТЕСТЫ С ДРОНОМ** — (1) Режим №2 + дрон, (2) `switch-mode.ps1 tunnel` → Режим №1 + дрон, (3) power-cycle обеих Pi (что грузится / какой режим по умолчанию). Затем `JITTER_LATENCY` под радио.
> §0: любая работа — после сверки с фактом (репо + железо), не по памяти.
> Этот файл СУПЕРСЕДИТ `HANDOFF-2026-06-05-stageC-2d-done.md`.

---

## ⚠️ ДОСТУП (WG-состояния ВЗАИМОИСКЛЮЧАЮЩИЕ)

ARDOR ходит в интернет / к ассистенту / в Claude Code **через WireGuard**:
- **WG ВКЛЮЧЁН** → интернет + ассистент + Claude Code есть, **НО** kill-switch (`AllowedIPs 0.0.0.0/0`) режет мост `192.168.1.x` → до Pi на мосту не достучаться.
- **WG ВЫКЛЮЧЕН** → мост `192.168.1.x` доступен (SSH к Pi), **НО** нет интернета → Claude Code не работает.

**Рабочий паттерн для моста = БАТЧ:** WG-off → команды в обычном PowerShell с `Start-Transcript` → WG-on → прислать транскрипт ассистенту. **Claude Code (нужен интернет) — только для репо/git при WG-on.**

SSH к Pi: `ssh -i ~/.ssh/u1u2 ubuntu@192.168.1.20` (u1) / `ubuntu@192.168.1.10` (u2), sudo NOPASSWD. (В Режиме №1 / дома — Pi по `10.8.0.6` / `10.8.0.7` при WG-on.)

---

## ШАГ 0 — §0-сверка (БАТЧ, PowerShell, WG-OFF; ТОЛЬКО ЧТЕНИЕ)

> WG выключить → выполнить в обычном PowerShell → WG включить → прислать файл. (Актуально, если Pi сейчас в Режиме №2 на мосту. Если уже перешли в Режим №1 — править адреса на `10.8.0.6/.7` и запускать при WG-on.)

```powershell
Start-Transcript -Path $HOME\Desktop\s0-audit.txt -Force
$REPO="$HOME\Documents\Projects\u1u2-bridge"; $K="$HOME\.ssh\u1u2"
git -C $REPO --no-pager log --oneline -5; git -C $REPO status -sb
ping -n 4 192.168.1.20
ping -n 4 192.168.1.10
ssh -i $K -o ConnectTimeout=8 ubuntu@192.168.1.20 'hostname; ip -4 -br addr; for u in crsf-bridge@p1 video-rx wg-quick@wg0; do echo ==$u==; systemctl is-active $u; done; echo --crsf--; journalctl -u crsf-bridge@p1 -n 2 --no-pager; echo --env--; cat /etc/u1u2-bridge/crsf-p1.env'
ssh -i $K -o ConnectTimeout=8 ubuntu@192.168.1.10 'hostname; ip -4 -br addr; for u in crsf-bridge@elrs video-tx wg-quick@wg0; do echo ==$u==; systemctl is-active $u; done; echo --crsf--; journalctl -u crsf-bridge@elrs -n 2 --no-pager; echo --env--; cat /etc/u1u2-bridge/crsf-elrs.env /etc/u1u2-bridge/video.env'
Stop-Transcript
```

**Ожидаю (факт на конец 2026-06-05):**
- git HEAD = `51bfa84` (`docs(claude-md): уроки Этапа D`); ниже `7a9ecec` (switch-mode.ps1), `783ed34` (фикс video.env). `main...origin`=0/0. Незакоммичено: `M pyproject.toml` (чужое) + старые untracked (PNG, прошлые хэндоффы, `handoff-2026-05-25/`).
- ping `.20` 0% (<1 мс), `.10` 0% (~2 мс, радио).
- u1 (`u1-pi`): `enP3p49s0 192.168.1.20/24`, `wg0 10.8.0.6`; `crsf-bridge@p1`+`video-rx`+`wg-quick@wg0`=`active`. `crsf-p1.env` PEER=`192.168.1.10:14552`.
- u2 (`u2-pi`): `enP3p49s0 192.168.1.10/24`, `wg0 10.8.0.7`; `crsf-bridge@elrs`+`video-tx`+`wg-quick@wg0`=`active`. `crsf-elrs.env` PEER=`192.168.1.20:14552`, `video.env` PEER_HOST=`192.168.1.20`.
- CRSF симметричный (`uart->udp` на u1 ≈ `udp->uart` на u2), `udp_drop=0`. Темп зависит от пакетрейта Boxer (видели ~26–31 KB/s в разных замерах) — важна симметрия и `drop=0`, не абсолют.

---

## ⚠️ ТЕРМИНОЛОГИЯ
- **Режим №2 / direct / радио** = ТЕКУЩИЙ боевой. Pi на CPE710 по воздуху, сеть `192.168.1.x`, без WG в тракте. RTT ~2 мс.
- **Режим №1 / tunnel** = WG `10.8.0.x` через интернет (RTT ~180 мс) — известно-рабочая база, точка отката. Требует Pi в домашнем свитче (нужен интернет).

---

## СОСТОЯНИЕ (факт, сверено live 2026-06-05 ~13:30 через само-тест switcher'а)

**Этап D ВЫПОЛНЕН.** Что сделано и проверено:

- **Код (запушено, `main...origin`=0/0):**
  - `783ed34` — `fix(install): video.env в обоих транспортах — закрыта дыра переключателя`. §7b теперь: `if [[ "$ROLE" == "u2" ]]` (оба режима) → `cat > video.env` c `PEER_HOST=$CRSF_PEER` (= адрес u1 в активном режиме: direct→`192.168.1.20`, tunnel→`10.8.0.6`). Убрана зависимость от неявного fallback в `video_tx.sh` (он остался аварийным).
  - `7a9ecec` — `feat(switch): switch-mode.ps1` (в корне репо).
  - `51bfa84` — `docs(claude-md)`: 3 урока (video.env, netplan location-adaptive, MOTW).
- **`switch-mode.ps1` (корень репо) — само-тест `direct -NoRestart` прошёл live:** preflight-ping обеих Pi → `git archive HEAD` (850 KB) → `scp` → `install.sh TRANSPORT=direct SKIP_APT=1 SKIP_NETPLAN=1 MODE=bench` на обе Pi. В логе: `video.env: PEER_HOST=192.168.1.20 (direct, → u1)` (= новый §7b), ufw идемпотентен (`Skipping adding existing rule`), `-NoRestart` сервисы не дёргал → 4 сервиса `active`, CRSF симметричный ~31 KB/s `drop=0`. **Неразрушающесть подтверждена.**
- **netplan обеих Pi (сверено):** `50-cloud-init.yaml` (`zz-all-en`/`zz-all-eth`, `dhcp4:true`) + `99-u1u2-bridge.yaml` (статика `192.168.1.x` на `zz-all-en`). Мёрджатся → интерфейс имеет И статику, И DHCP → **location-adaptive** (мост = статика; дом = DHCP даёт интернет/маршрут для WG). Поэтому switcher netplan НЕ трогает.

**Текущая боевая конфигурация (Режим №2, hardware-proven, без изменений с пред. хэндоффа):**
- **CRSF:** Boxer → u1 `/dev/ttyUSB0` (CH340) → `crsf-bridge@p1` → UDP `192.168.1.10:14552` → радио → `crsf-bridge@elrs` → u2 `/dev/ttyS7` (UART7) → ELRS-TX → RF → дрон. Обратный поток (telemetry) пока 0.
- **Видео:** u2 `video_tx.sh` (грабер 640×480 MJPG, `mpph264enc cbr bps=2500000 gop=15 profile=66`, `PEER_HOST` из `video.env`=`192.168.1.20`) → UDP `192.168.1.20:5600` → радио → u1 `video_rx.sh` (`cage`+`waylandsink`, `JITTER_LATENCY=50`).

---

## ❌ ПЛАН ДАЛЬШЕ (приоритет) — ПОЛЕВЫЕ ТЕСТЫ С ДРОНОМ

> ⚠️ Везде, где трогается дрон / рестартится CRSF при armed — **только спросив пользователя ЯВНО** (рестарт рвёт управление ~2 с).

1. **Тест Режима №2 с дроном (на мосту — текущее место).** Дрон подключён → проверить: управление (Boxer → дрон, бинд, ARM) И видео (ЖИВОЕ движение на мониторе u1, не просто наличие RTP-потока — см. урок «CBR маскирует no-signal»).

2. **Переключение в Режим №1 одной командой + тест с дроном.**
   - Физика: обе Pi → **домашний свитч** (WG требует интернета).
   - WG на ARDOR: **ВКЛЮЧИТЬ** (Pi станут доступны по `10.8.0.6/.7`).
   - `.\switch-mode.ps1 tunnel` (обычный PowerShell) → preflight-ping `10.8.0.6/.7` → deploy `TRANSPORT=tunnel` → подтвердить рестарт `[y/N]` (**дрон off на момент рестарта**).
   - Дрон → проверить управление + видео в tunnel (RTT ~180 мс, `JITTER_LATENCY=50` тут уместен).

3. **Power-cycle тест (выкл/вкл питание обеих Pi).** Проверить: что поднялось, всё ли работает, **какой режим грузится по умолчанию.**
   - Ожидание: режим = **последний задеплоенный** (зашит в env-файлах на диске; авто-детекта нет). После шага 2 это будет `tunnel`. `wg-quick@wg0` enabled → `wg0` поднимется всегда.
   - ⚠️ **u2 безмониторная** — если не загрузится, восстановление сложное (вернуть монитор / в домашний свитч). Делать осознанно.

4. **`JITTER_LATENCY` под радио** (после возврата в Режим №2): тюнилось под WG 180 мс (=50). Под радио ~2 мс можно опустить (порог дропов был ~10 мс). Мерить на ЖИВОМ движущемся видео.

5. **Хвосты (backlog):**
   - Обратный CRSF-peer (telemetry) — `crsf-elrs.env` PEER=`192.168.1.20` уже стоит; проверить, когда появится обратный поток.
   - **Trim CLAUDE.md** — сейчас **94.5 KB / 760 строк**, цель <40 KB (>2× превышение). Исторические bringup-уроки 2026-05-18/22 вынести в архивный doc.
   - Cleanup на Pi: удалить `~/deploy.tar` и `~/u1u2-deploy` на обеих Pi (мусор от редеплоя; рабочая система их не использует — код в `/opt/u1u2-bridge`).

---

## 📦 ПЕРЕКЛЮЧЕНИЕ РЕЖИМОВ — `switch-mode.ps1` (НОВОЕ, Этап D)

**Полный сценарий смены режима:** переставить Pi физически → выставить WG → `.\switch-mode.ps1 <tunnel|direct>` → подтвердить рестарт (дрон off).

- `tunnel`: Pi **дома**, WG **ВКЛ** (скрипт ходит к Pi по `10.8.0.6/.7`).
- `direct`: Pi **на мосту**, WG **ВЫКЛ** (скрипт ходит к Pi по `192.168.1.20/.10`).
- Что делает: preflight-ping → `git archive HEAD` → `scp` → `install.sh TRANSPORT=<mode> SKIP_APT=1 SKIP_NETPLAN=1 MODE=bench` на обе Pi → рестарт `crsf-bridge@*`+`video-*` по `[y/N]` → печать `is-active` + хвост CRSF.
- Запуск из **обычного PowerShell** (не Claude Code; интернет не нужен — `git archive` локальный, `scp` по LAN/WG).
- `-NoRestart` — только деплой конфига на диск, без рестарта (для безопасной проверки).
- Если скрипт **скачан заново** — `Unblock-File .\switch-mode.ps1` перед запуском (MOTW; см. урок). Сейчас на диске уже разблокирован.
- netplan не трогается (location-adaptive). `install.sh` без `restart` → switcher рестартит явно.

**Физику и WireGuard скрипт НЕ делает — только софт-флип.**

---

## 🔙 ОТКАТ В РЕЖИМ №1 (если что-то сломалось)

Теперь = `switch-mode.ps1 tunnel` (см. выше): Pi домой → WG ВКЛ → `switch-mode.ps1 tunnel` → подтвердить рестарт. После — Pi видны по `10.8.0.6/.7`, CRSF/видео по WG. UFW-direct-правила аддитивны, Режим №1 не ломают.

---

## УРОКИ (внесены в CLAUDE.md коммитом 51bfa84 — не дублировать)
1. `video.env` писался только в direct → дыра переключателя; peer-конфиг писать для всех транспортов из `$CRSF_PEER`.
2. netplan Pi location-adaptive (статика + cloud-init DHCP) → switcher netplan НЕ трогает (`SKIP_NETPLAN=1` в обоих режимах).
3. Скачанный `.ps1` несёт MOTW → ExecutionPolicy блокирует → `Unblock-File` (или отдавать ops-скрипты записью в репо, не скачиванием).

(Прошлые уроки сессии — WG on/off, SKIP_APT, install без restart, git-archive деплой, kill-switch, UFW — уже в CLAUDE.md.)

---

## ❗ НЕ ДЕЛАЙ
- **ДРОН включать / рестартить CRSF при armed — ТОЛЬКО спросив пользователя ЯВНО.** Рестарт `@elrs`/`@p1` рвёт управление ~2 с.
- **НЕ запускать install.sh без `SKIP_NETPLAN=1` вручную** — switcher это делает сам; ручной запуск без флага в direct перепишет netplan (риск lockout). netplan не трогать вообще.
- **НЕ запускать install.sh без `SKIP_APT=1` на мосту** — `apt` упадёт без интернета.
- **WG на ARDOR держать ВЫКЛЮЧЕННЫМ при работе с мостом** (kill-switch). Вкл — для Режима №1 / git-работы / запуска switcher'а в `tunnel`.
- **НЕ запускать клонский (`a8573d6`) install.sh из `~/u1u2-bridge` на Pi** — деплоить только HEAD (это делает switcher через `git archive`).
- НЕ `kmssink` (VOP2 timeout) — только `cage`+`waylandsink`; НЕ убирать `videoconvert` (чёрный на NV12). Грабер — 640×480 MJPG, без `io-mode=4`.
- `pyproject.toml` — чужое, не трогать. `docs/baseline/` — снимок, не трогать.
- В Claude Code Bash-тулзе НЕ `cd ~/...` (резолвится в Windows-домашку). Длинные файлы — через файл-артефакт, не вставкой в терминал.

---

## ТОПОЛОГИЯ / ДОСТУП
- u1 = RX + монитор, `192.168.1.20` (мост) / `10.8.0.6` (WG); u2 = TX, `192.168.1.10` / `10.8.0.7`. Ключ `~/.ssh/u1u2`, sudo NOPASSWD.
- ARDOR: встроенный `Ethernet` `192.168.31.150` (дом, интернет через WG); USB-NIC `Ethernet 3` `192.168.1.50` (мост, без gateway). WG `NSU-pc` `10.8.0.5`.
- CPE-AP `192.168.1.2`, CPE-Client `192.168.1.3`; Pharos UI с отдельного ПК `192.168.0.254`.
- В Режиме №2 Pi на ПРОТИВОПОЛОЖНЫХ концах радио. В Режиме №1 — обе в домашнем свитче.
- Репо: `C:\Users\ARDOR\Documents\Projects\u1u2-bridge`. На Pi код в `/opt/u1u2-bridge`, env в `/etc/u1u2-bridge`.

## ПРАВИЛА РАБОТЫ
- §0 аудит/план → diff → **НЕ коммить/менять без ОК**, поэтапно.
- Дозируй: один логический блок, жди подтверждения. Не вываливать длинные списки/код, если можно разбить.
- В начале шага — карта подключений (где Pi, WG on/off, что трогаем). Помечай «На u1:» / «На u2:» / «В PowerShell:» / «В Claude Code:».
- Claude Code — для локальных команд/git при WG-on; батч-PowerShell — для моста при WG-off. Переключаться не молча.
- При хэндоффе/передаче — сначала полный аудит факта (репо + железо), потом резюме. Не по памяти.
- Монитор на u1. Язык — русский.
