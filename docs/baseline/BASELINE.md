# BASELINE — рабочая CRSF-конфигурация (точка отката A0)

Снято с железа 2026-06-04. Режим №1 (туннель WireGuard 10.8.0.x), порт 14552.
Эти файлы — снимок для отката, НЕ деплой-артефакты. Истина деплоя — install.sh (после A5).

## Состояние юнитов
| Pi | crsf-bridge@p1 | crsf-bridge@elrs |
|----|----------------|------------------|
| u1 (10.8.0.6) | **enabled / active** | inactive (не используется) |
| u2 (10.8.0.7) | inactive (не используется) | **enabled / active** |

## Поток
Boxer → CH340 → u1:/dev/ttyUSB0 → crsf-bridge@p1 → UDP 14552 → wg →
crsf-bridge@elrs → u2:/dev/ttyS7 → ELRS.

## Факты железа
- **u1:** CH340 `1a86:7523` → `/dev/ttyUSB0` = пульт Boxer (через SN74HC14N).
- **u2:** `/dev/ttyS7` (UART7) → ELRS-модуль.
- Порт UDP обеих сторон: **14552**, peer = противоположный wg-адрес.

## Откат
Скопировать соответствующий `crsf-*.env` в `/etc/u1u2-bridge/` на нужной Pi,
`systemctl enable --now crsf-bridge@p1` (u1) / `@elrs` (u2).
