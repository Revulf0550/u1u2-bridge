# Архив уроков u1u2-bridge — вынесено из CLAUDE.md (закрытые/исторические инциденты). Новые сверху. Живые правила остаются в CLAUDE.md.

### 2026-05-25 · Pinout JR-bay Boxer ELRS — стандартный, но pin 3 опасен

При подготовке к распайке переходника пульт→u1 измерили JR-bay мультиметром: p1=3.3 В (PPM idle high), p2=0 В (не разведён), **p3=7.8 В (VBAT, спалит UART)**, p4=0 В (GND), p5=0.27 В (S.PORT idle low). Pinout стандартный, ничего нестандартного у Boxer ELRS нет.

**Правило:** при работе с любыми JR-bay коннекторами (даже стандартными) — обязательно проверять мультиметром каждый pin **до** подключения к Pi/UART. Pin 3 VBAT на разных пультах может быть 6–8.4 В — гарантированно сжигает 3.3 В UART, если перепутать.

**Проверка:** перед подключением — мультиметр в режим напряжения, измерить каждый pin относительно pin 4 (GND) с включённым пультом. Сверить с datasheet модели.

---

### 2026-05-24 · ELRS таймаут config mode — 30-60 секунд без валидного CRSF

После подачи питания ELRS Ranger Micro ждёт ~30-60 секунд валидный CRSF на UART. Если за это окно не получил — автоматически поднимает WiFi-сеть `ExpressLRS TX` для конфигурации. Это тот самый сигнал «CRSF не валидируется».

Окно теста для отладки UART к модулю: после reset питания у тебя ~30 секунд чтобы запустить стрим. Если не успел — модуль уйдёт в config, надо передёргивать питание (red wire к pin 3 модуля на 3 секунды).

**Правило:** тестовый процесс UART-моста к ELRS — это «передёрнул питание модуля → быстро стартанул стрим → жди 2 минуты для подтверждения». Если WiFi не появилась — успех.

**Проверка:** телефон с открытым списком WiFi-сетей рядом во время теста.

---

### 2026-05-24 · /tmp на u2-pi — tmpfs, очищается при ребуте

Тестовые скрипты, сохранённые в `/tmp/` через heredoc (как привычно делать при отладке), пропадают после каждой перезагрузки. Постоянное место для hardware-тестов на u2-pi — `~/hardware/` (= `/home/ubuntu/hardware/`). Не требует sudo, переживает ребуты.

**Правило:** тестовые скрипты, которые могут понадобиться повторно, не хранить в `/tmp/`. Сохранять в репозитории (`hardware/`) и деплоить на Pi через `scp` в `~/hardware/`.

**Проверка:** после ребута Pi — `ls ~/hardware/` должен показывать сохранённые скрипты.

---

### 2026-05-24 · CRSF 420k через single-NPN inverter не работает (storage time)

Hardware-инвертор на одиночном BC548 для UART_INVERTED не валидируется ESP32 в ELRS Ranger Micro при 420000 baud. Симптом: модуль уходит в config mode (поднимает WiFi `ExpressLRS TX`) через ~30-60 секунд после старта стрима. DC уровни корректные (B=2.8V, C=0.2V — точно как теоретически), но edges на 420k размытые из-за storage time транзистора в hard saturation. Расчёт: R1=2.2kΩ даёт ib=1.2mA при необходимом 3.5µA — over-drive в 340x → storage time вырастает с 225ns datasheet до 1-2µs, что 40-80% bit time 2.38µs на 420k.

**Правило:** для UART > 230400 baud не использовать single-NPN inverter без speed-up cap или Baker clamp. Для дальнейших CRSF-каналов сразу брать 74HC14N или другой CMOS-инвертор.

**Проверка:** статический замер DC inversion ничего не докажет на скоростях. Нужен либо осциллограф, либо end-to-end test с реальным потребителем (ESP32 UART receiver валидирует фреймы).

---

### 2026-05-24 · 74HC14N Schmitt-trigger как фикс UART invert на 420k

Замена single-NPN на SN74HC14N (hex Schmitt-trigger inverter, DIP-14) полностью решила проблему. ESP32 валидирует CRSF, модуль остаётся в operating mode, бинд с дроном проходит. Использован один gate (pin 1 IN / pin 2 OUT), остальные 5 input pins (3, 5, 9, 11, 13) обязательно стянуты на GND через одну перемычку, output pins (4, 6, 8, 10, 12) — NC.

Schmitt-trigger вариант выбран вместо обычного 74HC04, потому что гистерезис на входе (~0.4-1V) дополнительно чистит фронты от RK3588 UART и от паразитной capacitance проводов.

Финальная схема в `docs/inverter-schematic.md`.

**Правило:** для любого UART invert на скоростях ≥ 230400 — сразу 74HC14 (Schmitt). Не экономить на CMOS-IC ради «одного транзистора».

**Проверка:** smoke-test через `hardware/crsf_smoke_test.py`. Критерий: 2+ минуты стрима без появления `ExpressLRS TX` WiFi сети.

---

### 2026-05-24 · UART_INVERTED в ELRS — ESP32-only hardware feature

Опция `UART_INVERTED` в ExpressLRS firmware работает ИСКЛЮЧИТЕЛЬНО на ESP32-based TX-модулях. Это build-time define, который конфигурирует hardware UART periphery ESP32 для приёма inverted-level сигнала — на чипе. Не runtime-видимая опция, в WebUI её обычно нет.

Для не-ESP32 модулей (STM32-based и т.д.) UART_INVERTED игнорируется, нужно делать hardware inversion снаружи.

**Правило:** перед попыткой UART-связи с ELRS-модулем проверять, какой у него MCU и какая прошивка. Если ESP32 + master firmware с UART_INVERTED=on → нужен hardware inverter ИЛИ пересборка прошивки с UART_INVERTED=off.

**Альтернатива hardware:** перепрошить ELRS через Configurator с снятой галкой "Invert TX". Тогда инвертор не нужен. В нашем проекте выбрали hardware-путь чтобы не трогать прошивку модуля.

---

### 2026-05-22 (late night) · WebUI ELRS — это одна прокручиваемая страница, не несколько

В master-сборках ELRS (по крайней мере на commit 91b1ee) WebUI `http://10.0.0.1/` не имеет отдельной hardware-страницы. Есть три вкладки: **OPTIONS, WIFI, UPDATE**. Hardware-секция (CRSF Serial Pins, Radio Chip, Radio Power, и т.д.) находится **внизу OPTIONS-страницы** при прокрутке. Также там есть кнопки `UPLOAD target configuration` и `SAVE TARGET CONFIGURATION` для изменения pinout прямо через web.

**Правило:** при работе с WebUI ELRS — прокрутить OPTIONS-страницу до конца. Не ограничиваться видимой верхней частью.

**Проверка:** на странице должна быть видна секция "CRSF Serial Pins" с pin RX и pin TX.

---

### 2026-05-22 (late night) · Версия firmware ELRS — проверять первым делом

Шапка WebUI показывает версию firmware в формате `Firmware Rev. {branch} ({hash}) {band}`. Если branch = `master` — это самосборка с development ветки, **не stable release**. Поведение может отличаться от документированного.

**Правило:** перед любыми тестами CRSF к модулю — посмотреть версию firmware в шапке WebUI. Если master или git-hash — относиться к модулю как к unknown firmware и иметь в виду возможные regressions.

**Проверка:** Firmware Rev. на главной странице WebUI должна показывать понятную версию (3.x.x) для stable.

---

### 2026-05-22 (late night) · Drive contention в half-duplex single-pin CRSF — потенциальный блокер

ELRS TX модули обычно используют CRSF UART как half-duplex single-pin (RX pin == TX pin в hardware config). ESP32 переключает direction GPIO между приёмом команд и отправкой telemetry. Если подключить к этому пину OPi UART7 в стандартном push-pull режиме, который **непрерывно** драйвит линию — будут drive collisions с ESP32 telemetry output.

**Правило:** при подключении OPi (или любого Linux SBC) UART к single-pin half-duplex CRSF — ставить **резистор 1кΩ-4.7кΩ последовательно с TX** SBC. Это делает SBC "слабым" источником, ESP32 telemetry легко пересиливает.

**Проверка:** при тесте CRSF к ELRS TX модулю — если модуль не парсит правильно сформированные фреймы, и pinout верный, и GND общий, и polarity не инвертирована — добавить резистор и повторить.

---

### 2026-05-22 (late night) · GND через Dupont на header pin 6 OPi 5 Max — ненадёжно

В этой сессии continuity OPi pin 6 ↔ socket pin 4 не пищала через стандартный Dupont-коннектор на pin 6 header'а, несмотря на то что обе крайние точки = GND и провод цел. Перепайка чёрного провода напрямую на плату Pi (минуя Dupont) решила проблему.

**Правило:** для GND-связи между OPi 5 Max и внешним устройством — не полагаться только на Dupont-коннектор на header pin 6. Альтернативы: использовать другой GND pin (9, 14, 20, 25, 30, 34, 39), припаять напрямую к точке GND plane на плате Pi, или сменить Dupont на качественный с гарантированно хорошим обжимом.

**Проверка:** в continuity-тесте измерять "от пина header'а до металла другого конца провода", а не "от жилки до жилки". Это покрывает контакт Dupont↔header.

---

### 2026-05-22 (evening) · Не верить шёлкографии PCB без проверки документацией

На плате Ranger Micro есть сервисные пятаки `32_TX` / `32_RX`. По логике (имя + наличие в открытом доступе) они выглядят как «чистый неинвертированный UART к ESP32». На деле — оказалось, что ELRS firmware настраивает этот UART в режим `UART_INVERTED=true` (default для совместимости с радиостанциями типа FrSky QX7, TBS Tango 2, RadioMaster TX16S). Шёлкография говорит «вот UART ESP32», но **не говорит** «инвертированный или нет». Результат — припаялись правильно (electrically доказано через TX-spam), но LED модуля не реагирует на наш неинвертированный CRSF.

**Правило:** перед пайкой к сервисным пятакам ELRS / TBS Crossfire / R9 и других open-source RF-модулей — обязательно проверить в target-файле прошивки (на GitHub) что firmware ожидает на этом UART: invert или нет, full-duplex или half. То же касается debug-vs-CRSF UART: пятак может быть `serial_rx`/`serial_tx` для CRSF, а может быть UART0 ESP32 (общий с CP2102 для прошивки).

**Проверка:** GitHub-путь `ExpressLRS/ExpressLRS/src/hardware/TX/Radiomaster_<Module>_TX/` — там JSON/`.h` с `serial_rx`, `serial_tx`, `uart_invert`, `serial_half_duplex`. Полный контекст блокера — `docs/handoff/2026-05-22-evening-uart-invert-blocker.md`.

---

### 2026-05-22 (evening) · TX-spam + мультиметр DC = быстрый тест целостности 3.3V UART

Когда нужно проверить «доходит ли сигнал OPi UART до пятака приёмника после пайки» без осциллографа и без ответа от противоположной стороны: послать с OPi непрерывный байт-паттерн с большим количеством переходов (`b'\xAA' * 4096` в цикле write+flush), мерять DC-напряжение на целевом пятаке относительно GND, сравнить idle (без write) и spam (во время write). На 3.3V логике idle UART ≈ 3.2–3.3V (linе in idle high), на быстро меняющемся сигнале мультиметр DC показывает 0–2V среднее (зависит от duty cycle).

**Правило:** разница > 1V между idle и spam = OPi TX драйвит линию, провод имеет электрический контакт до пятака. Это НЕ подтверждает что сигнал корректно декодируется на той стороне (см. UART_INVERTED-блокер) — только физическую связь. Дешёвый sanity-test перед тем, как лезть в логические причины «нет ответа».

**Проверка:** одна цифра idle, одна spam, разница в одной точке (32_RX или RX-сторона цепи). Если разница близка к 0 — провод оборван, плохая пайка или GPIO не драйвит (sysfs ноды не активны, overlay не загрузился).

---

### 2026-05-22 (evening) · `stty` не поддерживает нестандартные baudrate (420 000 для CRSF)

CRSF использует 420 000 бод — нестандартная скорость, не входящая в POSIX-таблицу `stty`. Стандартный `stty -F /dev/ttyS7 420000 raw -echo` падает с `invalid argument '420000'` и не настраивает порт. Linux в принципе поддерживает arbitrary baudrate через `termios2` ioctl, но `stty` им не пользуется.

**Правило:** для нестандартных baudrate (включая 420k CRSF) использовать pyserial — она внутри вызывает `termios2`. `serial.Serial(port, 420000)` работает там, где `stty 420000` падает.

**Проверка:** `python3 -c "import serial; s=serial.Serial('/dev/ttyS7', 420000); print('ok'); s.close()"` печатает `ok` без exception.

---

### 2026-05-22 (evening) · `sudo python3 -c "..."` + запись в `/tmp` = PermissionError

При попытке `sudo python3 -c "...open('/tmp/file.bin','wb').write(data)"` падает `PermissionError: [Errno 13] Permission denied: '/tmp/file.bin'` даже когда процесс под root. Причина — AppArmor sandbox профиль для Python на Ubuntu 24.04 от joshua-riek (snap или дистрибутивный hardening): запись в `/tmp` из sandboxed Python заблокирована, несмотря на root-uid.

**Правило:** при необходимости сохранить бинарь через `sudo python3 -c "..."` — писать в `sys.stdout.buffer.write(data)` внутри Python, redirect `> ~/file.bin` снаружи sudo. Тогда файл создаёт shell от имени пользователя, AppArmor не вмешивается.

**Проверка:** `sudo python3 -c "import sys; sys.stdout.buffer.write(b'test')" > ~/test.bin && ls -la ~/test.bin` — файл создан с UID пользователя, не root.

---

### 2026-05-22 (late) · UART7 на Pi 5 Max архитектурно занят Bluetooth (AP6611)

После полного штатного reboot с overlay m1 loopback на пинах 29/38 показывает `in_waiting=0`, хотя `pinmux-pins` подтверждает привязку и `/dev/ttyS7` пишется без timeout. Причина: on-board Bluetooth-чип AP6611 штатно подключён к UART7 (m0-раскладка), служба `ap6611s-bluetooth.service` поднимает `brcm_patchram_plus` и держит `/dev/ttyS7` открытым. Overlay m1 переключает physical pinmux на пины 29/38, BT-чип становится недоступен, но патчер зависает и продолжает захват порта — наш Python-код тоже открывает порт, два клиента на одном UART-контроллере → конфликт. Race condition: первый тест после bringup может пройти (BT не успел захватить), штатный ребут — нет.

**Правило:** на платах RK3588 с on-board BT через UART (Pi 5 Max, Plus и подобных), прежде чем переназначать тот же UART через overlay — обязательно `systemctl disable --now + mask` для `bluetooth.service` и платформенного `*-bluetooth.service` (на Pi 5 Max — `ap6611s-bluetooth.service`).

**Проверка:** `sudo lsof /dev/ttyS7` сразу после ребута возвращает пусто; `systemctl is-active bluetooth.service ap6611s-bluetooth.service` показывает `inactive`. Полный контекст и команды восстановления — `docs/handoff/2026-05-22-late-uart7-bringup-complete.md`.

---

### 2026-05-22 (late) · `_BOOT_PATH=""` на joshua-riek ломает относительный `U_BOOT_FDT_OVERLAYS_DIR`

При попытке прописать persistent overlay через `U_BOOT_FDT_OVERLAYS_DIR="overlays/"` в `/etc/default/u-boot` (как в дефолтном шаблоне) скрипт `u-boot-update` тихо пропускает `fdtoverlays` — нет ошибки, в `extlinux.conf` остаётся только `fdtdir`. Причина: на joshua-riek образах `/boot` лежит на той же FS что и `/` (нет отдельной партиции), поэтому `u-boot-update` ставит `_BOOT_PATH=""`, и проверка `[ -f "${_BOOT_PATH}/${overlays_dir}/${dtbo}" ]` превращается в `[ -f "/overlays/..." ]` — путь от корня FS, где dtbo нет.

**Правило:** на joshua-riek (и любом образе с merged /boot+/) использовать **абсолютный** `U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"` и `U_BOOT_FDT_OVERLAYS` относительно `<kernel-version>/` подкаталога — тогда `u-boot-update` подставит актуальный `_VERSION` и dtbo обновится автоматически при апгрейде ядра.

**Проверка:** после `sudo u-boot-update` команда `grep fdtoverlays /boot/extlinux/extlinux.conf` под label `l0` показывает строку с абсолютным путём `/lib/firmware/<kernel>/.../*.dtbo`. Пусто → путь относительный или dtbo нет в `/lib/firmware/<kernel>/`. Полный разбор и TL;DR-команды — `docs/handoff/2026-05-22-late-uart7-bringup-complete.md`.

---

### 2026-05-22 (late) · Dupont-перемычки: подозревай контакт ПЕРВЫМ при странном loopback

В сессии bringup UART7 два независимых случая ложно-отрицательного loopback (overlay m2 на пинах 24/26 и overlay m1 на 29/38) каждый раз заставляли диагностировать программу — pinmux, скорости, права, race conditions — теряя часы. В обоих случаях виновник оказывался в перемычке: дешёвые Dupont female-female имеют плохой обжим, контакт пропадает при сгибе. Признаки: `in_waiting >> ожидание` + мусорные байты = RX плавает, ловит наводку 50 Гц; `in_waiting=0` полная тишина = TX в idle HIGH, RX тоже HIGH, наводок нет.

**Правило:** если loopback не проходит — **первое подозрение перемычка**, не программа. Прежде чем лезть в pinmux/скорости/драйверы — проверить контакт визуально и заменить перемычку на другую.

**Проверка:** "тест пальцем" — снять перемычку, открыть UART на пассивное чтение, прикоснуться пальцем к RX-пину. Живой RX за 5 секунд набирает десятки/сотни байт мусора от наводки 50 Гц через тело-антенну. Если 0 — проблема в программе или железе платы, не в перемычке.

---

### 2026-05-22 · UART7 на Orange Pi 5 Max работает через overlay m1, не m2

На Orange Pi 5 Max (kernel 6.1.0-1025-rockchip, joshua-riek Ubuntu 24.04) overlay `rk3588-uart7-m2.dtbo` активирует ноду `serial@feba0000`, но RX-пин остаётся `GPIO UNCLAIMED` — loopback не проходит ни на 420 000, ни на 9600 бод. Рабочий вариант — `rk3588-uart7-m1.dtbo`, физические пины 29 (TX) и 38 (RX), `pinmux-pins` подтверждает привязку `gpio3-16/17`. Подключение overlay через `U_BOOT_FDT_OVERLAYS` в `/etc/default/u-boot` молча игнорируется текущей версией `u-boot-menu`, пришлось править `/boot/extlinux/extlinux.conf` руками (правка помечена как auto-generated — открытый риск потери при обновлении ядра, см. Chunk D в HANDOFF).

**Правило:** для активации периферии RK3588 через device-tree overlay не доверять номерам пинов из стороннего туториала — всегда верифицировать через `sudo grep -ri uart7 /sys/kernel/debug/pinctrl/ | grep pinmux-pins` после загрузки и через loopback на 420k бод до пайки.

**Проверка:** `python3 -c 'import serial,time; s=serial.Serial("/dev/ttyS7",420000,timeout=2,write_timeout=2); s.reset_input_buffer(); s.write(b"TEST"); s.flush(); time.sleep(0.1); print(s.read(s.in_waiting))'` на u2-Pi с перемычкой 29↔38 должен вернуть `b'TEST'` и `in_waiting=4`.

---

### 2026-05-19 · Распиновка платы по фото без прозвонки

В сессии 2026-05-18 распиновку `video_out` на плате У-устройства зафиксировали в `docs/wiring.md` по одному фото без чёткой маркировки: белый=signal, жёлтый=shield. При пайке u1-переходника 2026-05-19 пятаки пересняли крупно, увидели на плате маркировку «+» (нижний пятак, жёлтый) и «−» (верхний пятак, белый), прозвонили мультиметром — оказалось обратное: **жёлтый=сигнал (CVBS), белый=GND**. `docs/wiring.md`, `docs/HANDOFF.md §7.4` и схема переходника исправлены. Сам спаянный переходник был сделан уже по правильной версии — юзер до коммита заметил расхождение по фото с маркировкой, пайки не пропали зря.

**Правило:** маркировка платы по одному фото без прозвонки — не источник истины для документа. Перед фиксацией distinct пин↔цвет↔сигнал в `docs/wiring.md` подтверждать мультиметром по конкретным пятакам, либо явно помечать запись `tentative, pending board check`.

**Проверка:** в commit-message правок `docs/wiring.md`, меняющих пин/цвет/сигнал, упоминать источник истины — `verified by continuity` или `verified by board silkscreen + photo + continuity`. Если правка идёт без свежей прозвонки — `tentative, pending board check`.

---

### 2026-05-18 (вечер) · Bench-инструмент эмулировал сценарий, которого в production нет

`bench/loopback.py` написан для закрытия §7.1 HANDOFF («auto-direction RS485 на 420k бод»). Архитектура: один Python-процесс, два потока, два USB-RS485 адаптера на одной Pi, три перемычки A↔A/B↔B/GND↔GND, pinger шлёт фрейм и ждёт echo. После 4 итераций фикса (`207ff66` adaptive deadline, `397ce65` cap+warning+flush, `060e52f` flush rollback, `23a994e` margin 2→20 мс) bench всё ещё давал нестабильные результаты — `echoer.bytes_received` скакал от 22 до 2073 байт между прогонами без изменений в коде/железе. В этот момент сделали raw тест без bench: `stty raw -echo` + `printf` 1000 байт в одном окне, `cat` в другом, 6 прогонов в обе стороны → **6/6 ровно 1000/1000 байт без потерь** на 1200 бод. Физика жива.

Только тогда увидели несоответствие: bench тестирует bidirectional ping-pong на одной RS485 шине через два адаптера на одной Pi. В production такого нет — `crsf_bridge.py` делает one-way streaming в каждую сторону (на u2-pi: ELRS Tx → Waveshare → bridge → UDP; на u1-pi: UDP → bridge → Waveshare → П1), между u1 и u2 IP-сеть, не общая шина. Auto-direction Waveshare на 420k в **одну** сторону — типичный CRSF use case, проверено индустрией. Bidirectional ping-pong через одну шину с двумя адаптерами — отдельный сценарий, и его нестабильность не блокирует production CRSF flow. 4 итерации фикса искали баги в скрипте, который мерил неактуальную для проекта нагрузку.

**Правило:** перед инвестицией в bench-инструмент явно описать (в module docstring): какой production data-flow он эмулирует и в чём отклонения. Если bench меряет нагрузку, которой в production нет — его результаты не могут служить gate-criterion для production-кода. Если хочется быть совсем уверенным в физике — параллельно с написанием скрипта сделать raw `stty` + `cat`/`printf` тест, это 30 секунд и снимает целый класс «призраков физики».

**Проверка:** в module-level docstring каждого `bench/*` скрипта должна быть секция «Соответствие production» с явным описанием отличий от реального flow. Если отличия есть и влияют на результат — секция «Limitations» с warning'ом (см. `bench/loopback.py` после `23a994e` как эталон).

---

### 2026-05-18 · scp с Windows: путаница окон между PowerShell и SSH-сессией

При попытке скопировать конфиг с NSU-pc на Pi запустил `scp C:\path\to\file.conf ubuntu@host:~/...` в терминале, где приглашение было `ubuntu@u1-pi:~$` (то есть внутри активной SSH-сессии). Bash увидел `C:\...` как удалённый-формат `<host>:<path>` из-за двоеточия, попытался открыть SSH на хост `C`, упал с `ssh: Could not resolve hostname c`. Повторял два раза, прежде чем понял, что окно не то. Та же ошибка ловится и для `Get-ChildItem`/`Copy-Item` в SSH-сессии, и для `nano`/`cat` Linux-команд в PowerShell.

**Правило:** scp/rsync с Windows-машины — ТОЛЬКО из локального PowerShell (приглашение `PS C:\...>`), никогда из SSH-сессии. При выдаче таких команд в мануале/чате — рядом явно «**в PowerShell**» или «**на Pi**». Перед каждым `scp` смотреть на префикс приглашения: `PS ` → можно, `user@host:~$` → открыть новое локальное PowerShell-окно.

**Проверка:** мнемоника на свою сторону — «scp идёт ОТ Windows К Linux, значит запускается ОТ Windows». Если ошибка `Could not resolve hostname c` (или любая односимвольная буква) при scp — это 100% знак, что путь начался с буквы диска и запущен из bash.

---
### 2026-05-18 · CRLF в shebang ломает запуск bash-скрипта на Linux после `git pull`

После `git pull` на u2-pi `./install.sh` не стартовал: `bash: ./install.sh: /bin/bash^M: bad interpreter: No such file or directory`. Причина: репо редактируется на Windows без `.gitattributes`, git хранил/чекаутил `install.sh` с CRLF, на Linux ядро при exec'е shebang-строки видит `#!/bin/bash\r` и ищет интерпретатор `/bin/bash^M` (которого нет). Разово лечилось `sed -i 's/\r$//' install.sh && chmod +x install.sh`, окончательно — `.gitattributes` с явными правилами EOL.

**Правило:** в любом репо, который редактируется на Windows и исполняется на Linux — обязателен `.gitattributes` с явным `text eol=lf` для shell/python и `text eol=crlf` для PowerShell. На `core.autocrlf` пользователя не полагаться (у каждого свой). Если файл закоммичен до добавления `.gitattributes` с неправильным EOL — `git add --renormalize . && git commit`.

**Проверка:** на Linux после `git pull` — `file install.sh` показывает `Bourne-Again shell script, ASCII text executable` БЕЗ суффикса `with CRLF line terminators`. Регрессия: `head -1 install.sh | xxd | grep -q '0d 0a'` должно ничего не вернуть (нет CRLF в первой строке).

---

### 2026-05-18 · wg-easy дефолт `AllowedIPs=0.0.0.0/0` на Windows-клиенте ломает локалку

Импорт сгенерированного wg-easy конфига в WireGuard for Windows (NSU-pc, peer `10.8.0.5`): дефолтный `AllowedIPs = 0.0.0.0/0` создал второй default route через туннель, локальная сеть и обычный интернет отвалились (весь трафик ушёл на VPS NL). Симметрично уроку от 2026-05-18 про Pi-клиент: дефолт wg-easy одинаково небезопасен с любой стороны, не только на Pi.

**Правило:** ЛЮБОЙ импортированный из wg-easy конфиг (Pi, Windows, Android — без разницы) править вручную перед подключением: `AllowedIPs = 10.8.0.0/24` (только VPN-подсеть), `PersistentKeepalive = 15`. Никогда не подключаться "из коробки".

**Проверка:** на Windows после подключения — `route print -4 | findstr "  0.0.0.0  "` должен показывать default route на физический gateway, не на WG-интерфейс. На Linux — `ip route show default` не должен указывать на `wg0`. Универсально: `wg show wg0 allowed-ips` — только `10.8.0.0/24`.

---

### 2026-05-18 · Pi 5 Max + joshua-riek: пустой SPI + только NVMe → splash виснет

Первая попытка загрузить Orange Pi 5 Max с NVMe (Ubuntu 24.04 от joshua-riek) висла на splash "Orange Pi" — Linux не догружался. Причина: SPL на NVMe не способен догрузить Linux без U-Boot в SPI — PCIe инициализируется именно там, а из коробки на Pi 5 Max SPI пустой. Решение: сначала загрузиться с SD с той же прошивкой, выполнить `sudo u-boot-install-mtd`, вынуть SD и грузиться с NVMe.

**Правило:** на Pi 5 Max (RK3588) при NVMe-only установке — обязательно сначала прошить SPI U-Boot'ом через SD + `u-boot-install-mtd`. Голый NVMe без U-Boot в SPI грузиться не может (PCIe инициализируется из SPI).

**Проверка:** после `u-boot-install-mtd` — `sudo dd if=/dev/mtd0 bs=1M count=16 status=none | md5sum` совпадает с MD5 исходного образа U-Boot (см. также соседний урок про Rockchip SPI offset).

---

### 2026-05-18 · Rockchip SPI: первые 32K служебные, реальный idbloader на 0x8000

При проверке прошивки SPI команда `head -c 16 /dev/mtd0` возвращала нули — выглядело как пустая/битая прошивка. На самом деле первые 32K на Rockchip SPI — служебная область, реальный idbloader начинается с offset `0x8000` с заголовком `RKNS`.

**Правило:** не делать вывод о целостности Rockchip SPI flash по первым байтам — нули в начале это нормально. Проверять MD5 целиком (`md5sum file.img` vs `sudo dd if=/dev/mtd0 bs=1M count=16 | md5sum`, `count` по реальному размеру SPI flash).

**Проверка:** обе хэш-суммы должны совпадать. Не совпадают — перепрошить через `u-boot-install-mtd`. Заодно валидировать header: `sudo dd if=/dev/mtd0 bs=1 skip=32768 count=4 status=none | xxd` должно показать `RKNS`.

---

### 2026-05-18 · wg-easy дефолты клиентского пира небезопасны для нашего сценария

При генерации клиентского конфига в веб-UI wg-easy по умолчанию вписывается `AllowedIPs = 0.0.0.0/0` и `PersistentKeepalive = 0`. Для нашего сценария (Orange Pi как обычный пир в /24 подсети моста, не дефолт-роут всего трафика) `0.0.0.0/0` отправляет в туннель **весь** трафик — ломает доступ к локальной сети и CPE710. `PersistentKeepalive = 0` отключает keepalive — NAT-таблица на пути за 60–180 секунд протухает, туннель тихо перестаёт работать без явной ошибки.

**Правило:** после скачивания конфига из wg-easy всегда править вручную: `AllowedIPs = 10.8.0.0/24` (или нужная подсеть VPN-моста, без `0.0.0.0/0`) и `PersistentKeepalive = 15`. Дефолтам wg-easy для этого проекта не доверять.

**Проверка:** `sudo wg show wg0 allowed-ips` — только VPN-подсеть, не `0.0.0.0/0`. После 60+ секунд молчания `ping` через туннель остаётся рабочим — keepalive держит NAT.

---

### 2026-05-18 · Orange Pi 5 Max имеет один 2.5GbE, не два

При планировании сетевой схемы предполагал у Pi 5 Max два Ethernet-порта (путал с Pi 5 Plus). На самом деле у Pi 5 Max — **один** 2.5GbE с именем `enP3p49s0` (на joshua-riek 24.04). План разделять трафик CPE710 / management по разным портам — невозможен на этой плате.

**Правило:** для Pi 5 Max закладывать один сетевой интерфейс. Перед редактированием netplan / `install.sh` IFACE-логики — всегда сверяться с `ip -br link`, а не с памятью про "Pi 5 имеет столько-то портов". Имя интерфейса на joshua-riek меняется от модели платы (`end0` на Pi 5, `enP3p49s0` на Pi 5 Max).

**Проверка:** `ip -br link | awk '$1 != "lo"'` на u2-pi показывает один интерфейс `enP3p49s0`. `install.sh` определяет IFACE автоматически (`ip -br link | awk '$2 == "UP"'`), переопределение — через `IFACE=...` env.

---

### 2026-05-18 · Waveshare USB-TO-RS485 (B) на CH343G → /dev/ttyACMx, не /dev/ttyUSBx

При подключении Waveshare USB-TO-RS485 (B) к Orange Pi 5 Max (Ubuntu 24.04) адаптер был распознан как USB CDC ACM device (драйвер `cdc_acm`), пришёл как `/dev/ttyACM0`, а не `/dev/ttyUSB0`. Vendor:Product = `1a86:55d3` (WCH CH343G). Прежние udev-правила и env-файлы `install.sh` ожидали `ttyUSB*` под CP2102N `10c4:ea60` — на CH343G не сработают вообще.

**Правило:** для CH343G использовать драйвер `cdc_acm` и имена `/dev/ttyACMx`; udev `SYMLINK+="ttyACM-CRSFx"`, env `SERIAL_DEV=/dev/ttyACM-CRSFx`. `ttyUSB*` валидно только для CP210x/CH340G — это другие чипы. При смене модели адаптера всегда сверяться с `dmesg` / `ls /dev/tty*`, не копировать имена из старых правил.

**Проверка:** после подключения адаптера — `ls /dev/ttyACM*` и `udevadm info -q property /dev/ttyACM0 | grep -E 'ID_USB_DRIVER|ID_VENDOR_ID|ID_MODEL_ID'` (ожидаем `cdc_acm`, `1a86`, `55d3`). Серийник конкретного адаптера на u2-pi — `5A98051690`. Пользователь должен быть в группе `dialout`: `groups ubuntu | grep -w dialout`.

---

### 2026-05-27 · CH340G c SerialNumber=0 — udev по серийнику невозможен

Конкретный экземпляр CH340G на u1-pi даёт `SerialNumber=0` в dmesg (`usb 1-1: New USB device strings: Mfr=0, Product=2, SerialNumber=0`). Это типичная картина для CH340G — серийник у этого чипа в EEPROM не программируется на заводе. Правило в HANDOFF `ATTRS{serial}=="REPLACE_WITH_SERIAL_1"` для такого устройства технически невозможно.

**Правило:** Перед написанием udev-правила всегда проверяй `udevadm info -a /dev/ttyUSB0 | grep -m1 'ATTRS{serial}'`. Если серийник пустой или "0" — используй `KERNELS=="X-Y"` (USB port path) или мигрируй на CH343G/CP2102N/FT232. Для одного USB-UART на хосте можно вообще обойтись `/dev/ttyUSB0` напрямую в env-файле, пока второго не появилось.

**Проверка:** `udevadm info -a /dev/ttyUSB0 | grep -m3 -E 'ATTRS\{(serial|idVendor|idProduct)\}'`.

---

### 2026-05-27 · stty в coreutils не поддерживает 420000 бод

`sudo stty -F /dev/ttyUSB0 raw 420000 -echo` → `stty: invalid argument '420000'`. Coreutils stty знает только POSIX-стандартные бод-рейты (до 4000000 в новых версиях, но дискретно — 9600, 19200, 38400, 57600, 115200, 230400, 460800, 500000, 576000, 921600, 1000000, 1152000, 1500000, 2000000, ...). 420000 — не в этом списке.

**Правило:** для нестандартных бод (CRSF 420000, S.Bus 100000 inverted, SBUS2 100000) — никогда не пытайся через `stty`. Используй pyserial (`serial.Serial('/dev/ttyUSBx', 420000)`) или termios2 `BOTHER` напрямую. Pyserial умеет любую кастомную скорость через `BOTHER` под капотом на Linux.

**Проверка одной строкой для снифа на любой нестандартной скорости:**
sudo python3 -c "
import serial, sys
sys.stdout.buffer.write(serial.Serial('/dev/ttyUSB0', 420000, timeout=3).read(500))
" | xxd | head -20

---

### 2026-05-13 · `PackageNotFoundError: u1u2-bridge` при `importlib.metadata.version()`

При планировании CLI-флага `--version` собирался использовать `importlib.metadata.version("u1u2-bridge")`, но проверка показала `PackageNotFoundError`: в `pyproject.toml` не было `[build-system]`, поэтому `uv sync` ставил только зависимости, а сам проект не устанавливался как distribution. Исправлено добавлением `[build-system] requires = ["hatchling"]` и `[tool.hatch.build.targets.wheel] packages = ["common"]`, после чего `uv sync` поставил `u1u2-bridge==0.1.0` editable.

**Правило:** перед использованием `importlib.metadata.*` (в коде или ещё на этапе плана) — однострочной проверкой убедиться, что пакет реально установлен в `.venv`. Если нет — сначала `[build-system]` + `uv sync`, либо предусмотреть `try/except PackageNotFoundError` с фолбэком.

**Проверка:** `uv run python -c "from importlib.metadata import version; print(version('u1u2-bridge'))"` должно печатать актуальную версию, не падать. Регрессионный тест: `tests/unit/test_crsf_bridge.py::TestGetVersion::test_returns_nonempty_string`.

---

### 2026-05-13 · `uv trampoline failed to canonicalize script path` после переезда проекта

При перемещении папки проекта с `Desktop\files\` в `Documents\Projects\` команда `mypy` упала с ошибкой *uv trampoline failed to canonicalize script path*. Причина — на Windows внутри `.venv\Scripts\` лежат тонкие .exe-трамплины (`mypy.exe`, `pytest.exe`, и т.д.), внутри которых **жёстко вшит абсолютный путь** к месту установки. После переезда они указывают на несуществующий путь.

**Правило:** при переносе папки проекта между директориями — сначала сносить `.venv` (`Remove-Item -Recurse -Force .venv`), затем пересоздавать через `uv sync --all-groups` в новом месте. Не пытаться "перенести" виртуальное окружение целиком.

**Проверка:** обязательный прогон `.\verify.ps1` сразу после переезда. Если красное — `.venv` поломан, пересоздать.

---

