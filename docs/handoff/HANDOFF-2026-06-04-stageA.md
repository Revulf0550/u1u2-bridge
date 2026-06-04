# HANDOFF → Этап A (чистка + автозапуск) · u1u2-bridge · 2026-06-04

> Точка входа в следующую сессию. Составлен ПОСЛЕ выполнения и сверки с фактом
> (`git log -3`, `is-active/is-enabled @p1`(u1)/`@elrs`(u2)).

## СНАЧАЛА ПРОЧИТАЙ
- `docs/PLAN.md` — мастер-план (2 режима, этапы A–E).
- `docs/baseline/` — точка отката рабочей CRSF-конфигурации (BASELINE.md + env + юниты).
- `CLAUDE.md` — Lessons & Incidents + `## Architecture` (GStreamer) + `## Process`.
- **§0:** любая работа — после сверки с фактом (репо + железо), не по памяти. Хэндофф
  «по памяти» запрещён.

## ВЫПОЛНЕНО (Этап A)
- **A0 — точка отката** (`06a0222`): вербатим `crsf-p1.env`/`crsf-elrs.env` + рендеры
  юнитов `@p1`/`@elrs` + `BASELINE.md` в `docs/baseline/`; `.gitattributes` `*.env eol=lf`.
- **A5 — install.sh переучен** (`a8573d6`): генерит реальную схему `p1`(u1)/`elrs`(u2)
  на туннеле, порт 14552; `TRANSPORT=tunnel|direct` (дефолт tunnel, авто `SKIP_NETPLAN=1`);
  `tx1/tx2` больше не создаются; видео отвязано от `MODE`.
- **A1a — деплой на обе Pi** (`sudo TRANSPORT=tunnel SKIP_VIDEO=1 ./install.sh u1|u2`):
  `/opt` перезалит свежим (старая сломанная копия u2 убита), env = baseline,
  `@p1`/`@elrs` active/enabled, CRSF ~6500 B/s (CRSF 250 Hz), netplan НЕ тронут.
- **A3 — tmpfiles** на u1: `/etc/tmpfiles.d/u1u2-bridge.conf` создаёт `/run/user/0` на буте
  (ручное создание больше не нужно; пересоздание на ребуте проверить в B3).
- **A-clean** на обеих Pi: `crsf-bridge@tx1/@tx2` disable --now (inactive/disabled) +
  `crsf-tx1/tx2.env` удалены. `@p1`/`@elrs` не задеты. (Юниты не в репо → коммитить нечего.)

## СОСТОЯНИЕ (факт 2026-06-04)
- **CRSF Режим №1 через туннель — работает:** Boxer → CH340 → u1:`/dev/ttyUSB0` →
  `crsf-bridge@p1` → UDP 14552 → wg → `crsf-bridge@elrs` → u2:`/dev/ttyS7` → ELRS.
  `@p1` (u1) и `@elrs` (u2) — active/enabled.
- **Видео НЕ под systemd** — ручной запуск (`cage + waylandsink`, `JITTER_LATENCY=50`).
  `video-rx`/`video-tx` НЕ включены (деплой шёл с `SKIP_VIDEO=1`).
- **git = `a8573d6`**, `main...origin/main` синхронизирован. Клоны на обеих Pi на `a8573d6`.
- **Телеметрия (обратный поток ELRS→пульт) = 0** — ОТКРЫТЫЙ вопрос (см. B-telem).

## ДАЛЬШЕ
1. **A2 — видео под systemd (вариант «а»):** завести `video-rx.service` (u1) +
   `video-tx.service` (u2). **РИСК:** cage от root + владение TTY → возможен Restart-loop;
   fallback — ручной запуск / `SKIP_VIDEO=1`. Тест на `videotestsrc`, дрон — только финал
   (СПРОСИТЬ, когда включать). Ограничения: `kmssink` мёртв (VOP2), `videoconvert`
   обязателен (NV12 не согласуется), cage требует `XDG_RUNTIME_DIR=/run/user/0`.
2. **Хвост доков до Этапа B:** убрать ссылки на `tx1/tx2`/`14550`/`14551` в
   `smoke_test.sh`, `README`, таблице Commands в `CLAUDE.md`. **НЕ трогать `docs/baseline/`**
   (там tx-имена — часть исторического снимка отката).
3. **Этап B (проверка Режима №1):** B1 видео e2e; B2 CRSF + замер задержки;
   **B-telem** — телеметрия на пульте (RSSI/LQ/предупреждения), ОТКРЫТЫЙ вопрос, спросить
   пользователя; B3 ребут обеих Pi → всё поднимается само (проверить `@p1`/`@elrs` enabled
   + пересоздание `/run/user/0`).

## ТОПОЛОГИЯ
- **u2 = TX:** `ssh -i ~/.ssh/u1u2 ubuntu@10.8.0.7`.
- **u1 = RX + HDMI-монитор:** `ssh -i ~/.ssh/u1u2 ubuntu@10.8.0.6`.
- Транспорт: WireGuard `10.8.0.x` через интернет, RTT ~150 мс, iface `enP3p49s0`.
  CPE710 НЕ развёрнут (Этап C).
- Деплой: `sudo TRANSPORT=tunnel [SKIP_VIDEO=1] ./install.sh u1|u2` (из `~/u1u2-bridge`).

## НЕ ДЕЛАЙ
- НЕ возвращать `kmssink` (VOP2: `wait pd0 off timeout`). Дисплей — cage+waylandsink.
- НЕ убирать `videoconvert` перед `waylandsink` (чёрный экран, NV12 не согласуется).
- НЕ запускать/доверять старому `/opt` без редеплоя (истина — репо/`install.sh`).
- `pyproject.toml` — чужое незакоммиченное изменение, не трогать.
- `docs/baseline/` — снимок отката, не редактировать «под текущее».

## ПРАВИЛА РАБОТЫ
- §0 аудит/план → diff → НЕ коммить без ОК (не «allow all»), поэтапно.
- Дозируй: один логический блок, жди подтверждения. Без простыней.
- Помечай блоки «На u1:» / «На u2:» / «В PowerShell:».
- ЯВНО говорить, когда включать ДРОН (только финал живой камеры). Монитор на u1. Русский.
