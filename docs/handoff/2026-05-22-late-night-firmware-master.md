# HANDOFF: u1u2-bridge — П3 продолжение, firmware master + drive contention (2026-05-22, late night)

> Документ продолжает серию handoff'ов. Предыдущий: `docs/handoff/2026-05-22-late-evening-gnd-mystery.md`. Эта сессия (5-я за день) — посвящена разрешению GND-блокера и выяснению того, что firmware на модуле = самосборка с master-ветки ELRS, а не stable release. GND починен обходом Dupont. CRSF stream до модуля не парсится. Сформулированы три оставшиеся гипотезы.
>
> Перед стартом нового чата прочитать в репо: `CLAUDE.md`, `docs/wiring-opi5max.md`, все handoff'ы в `docs/handoff/`.

---

## 1. ⚡ TL;DR

- **GND-блокер прошлой сессии решён** обходным путём: пользователь отпаял чёрный провод от Dupont-коннектора на header pin 6 и **припаял/привязал напрямую к плате Pi** (точная точка не уточнялась). Continuity OPi pin 6 ↔ socket pin 4 теперь пищит ✅. Сам Dupont на pin 6 действительно был ненадёжным.
- **Сервис `crsf-bridge@tx1` остановлен и disabled.** `systemctl is-active` → `inactive`. Путь к `/dev/ttyS7` свободен для ручных тестов.
- **Тест "WiFi не появляется" провален** — модуль ушёл в WiFi mode через 30 сек несмотря на стабильный 60 Hz CRSF stream от OPi. Значит, CRSF до парсера ESP32 не доходит, **несмотря на исправленный GND**.
- **Critical finding по firmware**: версия модуля = `master (91b1ee) 2440`. Это **самосборка с development-ветки ELRS**, не stable release. Может содержать regression или нестандартное поведение в CRSF handling.
- **Pinout подтверждён** окончательно по WebUI hardware-section: `CRSF Serial Pins: RX = 13, TX = 13` — single pin half-duplex. То есть пайка зелёного на JR-bay socket pin 5 = ESP32 GPIO 13 — **правильная**, мы паяемся туда куда нужно.
- **Никаких UART inversion/polarity опций в WebUI нет** — значит модуль ждёт стандартный non-inverted CRSF (что мы и шлём).
- **Главный кандидат на блокер**: drive contention в half-duplex single-pin режиме. OPi UART7 push-pull непрерывно драйвит линию; ESP32 GPIO 13 периодически переключается в output для telemetry (TLM interval = 240ms). Когда оба драйвят одновременно — short circuit, corrupt signal. Решение — резистор 1кΩ-4.7кΩ последовательно с OPi TX.

---

## 2. 🟢 Что сделано в этой сессии (хронология)

1. **Сервис `crsf-bridge@tx1` стоп+disable.** Выполнено пользователем по SSH, `is-active` → `inactive` ✅.

2. **GND-блокер решён**. Пользователь обошёл ненадёжный Dupont на OPi header pin 6 — припаял/привязал чёрный провод напрямую к плате Pi (видимо к какой-то точке GND plane на PCB). Continuity OPi pin 6 ↔ socket pin 4 теперь пищит. Подтверждено мультиметром.

3. **Continuity recheck двух главных цепей** — обе пищат:
   - Signal: OPi pin 29 ↔ socket pin 5 (зелёный)
   - GND: OPi pin 6 ↔ socket pin 4 (чёрный — через новую пайку к плате)

4. **Запущен тест "WiFi не появляется"** (независимый от LED критерий парсинга CRSF):
   - CRSF stream запущен ДО подачи питания на модуль
   - Stream стабилен 60 Hz, видны строки `>>> N packets, 60 Hz`
   - Подан XT30 → модуль стартует с уже идущим CRSF
   - Через 30+ сек WiFi `ExpressLRS TX` появилась → **CRSF не парсится** ❌

5. **Открыт WebUI** `http://10.0.0.1/`. Структура прояснилась: это **одна прокручиваемая страница** с tabs **OPTIONS / WIFI / UPDATE**. Hardware section находится **внизу** Options page (не отдельная страница). В прошлой сессии скриншоты hardware-секции были сделаны со скроллом — handoff §3.3 неточно описал их как "содержимое hardware-страницы".

6. **Получены полные скриншоты WebUI** (см. §9 для деталей):
   - Версия firmware: `master (91b1ee) 2440`
   - Packet rate: `RUS 24Hz(-109dBm)` — самый низкий OTA rate
   - Binding UID Overridden: `64,160,44,152,121,177`
   - TLM report interval: 240ms
   - AirPort serial device: **disabled**
   - AirPort UART baud: 420000 (но disabled)
   - **CRSF Serial Pins: RX=13, TX=13** (single pin half-duplex) — pinout правильный
   - Backpack: enabled, GPIO 16/17, baud 460800 (другой UART, не конфликт)
   - Radio Power: RXEN=32, TXEN=33 (это пятаки 32_TX/32_RX на PCB, на которых мы сидели раньше)

7. **Заключения**:
   - Pinout правильный (паяем в нужный пин)
   - Никаких настроек, которые могли бы быть причиной отказа парсинга
   - Самое примечательное — firmware master branch, не stable

8. **Сформулированы три оставшиеся гипотезы** (см. §5).

9. **Решение прервать сессию** — контекст перегружен, для каждой из трёх оставшихся гипотез требуется физическая работа или серьёзная операция (пайка резистора, перепрошивка, или handset test). Лучше сделать в чистой сессии с трезвым выбором.

---

## 3. ✅ Что подтверждено фактами

| # | Факт | Подтверждение |
|---|---|---|
| 1 | GND continuity OPi pin 6 ↔ socket pin 4 пищит | Мультиметр после перепайки на плату Pi |
| 2 | Signal continuity OPi pin 29 ↔ socket pin 5 пищит | Мультиметр |
| 3 | Сервис `crsf-bridge@tx1` остановлен | `systemctl is-active` → `inactive` |
| 4 | CRSF stream от OPi стабилен 60 Hz | Видны строки `>>> N packets, 60 Hz` в логе |
| 5 | Модуль уходит в WiFi mode через 30+ сек при идущем CRSF stream | Прямое наблюдение AP `ExpressLRS TX` в списке сетей |
| 6 | Firmware = master (91b1ee) 2440 | Шапка WebUI |
| 7 | CRSF Serial Pins на этой firmware: RX=13, TX=13 | Hardware section WebUI (Image 4 скриншотов) |
| 8 | AirPort serial device disabled — UART не перехвачен | Options section WebUI |
| 9 | Backpack на GPIO 16/17 (не конфликт с CRSF на GPIO 13) | Hardware section WebUI |
| 10 | Никаких UART inversion / polarity опций в WebUI нет | Полный обзор всех вкладок |

---

## 4. ❌ Что НЕ работает — текущий блокер

**CRSF stream от OPi через socket pin 5 не парсится модулем**, несмотря на:
- Правильный pinout (pin 5 = GPIO 13 = CRSF Serial RX)
- Исправленный GND (continuity пищит)
- Стабильный 60 Hz CRSF фреймов корректного формата (sync 0xC8, len 24, type 0x16 RC_CHANNELS_PACKED, CRC8 poly 0xD5)
- Standard baud 420000, 8N1, non-inverted UART (как и ожидает ELRS)

Симптом: модуль через ~30 сек после boot поднимает AP `ExpressLRS TX` — стандартное поведение "no CRSF received".

---

## 5. 💡 Три оставшиеся гипотезы (по убывающей вероятности)

### Гипотеза 1 — Drive contention в half-duplex single-pin

**Суть**: CRSF UART на этой firmware = single pin (RX=TX=13). ESP32 GPIO 13 работает в half-duplex: input когда ждёт CRSF, output когда отправляет telemetry (TLM interval 240ms).

OPi UART7_TX — стандартный **push-pull** драйвер, **непрерывно** держит линию (low/high). Когда ESP32 решает ответить telemetry и переключает GPIO 13 в output mode — оба источника драйвят одну линию. Если OPi гонит "1" (3.3V) а ESP32 — "0" (0V), это **short circuit** между двумя источниками с активным push-pull.

Последствия:
- Сигнал телеметрии искажается → ESP32 не может корректно ответить → могут быть аномалии в state machine модуля
- Длительное накопление коротких замыканий может повредить выходные драйверы (но это медленный процесс)
- Master firmware может детектировать collision и решать "линия мёртвая" → уходить в WiFi

**Решение для проверки**: добавить **резистор 1кΩ-4.7кΩ последовательно с OPi TX** (между OPi pin 29 и socket pin 5). При этом:
- OPi становится "слабым" источником через резистор
- ESP32 в output mode легко пересиливает OPi
- Короткого замыкания больше нет

**Время**: 10-15 минут пайки.
**Требует**: резистор номиналом 1k-4.7k в наличии у пользователя.

### Гипотеза 2 — Master firmware bug / нестандартное поведение

**Суть**: `91b1ee` — конкретный коммит development-ветки master. Не stable release. Может содержать regression в CRSF parser, ожидать какие-то discovery-фреймы (`CRSF_FRAMETYPE_DEVICE_PING` 0x28) перед активацией, или иметь другую поломку.

Standard handset (TX12 с EdgeTX) шлёт не только RC_CHANNELS_PACKED, но и другие фреймы (parameter read, device info, etc). Мы шлём **только** RC_CHANNELS_PACKED — это технически валидно по spec, но может не активировать конкретно эту master сборку.

**Решение**:
1. (Быстро) Добавить в наш стример разные CRSF фреймы — DEVICE_PING, PARAMETER_READ — посмотреть реакцию.
2. (Долго) Перепрошить модуль на stable 3.x release через WebUI (UPDATE tab) или через USB.

**Время**: пункт 1 — час кода, пункт 2 — 30+ минут.
**Риск**: перепрошивка может убить модуль если что-то пойдёт не так (нужен backup firmware на всякий случай).

### Гипотеза 3 — Модуль повреждён

**Суть**: в одной из предыдущих сессий мы паялись на пятаки `32_TX`/`32_RX`, считая их UART, и слали туда UART signal с 420k. Это были GPIO RXEN/TXEN, настроенные firmware как **output** (управление RF amp). Параллельный drive от двух источников = short. Могло повредить GPIO 32/33 drivers, или каким-то путём ESP32 в целом.

WebUI работает = boot OK = большая часть ESP32 функциональна. Но конкретно CRSF UART parser может быть сломан.

**Решение для проверки**: **вставить модуль в JR-bay handset TX12**, перевести handset в режим CRSF (External RF → CRSF → Ranger Micro), посмотреть LED модуля:
- Если LED показывает зелёный fade или связывается с приёмником → модуль OK, проблема не в железе, копать гипотезы 1 и 2
- Если LED останется оранжевым / уйдёт в WiFi → модуль сломан, дальнейшая работа невозможна без замены / ремонта

**Время**: 5-10 минут.
**Требует**: handset TX12 рядом, кабели/антенна, понимание настроек EdgeTX External RF.

---

## 6. 🛤️ Рекомендуемый порядок действий в новой сессии

**Логика**: handset test (гипотеза 3) — самый быстрый и самый информативный шаг. Он сразу разделяет "модуль OK" от "модуль сломан". После него выбор между гипотезой 1 и 2 становится понятным.

1. **Handset test (5-10 мин)** — проверка базовой функциональности модуля.
   - Если модуль работает с handset → переходим к шагу 2
   - Если не работает → модуль сломан, проект блокирован на покупке нового модуля

2. **Резистор 1k-4.7k последовательно с OPi TX (10-15 мин)** — проверка гипотезы drive contention.
   - Если CRSF начал парситься → блокер решён
   - Если нет → переходим к шагу 3

3. **Перепрошивка на stable release или эксперимент с CRSF DEVICE_PING фреймами (30+ мин)** — проверка гипотезы 2.
   - Сначала попробовать добавить DEVICE_PING в стример (бесплатно, без риска)
   - Если не помогло — перепрошить на stable 3.x через WebUI UPDATE tab

---

## 7. 🚨 Висящие неопределённости / открытые вопросы

### 7.1. Куда именно пользователь припаял GND
В этой сессии пользователь сказал "с гребенки пина 4 кабель обвязал просто на плату пи и земля появилась на пине 6". Точная точка не уточнялась. Continuity пищит → электрически это GND plane. Но если потом возникнут проблемы (шум, ground loop) — стоит проверить визуально что припай чистый и на правильной точке.

### 7.2. Откуда взялся master firmware на модуле
Это не stable release из RadioMaster Github. Видимо, предыдущий владелец модуля собирал firmware из исходников сам (commit hash 91b1ee). Может быть с custom config. Что в этом custom config — неизвестно. Стоит при возможности посмотреть git log `91b1ee` в репо ExpressLRS/ExpressLRS — есть ли там известные баги или special handling.

### 7.3. Совместимость с EdgeTX External RF mode
В шаге 1 порядка действий (handset test) предполагается что у пользователя есть TX12 с правильно настроенным EdgeTX. Если EdgeTX на TX12 не настроен или версия старая — handset test может дать ложно-негативный результат.

### 7.4. AirPort UART baud = 420000 при disabled AirPort device
AirPort feature disabled, но baud rate настроен на стандартный CRSF 420000. Возможно эта настройка влияет на что-то ещё в master firmware (например, на полярность или режим CRSF UART). Стоит при возможности изучить master source code в окрестностях `AirPort` handling.

---

## 8. ⚠️ Антипаттерны для новой сессии (НЕ повторять)

1. **НЕ пытаться "ещё раз проверить continuity" на текущей сборке** — все цепи уже подтверждены, мультиметр пищит. Дальнейшая electrical диагностика не даст новой информации.
2. **НЕ запускать `crsf-bridge@tx1` сервис до починки env-файла**. Текущий env содержит `SERIAL_DEV=/dev/ttyACM-CRSF1` (не существует). Сначала исправить на `/dev/ttyS7`, потом enable.
3. **НЕ паять без резистора** прежде чем посмотрел handset test. Если модуль сломан — пайка резистора бесполезна.
4. **НЕ перепрошивать модуль** прежде чем испробовал гипотезы 3 и 1. Перепрошивка имеет риск кирпича.
5. **НЕ полагаться на LED модуля** как единственный критерий — пользователь плохо различает цвета, и boot animation может ввести в заблуждение. Использовать тест "WiFi не появляется" или telemetry round-trip.

---

## 9. 📋 Технические данные (для копирования)

### 9.1. Hardware распиновка (актуальная)

| Сторона | Сигнал | Цвет | Состояние |
|---|---|---|---|
| OPi 5 Max GPIO | Pin 29 (UART7_TX) | зелёный | На JR-bay socket pin 5 (CRSF) |
| OPi 5 Max плата (точка GND plane) | GND | чёрный | Припаян напрямую к плате, **не через Dupont на pin 6** |
| Socket pin 4 (GND) | GND | чёрный | Второй конец чёрного провода |
| OPi 5 Max GPIO | Pin 38 (UART7_RX) | синий | **Отрезан**, не используется |

### 9.2. SSH и сетевые адреса

```
u2-Pi:    ssh ubuntu@10.8.0.7  (WireGuard)
u1-Pi:    ssh ubuntu@10.8.0.6  (WireGuard)
Ranger Micro WiFi AP:  ExpressLRS TX  (password: expresslrs)
WebUI:    http://10.0.0.1/
```

### 9.3. Полный pinout Ranger Micro (firmware master 91b1ee, 2440 MHz S-Band)

```
CRSF Serial:        RX=13, TX=13 (single pin half-duplex)
Serial2 Pins:       не настроены
Radio Chip (SX1280): BUSY=22, DIO0=пусто, DIO1=21, MISO=19, MOSI=23, NSS=4, RST=5, SCK=18
DCDC enabled:       checked
RFO_HF enabled:     unchecked
Radio Antenna:      CTRL=пусто, CTRL_COMPL=пусто
Radio Power:        PA enable=пусто, APC2=пусто, RXEN=32, TXEN=33
Power levels:       Min=25mW, High=1000mW, Max=1000mW, Default=50mW
Power Level control: via SEMTECH
Power Value(s):     -17,-15,-12,-7,-4,2
PA LNA Gain:        12
RGB LED:            pin=15, GRB byte order
Backpack:           Enabled, RX=16, TX=17, baud=460800, BOOT=26, EN=25, Passthrough=230400
Fan enable:         pin=27
OLED/TFT:           None
```

### 9.4. Runtime Options (актуальные)

```
Binding Phrase:     (пусто)
Binding UID:        Overridden, 64,160,44,152,121,177
S-Band frequency:   2440 MHz
Packet rate:        RUS 24Hz(-109dBm)
WiFi auto-on:       60 сек
TLM report interval: 240 ms
Fan runtime:        30 сек
AirPort Serial:     disabled
AirPort UART baud:  420000
```

### 9.5. Команды для быстрого старта в новой сессии

**Открыть SSH:**
```powershell
ssh ubuntu@10.8.0.7
```

**Проверить состояние сервиса (должен быть inactive):**
```bash
sudo systemctl is-active crsf-bridge@tx1
```

**CRSF-стример (если нужен — для повторных тестов):** см. §9.5 предыдущего handoff'а `2026-05-22-late-evening-gnd-mystery.md`.

---

## 10. 📚 Lessons (черновики для CLAUDE.md)

```markdown
### 2026-05-22 (late night) · WebUI ELRS — это одна прокручиваемая страница, не несколько

В master-сборках ELRS (по крайней мере на commit 91b1ee) WebUI `http://10.0.0.1/` не имеет отдельной hardware-страницы. Есть три вкладки: **OPTIONS, WIFI, UPDATE**. Hardware-секция (CRSF Serial Pins, Radio Chip, Radio Power, и т.д.) находится **внизу OPTIONS-страницы** при прокрутке. Также там есть кнопки `UPLOAD target configuration` и `SAVE TARGET CONFIGURATION` для изменения pinout прямо через web.

**Правило:** при работе с WebUI ELRS — прокрутить OPTIONS-страницу до конца. Не ограничиваться видимой верхней частью.

**Проверка:** на странице должна быть видна секция "CRSF Serial Pins" с pin RX и pin TX.

### 2026-05-22 (late night) · Версия firmware ELRS — проверять первым делом

Шапка WebUI показывает версию firmware в формате `Firmware Rev. {branch} ({hash}) {band}`. Если branch = `master` — это самосборка с development ветки, **не stable release**. Поведение может отличаться от документированного.

**Правило:** перед любыми тестами CRSF к модулю — посмотреть версию firmware в шапке WebUI. Если master или git-hash — относиться к модулю как к unknown firmware и иметь в виду возможные regressions.

**Проверка:** Firmware Rev. на главной странице WebUI должна показывать понятную версию (3.x.x) для stable.

### 2026-05-22 (late night) · Drive contention в half-duplex single-pin CRSF — потенциальный блокер

ELRS TX модули обычно используют CRSF UART как half-duplex single-pin (RX pin == TX pin в hardware config). ESP32 переключает direction GPIO между приёмом команд и отправкой telemetry. Если подключить к этому пину OPi UART7 в стандартном push-pull режиме, который **непрерывно** драйвит линию — будут drive collisions с ESP32 telemetry output.

**Правило:** при подключении OPi (или любого Linux SBC) UART к single-pin half-duplex CRSF — ставить **резистор 1кΩ-4.7кΩ последовательно с TX** SBC. Это делает SBC "слабым" источником, ESP32 telemetry легко пересиливает.

**Проверка:** при тесте CRSF к ELRS TX модулю — если модуль не парсит правильно сформированные фреймы, и pinout верный, и GND общий, и polarity не инвертирована — добавить резистор и повторить.

### 2026-05-22 (late night) · GND через Dupont на header pin 6 OPi 5 Max — ненадёжно

В этой сессии continuity OPi pin 6 ↔ socket pin 4 не пищала через стандартный Dupont-коннектор на pin 6 header'а, несмотря на то что обе крайние точки = GND и провод цел. Перепайка чёрного провода напрямую на плату Pi (минуя Dupont) решила проблему.

**Правило:** для GND-связи между OPi 5 Max и внешним устройством — не полагаться только на Dupont-коннектор на header pin 6. Альтернативы: использовать другой GND pin (9, 14, 20, 25, 30, 34, 39), припаять напрямую к точке GND plane на плате Pi, или сменить Dupont на качественный с гарантированно хорошим обжимом.

**Проверка:** в continuity-тесте измерять "от пина header'а до металла другого конца провода", а не "от жилки до жилки". Это покрывает контакт Dupont↔header.
```

---

## 11. 📌 Шаблон первого сообщения в новом чате

```
Продолжаем bringup u1u2-bridge. Прикладываю handoff
2026-05-22-late-night-firmware-master.md.

TL;DR:
- GND починен обходом Dupont (черный припаян напрямую к плате Pi)
- Continuity всех цепей подтверждена
- Сервис crsf-bridge@tx1 stopped + disabled
- Тест "WiFi не появляется" провалился — модуль уходит в WiFi через 30
  сек, CRSF до парсера не доходит
- Firmware модуля = master (91b1ee), не stable release
- Pinout правильный: CRSF Serial RX=13 TX=13 (single pin half-duplex)
  = JR-bay socket pin 5 (куда и припаяно)
- Три оставшиеся гипотезы: drive contention (резистор 1k-4.7k нужен),
  master firmware bug, или модуль повреждён

План:
1. Handset test — вставить модуль в TX12, проверить базовую
   функциональность (5-10 мин). Это разделит "модуль OK" от
   "модуль сломан".
2. Если модуль OK — резистор 1k-4.7k последовательно с OPi TX.
3. Если резистор не помог — DEVICE_PING фреймы или перепрошивка
   на stable.

Прошу прочитать в репо: CLAUDE.md, docs/wiring-opi5max.md, все
handoff'ы в docs/handoff/.

SSH-адреса:
  u2-Pi:  ssh ubuntu@10.8.0.7
  u1-Pi:  ssh ubuntu@10.8.0.6

Перед стартом новой сессии у меня есть в наличии (отвечу когда
спросишь): [резистор 1k или 4.7k да/нет, handset TX12 да/нет].
```

---

## 12. 🎒 Что не входит в этот handoff (для полноты)

- **Состояние u1-Pi** — в этой сессии не трогалось.
- **8-pin разъём модель** — не определена.
- **Видео pipeline** — не тестировалось.
- **Telemetry/back-channel** — пока без синего провода.
- **CTRL-канал** второй CRSF — после первого.
- **CP2102 USB-Serial на Windows (Error 31)** — отложено.

---

## 13. 🧠 Предпочтения пользователя (соблюдать)

1. Claude Code установлен в `C:\Users\ARDOR\Documents\Projects\u1u2-bridge`. Анонсировать заранее при переходе к работе с репо/git.
2. Длинный чат → handoff + новый чат заранее.
3. Дозировать информацию (один блок за раз).
4. При шагах с программой — расписать пошагово.
5. По-русски.
6. Не полагаться на LED-индикацию (цветовое восприятие).
