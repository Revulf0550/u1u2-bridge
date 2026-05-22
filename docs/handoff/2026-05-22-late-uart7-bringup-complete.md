# Handoff: u1u2-bridge — UART7 bringup завершён (2026-05-22, late evening)

> Документ создан на breakpoint **после полного успеха** UART7 hardware bringup на u2-Pi. Перед новым чатом убедись, что прочитан `CLAUDE.md` и `docs/wiring-opi5max.md` в репо — они содержат коммит 07b0299 от 2026-05-22 (afternoon) с распиновкой и одним Lesson про m1 vs m2 overlay.

---

## ⚡ TL;DR — команды восстановления конфигурации u2-Pi

Если когда-то понадобится сделать UART7 с нуля на чистом образе joshua-riek 24.04 для Pi 5 Max, минимально достаточный набор:

```bash
# 1. Прописать persistent overlay через стандартный механизм u-boot-menu
sudo tee -a /etc/default/u-boot >/dev/null <<'EOF'

# UART7 на пинах 29/38 (TX/RX) для u1u2-bridge
U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"
U_BOOT_FDT_OVERLAYS="device-tree/rockchip/overlay/rk3588-uart7-m1.dtbo"
EOF
sudo u-boot-update

# 2. Освободить UART7 от Bluetooth-стека (BT в проекте не нужен)
sudo systemctl disable --now bluetooth.service ap6611s-bluetooth.service
sudo systemctl mask bluetooth.service ap6611s-bluetooth.service

# 3. Перезагрузка
sudo reboot
```

После этого `/dev/ttyS7` свободен на пинах 29 (TX) и 38 (RX), готов к подключению ELRS TX модуля или к loopback-тестам. Этот же набор должен попасть в `install.sh` для роли `u2` (см. "Приоритет 2" ниже).

---

## 🟢 Состояние u2-Pi (актуальная рабочая конфигурация)

UART7 работает на физических пинах **29 (TX)** и **38 (RX)** через overlay `rk3588-uart7-m1.dtbo`. Loopback на 420 000 бод проходит чисто, без мусорных байт.

### Что сделано на железе

1. **Overlay persistence через `/etc/default/u-boot`** (стандартный механизм, переживёт обновления ядра):
   ```
   U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"
   U_BOOT_FDT_OVERLAYS="device-tree/rockchip/overlay/rk3588-uart7-m1.dtbo"
   ```
   `sudo u-boot-update` после изменения сам генерирует правильный `fdtoverlays` в `/boot/extlinux/extlinux.conf`. Ручные правки `extlinux.conf` больше не нужны.

2. **Bluetooth-стек disabled + masked** (BT захватывал `/dev/ttyS7` через `brcm_patchram_plus`):
   ```
   sudo systemctl disable --now bluetooth.service
   sudo systemctl disable --now ap6611s-bluetooth.service
   sudo systemctl mask bluetooth.service
   sudo systemctl mask ap6611s-bluetooth.service
   ```

3. **Бэкапы** на u2-Pi (оставлены для отката, можно удалить когда уверены):
   - `/etc/default/u-boot.bak` — до правки
   - `/boot/extlinux/extlinux.conf.bak` — самый ранний бэкап
   - `/boot/extlinux/extlinux.conf.preuart` — до ручной правки
   - `/boot/extlinux/extlinux.conf.before-uboot-update` — перед последним u-boot-update

4. **Loopback-перемычка** между пинами 29 и 38 — **физически стоит**. Можно снять (она нужна была только для bringup-тестов) или оставить (не мешает, понадобится для бенч-тестов перед подключением ELRS).

---

## 🔴 Что обнаружено в этой сессии (новые уроки, не в репо)

### Lesson 1 — UART7 на Pi 5 Max архитектурно занят Bluetooth

**Симптом:** после полного штатного reboot с включённым overlay m1 loopback показывает `in_waiting=0`, хотя `pinmux-pins` подтверждает правильную привязку pin 112/113 к `uart7m1-xfer` и `/dev/ttyS7` пишется без timeout.

**Причина:** Orange Pi 5 Max имеет on-board Bluetooth модуль AP6611, который **штатно подключён к UART7** через m0-раскладку (pin 146 RTS и др.). Joshua-Riek образ запускает службу `ap6611s-bluetooth.service`, которая поднимает `brcm_patchram_plus` для загрузки прошивки в BT-чип. Эта утилита держит `/dev/ttyS7` открытым в ожидании ответа от чипа. Когда overlay m1 переключает физический pinmux на pin 29/38, BT-чип становится недоступен, но `brcm_patchram_plus` зависает в ожидании, продолжая держать порт. Наш Python-код тоже открывает `/dev/ttyS7` — два клиента на одном UART-контроллере, конфликт.

**Подтверждено независимыми источниками:**
- CNX Software (Pi 5 Max review): "Onboard WiFi 6E and Bluetooth 5.3 module (AP6611) using SDIO 3.0 for WiFi, UART and PCM for Bluetooth".
- Arch Linux ARM форум по Pi 5 Max + Joshua-Riek BSP: "On the Joshua's 6.1 BSP kernel, the bluetooth should work on the Orange Pi 5 Max. There's a specific commit to get the AP6611s working... You should be able to create the ap6611s-bluetooth.service in userspace".

**Правило:** на платах с on-board BT через UART (Pi 5 Max, Pi 5 Plus и подобных RK3588), прежде чем переназначать тот же UART через overlay, обязательно отключать BT-стек (`systemctl disable + mask` для `bluetooth.service` и платформенно-специфичного `*-bluetooth.service`). Иначе race condition: первый тест после bringup может пройти (BT ещё не успел захватить), но штатные ребуты будут проваливать loopback.

**Проверка:** `sudo lsof /dev/ttyS7` сразу после ребута должен возвращать пусто. Если есть `brcm_patchram_plus` — BT не отключён до конца.

### Lesson 2 — `_BOOT_PATH` пустая на joshua-riek (rootfs/boot не отдельная партиция)

**Симптом:** при попытке использовать `U_BOOT_FDT_OVERLAYS_DIR="overlays/"` (относительный путь, как ожидалось бы из дефолтного шаблона `/etc/default/u-boot`) скрипт `u-boot-update` не находит файл и тихо пропускает `fdtoverlays`, оставляя только `fdtdir`.

**Причина:** `u-boot-update` определяет, что `/boot` находится **на той же файловой системе что и `/`** (нет отдельной партиции `/boot`), и ставит `_BOOT_PATH=""`. Все пути в extlinux.conf пишутся абсолютно от корня FS. Проверка существования файла `[ -f "${_BOOT_PATH}/${overlays_dir}/${dtbo}" ]` превращается в `[ -f "/overlays/..." ]` — путь от корня FS, где наших файлов нет.

**Решение:** использовать **абсолютный путь** `U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"` и значение `U_BOOT_FDT_OVERLAYS` относительно `<kernel-version>/` подкаталога — тогда скрипт построит `/lib/firmware/<kernel>/<dtbo-path>`, что соответствует штатному расположению dtbo от пакета ядра.

**Бонус-эффект:** при обновлении ядра новый dtbo приходит в `/lib/firmware/<новое-ядро>/`, `_VERSION` подставляется автоматически, `fdtoverlays` обновляется в новом extlinux.conf без нашего участия. То есть persistence + auto-pick правильной версии dtbo бесплатно.

**Проверка:** после `sudo u-boot-update` команда `grep fdtoverlays /boot/extlinux/extlinux.conf` должна показать `fdtoverlays /lib/firmware/<kernel>/device-tree/rockchip/overlay/rk3588-uart7-m1.dtbo` под label `l0`.

### Lesson 3 — Dupont-перемычки: подозревай физический контакт ПЕРВЫМ при ложно-отрицательных loopback

**Симптом:** loopback-тест UART даёт неожиданный результат — либо `in_waiting` сильно больше отправленного (буфер мусором забит), либо `0` без касаний. Инстинктивно начинаешь подозревать программу: pinmux, скорость, права на устройство, конфликты драйверов, race conditions. Тратишь часы на разбирательство.

**Причина:** Dupont female-female перемычки из дешёвых наборов часто имеют брак — провод обжат внутри коннектора плохо, и контакт пропадает при малейшем сгибе. Также пины Pi не всегда плотно зажимают коннектор. Признаки разные:
- `in_waiting >> ожидание` + мусорные байты в RX = RX-пин плавает, ловит наводку 50 Гц от тела/сети.
- `in_waiting=0` (полная тишина) = один конец перемычки подключён к TX, второй болтается возле RX-пина (экранирует), TX в idle = HIGH, RX тоже HIGH, наводок нет.

**Правило:** **если loopback не проходит, первое подозрение — перемычка**. Прежде чем лезть в pinmux, скорости, драйверы — проверить контакт визуально (плотно ли сидят оба конца) и если есть возможность — поменять на другую перемычку. В нашей сессии два независимых случая (с overlay m2 на пинах 24/26 и с m1 на пинах 29/38) дали ложно-отрицательный результат именно из-за перемычки, мы каждый раз диагностировали программу первым.

**Проверка:** "тест пальцем" — снять перемычку, открыть UART на пассивное чтение, прикоснуться пальцем к RX-пину. Если RX живой — за 5 секунд должны прилететь десятки/сотни байт мусора от наводки 50 Гц через тело-антенну. Если 0 — проблема в программе/железе, не в перемычке.

---

## 📋 Состояние репо (что зафиксировано, что НЕТ)

### Зафиксировано в коммите 07b0299

- `docs/wiring-opi5max.md` — распиновка UART7 (pin 29 TX, pin 38 RX, overlay m1).
- `CLAUDE.md` — Lesson "UART7 на Orange Pi 5 Max работает через overlay m1, не m2".
- `docs/HANDOFF.md` — баннер про устаревший статус.

### НЕ зафиксировано (задачи для нового чата)

1. **Lesson 1 (BT-конфликт)** — добавить в `CLAUDE.md` Lessons.
2. **Lesson 2 (`_BOOT_PATH=""` на joshua-riek)** — добавить в `CLAUDE.md` Lessons.
3. **Lesson 3 (Dupont-перемычки — physical contact first)** — добавить в `CLAUDE.md` Lessons.
4. **`docs/wiring-opi5max.md` v3** — добавить notice про обязательное отключение BT перед UART7 loopback, закрыть "открытый вопрос про persistence", дописать третий абзац в "Историю". Готовая обновлённая версия прилагается к этому handoff'у — Claude Code должен заменить файл целиком.
5. **Сам этот handoff** — положить в репо как `docs/handoff/2026-05-22-late-uart7-bringup-complete.md`. Это полезно: история проекта не только в чатах, но и в git, следующий разработчик через месяцы сможет посмотреть как мы добрались до текущей конфигурации.
6. **`install.sh` для роли `u2` (новые шаги bringup)** — см. "Приоритет 2" ниже.
7. **Тесты:** unit-тесты для нового скрипта `setup_uart.sh` (если будет отдельный) с моками.
8. **`docs/DEPLOYMENT.md`:** упомянуть требование отсутствия BT-нужд на u2-Pi.

---

## 🚀 Первые шаги нового чата

### Приоритет 1 — фиксация уроков и handoff в репо (Claude Code)

Открыть Claude Code в `C:\Users\ARDOR\Documents\Projects\u1u2-bridge` и передать задание:

```
Контекст: UART7 на Orange Pi 5 Max был доведён до рабочего состояния. Обнаружены три новых урока,
есть обновлённая версия docs/wiring-opi5max.md и сам этот handoff — нужно зафиксировать всё в git.

Задание:
1. В CLAUDE.md, в раздел "Lessons & Incidents", добавить ТРИ новых записи сверху над текущей
   записью 2026-05-22 (про m1 vs m2). Тексты уроков — см. docs/handoff/2026-05-22-late-uart7-bringup-complete.md,
   разделы "Lesson 1" (BT-конфликт), "Lesson 2" (_BOOT_PATH="" quirk), "Lesson 3" (Dupont первое подозрение).
   Формат записей — как у текущих в Lessons & Incidents (заголовок с датой, абзац описания, "Правило",
   "Проверка"). Каждая запись короче чем в handoff (3-5 предложений + правило + проверка), а полный
   контекст остаётся в handoff-файле.

2. Заменить docs/wiring-opi5max.md новой версией (исходник прилагается отдельно, скопировать целиком
   с заменой существующего файла).

3. Создать docs/handoff/2026-05-22-late-uart7-bringup-complete.md — положить туда полный текст
   handoff'а (исходник прилагается отдельно). Если папки docs/handoff/ нет — создать.

4. verify (.\verify.ps1) должен пройти зелёным по всем 5 шагам (правки только в .md, кода не трогаем,
   shellcheck должен быть на PATH после прошлой сессии).

5. Коммит:

   docs: UART7 bringup — BT-конфликт, _BOOT_PATH quirk, Dupont-perfemma & handoff archive

   - CLAUDE.md: три новых Lesson (BT-конфликт UART7 ↔ AP6611, _BOOT_PATH="" на joshua-riek,
     Dupont-перемычки как первое подозрение)
   - docs/wiring-opi5max.md v3: notice про обязательное отключение BT перед UART7 loopback,
     закрыт открытый вопрос про persistence
   - docs/handoff/2026-05-22-late-uart7-bringup-complete.md: архив handoff'а из сессии bringup

   Pushни в origin.
```

### Приоритет 2 — автоматизация в install.sh (Claude Code, та же сессия или следующая)

Через Claude Code добавить в `install.sh` для роли `u2` (где-то после установки overlay-файлов, перед systemd enable) шаги:

- Дописать в `/etc/default/u-boot` (idempotent — sed-replace или check-then-append):
  ```
  U_BOOT_FDT_OVERLAYS_DIR="/lib/firmware/"
  U_BOOT_FDT_OVERLAYS="device-tree/rockchip/overlay/rk3588-uart7-m1.dtbo"
  ```
- Вызвать `u-boot-update`.
- `systemctl disable + mask bluetooth.service ap6611s-bluetooth.service`.

Эти три действия — это **TL;DR** в начале handoff (см. выше), они уже выверены на u2-Pi. Подумай как сделать idempotent для запуска повторно без падений (sed -i с проверкой, что строки ещё нет). После изменений — `verify` зелёный, коммит, push.

### Приоритет 3 — hardware-задачи (требуют ответа от пользователя)

1. **Спросить пользователя модель ELRS TX модуля** — для распайки. Нужно знать:
   - Питание модуля: 5В (pin 2 Pi) или 3.3В (pin 1 Pi)?
   - Расположение пятаков/контактов RX, TX, GND, VCC на модуле.
2. После получения ответа — собрать переходник с обжатыми/паянными проводами:
   - Pi pin 29 (UART7_TX) → ELRS RX
   - Pi pin 38 (UART7_RX) → ELRS TX
   - Pi pin 2 (5V) или pin 1 (3.3V) → ELRS VCC
   - Pi pin 6 (GND) → ELRS GND

### Приоритет 4 — end-to-end проверка (после распайки)

Стенд (без винтов!):
- TX12 → u1-Pi (USB HID)
- u1-Pi → u2-Pi через CPE710 + WireGuard
- u2-Pi → ELRS TX модуль (UART7 на pin 29/38)
- ELRS TX → дрон через 2.4 ГГц
- Дрон в Betaflight Configurator — должны видеть RX каналы.

Это блокировано параллельно:
- CPE710 PtP-настройка (отдельная задача из `docs/CPE710-SETUP.md`).
- u1-Pi настройка (joystick → CRSF мост, WireGuard клиент).

---

## ❌ Что НЕ нужно делать в новом чате (антипаттерны)

- **Не пытаться использовать overlay m2** — он на Pi 5 Max сломан, M2 активирует ноду но RX-сторону оставляет в `GPIO UNCLAIMED`. Проверено.
- **Не использовать пины 24/26** для loopback m2 — они тоже не работают по той же причине.
- **Не пытаться использовать UART7 с включённым BT** — `brcm_patchram_plus` захватит порт, конфликт неизбежен.
- **Не класть dtbo в `/boot/overlays/` с `U_BOOT_FDT_OVERLAYS_DIR="overlays/"`** — `_BOOT_PATH=""` на joshua-riek ломает поиск, скрипт ищет в `/overlays/`.
- **Не править `/boot/extlinux/extlinux.conf` вручную** — теперь работает штатный `u-boot-update` через `/etc/default/u-boot`. Ручная правка переживёт ровно до следующего обновления ядра.
- **Не пытаться писать kernel postinst hook** для перезаписи extlinux.conf — он не нужен, штатный механизм работает.
- **Не диагностировать программу первой при странном loopback** — сначала проверь перемычку (см. Lesson 3).

---

## 🔄 Открытые архитектурные вопросы

- **u1-Pi:** Bluetooth там тоже архитектурно занимает UART (вероятно UART7, проверить). Если на u1-Pi мы НЕ используем UART7 — BT можно оставить (вдруг пригодится для BT-клавиатуры при отладке). Если используем — disable+mask аналогично. Решить при настройке u1-Pi.
- **install.sh `MODE=full`:** в HANDOFF от середины дня была идея режима, где оба стека (control + video) идут через WireGuard. Это пока не реализовано.

---

## 🎒 Предпочтения пользователя (соблюдать)

1. **Claude Code установлен** (`C:\Users\ARDOR\Documents\Projects\u1u2-bridge`). При переходе к работе с репо/git — анонсировать заранее, не молча. PowerShell на Windows.
2. **Длинный чат → handoff + новый чат заранее.** Анонсировать.
3. **Дозировать информацию.** Один логический блок за раз, ждать подтверждения. Не вываливать длинные списки/таблицы/портянки кода.
4. **Когда шаг требует открыть программу** (PowerShell, Claude Code, SSH, браузер, web-UI) — явно сказать в начале шага и расписать пошагово.
5. **Общается по-русски,** отвечать по-русски.
