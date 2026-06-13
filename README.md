# u1u2-bridge

Беспроводной линк (CRSF-управление + видео) между двумя устройствами FPV-наземки (У1 ↔ У2) через пару Orange Pi 5 + готовый Wi-Fi PtP мост TP-Link CPE710 + WireGuard поверх.

Архитектурный обзор — в [`docs/HANDOFF.md`](docs/HANDOFF.md) (⚠️ помечен устаревшим на 2026-05-22; актуальные факты — в `CLAUDE.md`). Главные инварианты для разработки — в [`CLAUDE.md`](CLAUDE.md).

## Структура

```
.
├── common/      # Python код общий для У1 и У2 (UART↔UDP мост)
├── u1/          # деплой на мастер-пульт (HDMI вывод)
├── u2/          # деплой на выносную базу (видео-кодирование + ELRS)
├── install.sh   # деплоер на Orange Pi (роль u1|u2)
├── docs/        # HANDOFF.md (обзор), diagrams/ (схемы линка), cheatsheets/
└── tests/       # unit-тесты с моками socket/serial
```

## Разработка на Windows

Требования:
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — `irm https://astral.sh/uv/install.ps1 | iex` в PowerShell
- Git

Первый запуск:

```powershell
uv sync --all-groups
.\verify.ps1
```

Должно быть зелёное `[OK] All checks passed`.

## Деплой на Orange Pi (на железе)

После того как Orange Pi прошита Ubuntu 24.04 от Joshua Riek и подключена к сети — клонируем репо и:

```bash
# На выносной базе:
sudo ./install.sh u2

# На мастер-пульте:
sudo ./install.sh u1
```

Подробности — `docs/HANDOFF.md` (архитектурный обзор, частично устарел). Актуальные факты — `CLAUDE.md`.

## Команды разработки

```powershell
.\verify.ps1     # все проверки: ruff + mypy + pytest + shellcheck
.\format.ps1     # авто-починка форматирования
uv run pytest    # только тесты
uv run mypy common tests   # только типы
```

## Состояние

Актуальное состояние и уроки — `CLAUDE.md` (раздел Lessons & Incidents). Исходный план/этапы — `docs/HANDOFF.md` §6/§8 (⚠️ устарел).
