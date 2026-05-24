# Инвертор UART для ELRS (SN74HC14N)

Аппаратный инвертор между OPi 5 Max UART7 TX и ELRS Ranger Micro CRSF input.
Необходим потому, что ELRS firmware (master 91b1ee) ожидает inverted UART (`UART_INVERTED=on`).

## BOM

| Компонент | Номинал / модель | Назначение |
|---|---|---|
| IC1 | Texas Instruments SN74HC14N, DIP-14 | Hex Schmitt-trigger inverter |
| C1 (опционально) | 100 нФ керамический | Decoupling между VCC и GND у IC |

Со старой BC548-платы выкинуты: BC548 (NPN), R1=2.2kΩ, R2=4.7kΩ. Single-NPN inverter не работает на 420k baud из-за storage time в hard saturation.

## Pinout IC (SN74HC14N, DIP-14)

Ориентация: выемка / точка-индикатор pin 1 — **сверху** при вертикальном монтаже, pin 1 в верхнем-левом углу.

| Pin IC | Функция | Подключение |
|---|---|---|
| 1 | 1A (input) | зелёный провод от OPi pin 26 (UART7-M2 TX) |
| 2 | 1Y (output, inverted) | белый провод к ELRS pin 5 (CRSF) |
| 3 | 2A (unused input) | GND (через перемычку) |
| 4 | 2Y (unused output) | NC |
| 5 | 3A (unused input) | GND (через перемычку) |
| 6 | 3Y (unused output) | NC |
| 7 | GND | чёрный короткий от OPi pin 6 + GND-шина |
| 8 | 4Y (unused output) | NC |
| 9 | 4A (unused input) | GND (через перемычку) |
| 10 | 5Y (unused output) | NC |
| 11 | 5A (unused input) | GND (через перемычку) |
| 12 | 6Y (unused output) | NC |
| 13 | 6A (unused input) | GND (через перемычку) |
| 14 | VCC | синий провод от OPi pin 1 (3.3V) |

## Подключение проводов (6 проводов)

| Pin OPi | Функция | Провод | Куда |
|---|---|---|---|
| 1 | 3.3V | синий | IC pin 14 (VCC) |
| 2 | 5V | красный | ELRS Ranger Micro pin 3 (питание модуля) |
| 6 | GND | чёрный длинный | ELRS pin 4 (GND модуля) |
| 6 | GND | чёрный короткий | IC pin 7 (GND-шина) |
| 26 | UART7-M2 TX | зелёный | IC pin 1 (input) |
| — | — | белый | IC pin 2 (output) → ELRS pin 5 (CRSF) |

## ELRS Ranger Micro — pinout (JR-style)

| Pin модуля | Сигнал | Откуда |
|---|---|---|
| 3 | 5V | OPi pin 2 (красный) |
| 4 | GND | OPi pin 6 (чёрный длинный) |
| 5 | CRSF (inverted) | IC pin 2 (белый) |

## GND-шина

Один проводок физически проходит через pins 7, 3, 5, 9, 11, 13 на плате, припаян в 6 точках. От общей точки (pin 7) — чёрный короткий провод к OPi pin 6.

Все неиспользуемые входы **обязательно** на GND — иначе CMOS-входы ловят наводку и IC потребляет лишний ток (через shoot-through в выходных каскадах).

## Тест-процедура (4 этапа)

### Этап 1: Прозвонка

Мультиметром в режиме continuity проверить:

- OPi pin 1 (3.3V) → IC pin 14: звенит
- OPi pin 6 (GND) → IC pin 7: звенит
- IC pin 7 → IC pins 3, 5, 9, 11, 13: все звенят (GND-шина)
- OPi pin 26 → IC pin 1: звенит
- IC pin 2 → ELRS pin 5: звенит
- OPi pin 2 (5V) → ELRS pin 3: звенит
- OPi pin 6 → ELRS pin 4: звенит

### Этап 2: Static DC (без UART-трафика)

Подать питание (OPi включён). Мерить DC относительно GND:

| Точка | Ожидание |
|---|---|
| IC pin 14 (VCC) | 3.2–3.3V |
| IC pin 1 (input, UART idle = HIGH) | 3.2–3.3V |
| IC pin 2 (output, inverted idle = LOW) | 0–0.1V |
| ELRS pin 3 (5V) | 4.8–5.2V |

### Этап 3: Stream на 115200 baud

Запустить непрерывную передачу на пониженной скорости:

```bash
sudo python3 -c "
import serial, time
s = serial.Serial('/dev/ttyS7', 115200, timeout=1)
while True:
    s.write(b'\xAA' * 64)
    s.flush()
    time.sleep(0.01)
"
```

Мерить DC на IC pin 2 (output): должно быть ~1.5–2.0V (среднее от быстрого переключения 0↔3.3V). Если 0V или 3.3V стабильно — вход не подключён или IC не запитан.

### Этап 4: CRSF 420k baud (финальный)

```bash
sudo python3 ~/hardware/crsf_smoke_test.py
```

Критерий успеха: 2+ минуты стрима без появления WiFi сети `ExpressLRS TX` на телефоне рядом. Если WiFi появляется через 30-60 секунд — ESP32 не валидирует CRSF, проверять edges (этап 2-3) и подключение.
