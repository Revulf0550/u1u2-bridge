# hardware/

Python-скрипты для тестирования физического слоя (UART, GPIO, hardware-инвертор 74HC14N).

## Скрипты

| Файл | Назначение |
|---|---|
| `crsf_smoke_test.py` | CRSF RC frames @ 250 Hz, baud 420000 — smoke-test инвертора и ELRS-линка |
| `crsf_jitter_test.py` | Расширенная версия с измерением jitter, throughput, min/max интервалов |

## Workflow деплоя

1. Пишем/правим скрипт в репозитории на ноуте
2. Копируем на Pi:
   ```powershell
   scp hardware/*.py ubuntu@192.168.31.100:~/hardware/
   ```
   Или через WireGuard:
   ```powershell
   scp hardware/*.py ubuntu@10.8.0.7:~/hardware/
   ```
3. SSH на Pi и запуск:
   ```bash
   sudo python3 ~/hardware/crsf_smoke_test.py
   sudo python3 ~/hardware/crsf_jitter_test.py
   ```

## Требования

- **Где работает:** u2-pi (Orange Pi 5 Max)
- **UART:** `/dev/ttyS7` через overlay UART7-M2 (см. `docs/opi5max-uart7-setup.md`)
- **Инвертор:** 74HC14N между OPi TX и ELRS (см. `docs/inverter-schematic.md`)
- **Права:** `sudo` (или пользователь в группе `dialout`)
- **Python:** системный python3 + `pyserial` (`apt install python3-serial`)
