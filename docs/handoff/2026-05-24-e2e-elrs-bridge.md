# HANDOFF — 2026-05-24 — End-to-end ELRS bridge через WireGuard

> **Статус:** РАБОТАЕТ. Полный канал u1 → WireGuard → u2 → ELRS → дрон подтверждён
> визуально в BetaFlight Receiver (AETR sweep, AUX1=LOW DISARM-гард).

---

## 1. Что заработало end-to-end

```
u1 (10.8.0.6)
  bench/crsf_udp_source.py --mode sweep --rate 250
    │
    │ UDP/14552, 26 B/frame, 250 fps
    ▼
  wg0 (WireGuard через VPS 95.140.147.108)
    │
    ▼
u2 (10.8.0.7)
  crsf-bridge@elrs.service (0.0.0.0:14552 → /dev/ttyS7)
    │
    │ UART7-M2, 420000 baud, pin 26
    ▼
  SN74HC14N (gate 1, инвертирует TX)
    │
    ▼
  ELRS Ranger Micro (UART_INVERTED=on, master 91b1ee)
    │
    │ 2.4 GHz RF
    ▼
  Дрон с ELRS RX (бинд OK)
    │
    ▼
  BetaFlight Receiver tab: AETR синусоида, AUX1=LOW
```

### Измеренные параметры

| Метрика | Значение |
|---|---|
| Frame rate (bench) | 250 fps стабильно |
| Frame size | 26 B (CRSF RC_CHANNELS_PACKED) |
| Throughput (bench → bridge) | 6492–6494 B/s (целевые 6500) |
| Потери (за сессию) | 0 |
| `udp->uart` (journalctl) | ~6500 B/s |
| `uart->udp` (обратная телеметрия) | ~50–300 B/s (link statistics от ELRS) |

---

## 2. Конфигурация на u2-pi

### Env-файл

`/etc/u1u2-bridge/crsf-elrs.env`:
```
SERIAL_DEV=/dev/ttyS7
BAUD=420000
LISTEN=0.0.0.0:14552
PEER=10.8.0.6:14552
```

### Systemd

`crsf-bridge@elrs.service` — enabled, auto-start при загрузке.

```bash
systemctl status crsf-bridge@elrs
journalctl -u crsf-bridge@elrs -f
```

### UFW

```bash
sudo ufw allow from 10.8.0.6 to any port 14552 proto udp comment 'crsf-elrs from u1'
```

Без этого правила UDP-пакеты молча дропаются на INPUT chain (default-deny),
сервис работает, но `udp->uart=0 B/s`. См. lesson в CLAUDE.md.

---

## 3. Конфигурация на u1

Bench-скрипт запускается вручную:

```bash
uv run python -m bench.crsf_udp_source --peer 10.8.0.7:14552 --mode sweep
```

В production u1 будет запускать `common/joystick_to_crsf.py` с реальным джойстиком
(RadioMaster TX12 через USB), не bench-скрипт.

---

## 4. Открытые вопросы

### a) Обратная телеметрия u2→u1

На u1 пока нет UFW-правила для входящего 14552/udp от 10.8.0.7.
Bench-скрипт не слушает обратный трафик (он только шлёт). Когда на u1
поднимется `crsf-bridge` для пульта П1 RadioMaster TX12 — нужно будет
открыть порт и настроить PEER в обратном направлении.

### b) Полевые испытания

Тест проводился дома через WireGuard VPN (u1→VPS NL→u2). На дистанции
через CPE710 (LAN 192.168.1.0/24) не проверялось. Латенция WG-маршрута
через VPS ~40–60 мс, через CPE710 ожидается ~5–10 мс.

### c) Видео-pipeline

`video-tx.sh` / `video-rx.sh` написаны, не тестировались. Отдельная задача.

### d) Второй CRSF-канал

Env для `crsf-tx2` (порт 14551) существует. Второй ELRS-модуль физически
не подключён. Для него нужен второй gate на том же 74HC14N (пины 3→4)
и второй UART OPi (overlay для UART8 или другого свободного).

### e) Второй Waveshare на u2

Сейчас CRSF идёт через встроенный UART7 (/dev/ttyS7), не через Waveshare
USB→RS485. Waveshare-адаптеры (ttyACM-CRSF1, ttyACM-CRSF2) на u2 подключены,
но ELRS получает данные через UART7 напрямую. Для второго ELRS-модуля
нужно решить: второй встроенный UART или Waveshare.

---

## 5. Lessons из этого теста

Записаны в `CLAUDE.md` (раздел Lessons & Incidents, дата 2026-05-24):

1. **UFW дропает пакеты на новые порты crsf-bridge молча** — при создании нового
   env-файла обязательно парный `ufw allow`.
2. **ELRS TX в WiFi config mode игнорирует CRSF** — проверять SSID `ExpressLRS TX`
   на телефоне перед диагностикой UART.

---

*Конец handoff.*
