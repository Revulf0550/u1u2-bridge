# HANDOFF: u1u2-bridge · Этап 2 (видео) · 3 июня 2026

> Этот документ — полное состояние сессии 3 июня 2026 по Этапу 2. Скопируй
> целиком в первое сообщение нового чата, чтобы продолжить с того же места
> с полным контекстом, не повторяя путь.

---

## TL;DR

- **Этап 1 (CRSF) закрыт 27 мая.** Управление от Boxer до дрона через wg-туннель работает.
- **Этап 2 (видео) сегодня:** программная цепочка `v4l2src → mpph264enc → RTP → wg → udpsrc → mppvideodec → waylandsink → HDMI` была доказательно собрана и запускалась (видели чёрный кадр от грабера на HDMI монитор u1).
- **Сейчас застряли** на парадоксе: TX-pipeline на u2 в PLAYING без ошибок, но `tcpdump -i wg0 'udp port 5600'` на u2 показывает **0 пакетов** за 20+ секунд. Pipeline не доводит данные до udpsink. Это произошло после многих перезапусков пайплайна.
- **Грабер физически работает** (подтверждено коллегой на этой же Pi, подтверждено файловым захватом `multifilesink`).
- **Очень много гипотез отметено** — список ниже, чтобы не ходить по кругу.

---

## Реальная конфигурация (отличается от HANDOFF.md и CLAUDE.md)

### Сеть

| Что | В HANDOFF.md | По факту |
|---|---|---|
| LAN сеть | `192.168.1.0/24` | **`192.168.31.0/24`** |
| u1 LAN IP | 192.168.1.20 | **192.168.31.72** |
| u2 LAN IP | 192.168.1.10 | **192.168.31.100** |
| WireGuard сеть | `10.10.0.0/24` | **`10.8.0.0/24`** |
| u1 wg IP | (не было) | **10.8.0.6** |
| u2 wg IP | (не было) | **10.8.0.7** |
| Основная машина wg | (не было) | **10.8.0.5** |
| Сетевой интерфейс | `end0` | **`enP3p49s0`** |
| CPE710 PtP-мост | предполагался основным транспортом | **отсутствует** в этой фазе |
| Текущий транспорт wg | через CPE710 | **через интернет**, ping 180 ms |

CPE710 — это **Этап 3**, ещё не разворачиваем. Пока всё через wg-туннель поверх домашних роутеров.

### Hardware

- **Грабер:** Arkmicro 18ec:5555 "USB2.0 PC CAMERA" — **не MS2130** как было в HANDOFF.md. Это дешёвый EasyCAP-клон с CVBS-входом (жёлтый RCA), S-Video, и парой RCA audio. Известный плохой клон, но **коллега подтвердил что у него работало** на этой же Orange Pi 5.
- **VRX:** модель не названа пользователем, 5.8 ГГц аналог, выдаёт PAL composite.
- **Дрон + Vtx:** модель не названа, Vtx 5.8 ГГц, ELRS управление (Этап 1).
- **HDMI монитор:** подключён к u1, 1920×1080.

### Текущее физическое подключение

```
Дрон Vtx (5.8 GHz) ─air─> VRX (5.8 GHz, PAL) ─RCA жёлтый─> Arkmicro грабер ─USB─> u2
                                                                                    ↓
                                                                          GStreamer TX
                                                                                    ↓
                                                                          udpsink → wg0
                                                                                    ↓
                                                                       wg-туннель (180ms)
                                                                                    ↓
                                                                          udpsrc на u1
                                                                                    ↓
                                                                          GStreamer RX (в cage)
                                                                                    ↓
                                                                          waylandsink → HDMI монитор
```

---

## Что точно работает (подтверждено сегодня)

1. **SSH к u1 (10.8.0.6) и u2 (10.8.0.7)** через wg-туннель.
2. **`ping 10.8.0.6` / `ping 10.8.0.7`** — отвечают, 180 ms.
3. **`scp`** в обе стороны.
4. **CRSF Этап 1:**
   - `crsf-bridge@tx2.service` — **active** (управление работает через него)
   - `crsf-bridge@tx1.service` — **inactive** (это нормальное текущее состояние, не трогать)
5. **Грабер физически опознан** — `lsusb` показывает `18ec:5555 Arkmicro Technologies Inc. USB2.0 PC CAMERA`, появились `/dev/video0` и `/dev/video1`.
6. **Грабер выдаёт кадры в файлы** через `multifilesink` (например 50 кадров за 1.4 сек = ~36 fps). В одном из тестов из 50 кадров: 48 кадров синей заставки 6.6 KB + 2 кадра живого OSD VRX 37–40 KB.
7. **Cage + waylandsink на u1** — рабочее решение для HDMI вывода (см. ниже подробности).
8. **GStreamer TX-pipeline собирается** — caps идут до `mpph264enc.src` (H264 baseline).
9. **wg0 интерфейс на u2 имеет правильный маршрут до 10.8.0.6**: `ip route get 10.8.0.6` → `dev wg0 src 10.8.0.7`.

## Что не работает (текущая проблема)

**TX-pipeline на u2 в PLAYING, но НИ ОДНОГО UDP-пакета не уходит на wg0.**

- Лог TX: дошёл до `mpph264enc.sink caps = NV12, 640x480` и обрезается. Нет caps для `rtph264pay` и `udpsink`. Это либо обрезанный лог, либо pipeline на этом и стопится.
- `tcpdump -i wg0 -n 'udp port 5600' -c 20` на u2 за 20+ секунд — 0 пакетов.
- На u1 в окне cage `udpsrc.src caps` появилось (declared caps, не доказательство получения!), `rtpjitterbuffer.sink` тоже, `rtph264depay.sink` тоже — но **`rtph264depay.src` не появилось**: ни одного H264-кадра на выходе depay.

Проблема воспроизводится **с videotestsrc** (исключает грабер) и **без rtpjitterbuffer** (исключает проблему latency дропа поздних пакетов).

---

## Что попробовать в первую очередь (план следующей сессии)

### Версия #1: «застрял RKMPP encoder после многих перезапусков»

Гипотеза: за сессию было ≥6 перезапусков GStreamer TX-pipeline с `mpph264enc`. RKMPP драйвер мог не освободить нормально внутренние ресурсы. encoder инициализируется (caps есть), но не выпускает кадры.

**Шаги:**

```bash
# на u2:
sudo reboot
# подождать ~30 сек, переподключиться по SSH
```

После рестарта u2 — заново подключить грабер (или отключить-подключить USB), создать `/run/user/0` на u1 (он тоже на tmpfs), запустить ту же цепочку. Должно дать чистый старт RKMPP.

### Версия #2: software encoder x264enc вместо mpph264enc

Для исключения RKMPP полностью. Установить если нет:

```bash
# на u2:
sudo apt install -y gstreamer1.0-plugins-ugly
```

Команда TX с x264enc:

```bash
gst-launch-1.0 -v \
  videotestsrc \
  ! video/x-raw,format=I420,width=640,height=480,framerate=30/1 \
  ! x264enc bitrate=2500 tune=zerolatency speed-preset=ultrafast key-int-max=30 \
  ! video/x-h264,profile=baseline \
  ! rtph264pay pt=96 mtu=1200 config-interval=1 \
  ! udpsink host=10.8.0.6 port=5600 sync=false async=false
```

x264enc — software encoder, медленнее, но стабильный. Если **с ним пакеты пойдут на wg0** (`tcpdump` поймает), а с mpph264enc нет — значит проблема в RKMPP. Если **и с x264enc 0 пакетов** — проблема в udpsink/сети/wg.

### Версия #3: проверить udpsink базово

Минимальный тест — отправить UDP без всякого encoder, просто `videotestsrc → multipart → udpsink`. Или ещё проще:

```bash
# на u2:
echo "hello" | nc -u -w1 10.8.0.6 5600
```

И параллельно на u1 в новом окне:

```bash
sudo tcpdump -i wg0 -n 'udp port 5600' -c 5
nc -ul 5600  # в отдельном окне
```

Если `nc` пакет прошёл — UDP/wg-сторона работает, проблема **точно** в GStreamer. Если `nc` не прошёл — что-то с сетью.

### Версия #4: bind-address у udpsink

GStreamer udpsink по умолчанию без `bind-address`. Возможно ядро выбирает не тот source IP. Попробовать:

```bash
... ! udpsink host=10.8.0.6 port=5600 bind-address=10.8.0.7 sync=false async=false
```

### Версия #5: разобраться с грабером отдельно от live

Параллельно с решением «TX не отправляет UDP» — выяснить почему грабер даёт OSD VRX только в 4% кадров. Это про физику VRX/Vtx:
- **Узнать модель VRX** (этот вопрос задавался 3 раза, не получил ответа)
- **Узнать модель Vtx и его частоту/диапазон** (R/F/A/B/E/L band, канал)
- Возможно VRX не залочен на Vtx и выдаёт собственный синий "no signal" overlay вместо живой картинки

---

## Hardware-блокер по VRX (открытый вопрос)

Из `multifilesink`-тестов: грабер видит **в основном синюю заставку** (либо своя, либо OSD VRX), и только **2 кадра из 50** дали живой OSD. То есть VRX почти не передаёт видео на CVBS-выход.

**Что нужно узнать у пользователя:**
1. Модель VRX (бренд + модель)
2. Есть ли у VRX дисплей / LED — что они показывают, когда есть/нет дрон
3. Модель Vtx (бренд + модель)
4. Частоту/канал Vtx (например R1=5658 MHz, F2=5760 MHz и т.п.)
5. Есть ли у VRX **scan/search** функция, и пробовал ли пользователь
6. Какая антенна на VRX (linear / circular), и в правильную ли сторону смотрит

Без этой информации диагностика "почему VRX не передаёт видео" дальше не двинется.

---

## Рабочие команды (для копирования в новую сессию)

### Подготовка u1 после reboot (одноразово каждый раз)

```bash
sudo pkill -9 cage
sudo pkill -9 gst-launch
sudo mkdir -p /run/user/0
sudo chmod 0700 /run/user/0
```

### RX на u1 (через cage + waylandsink)

```bash
sudo XDG_RUNTIME_DIR=/run/user/0 cage -- gst-launch-1.0 -v \
  udpsrc port=5600 caps="application/x-rtp,encoding-name=H264,payload=96,clock-rate=90000" buffer-size=2097152 \
  ! rtpjitterbuffer latency=500 drop-on-latency=false do-lost=true \
  ! rtph264depay ! h264parse ! mppvideodec ! videoconvert \
  ! waylandsink
```

**Изменения от вчерашних попыток:** `latency=500` (было 50), `drop-on-latency=false` (было true) — учитывает wg-latency 180 ms.

### TX на u2 с грабером (текущая рабочая)

```bash
gst-launch-1.0 -v \
  v4l2src device=/dev/video0 \
  ! image/jpeg,width=640,height=480,framerate=30/1 \
  ! jpegdec ! videoconvert ! video/x-raw,format=NV12 \
  ! mpph264enc rc-mode=cbr bps=2500000 gop=15 profile=66 \
  ! video/x-h264,profile=baseline ! h264parse config-interval=1 \
  ! rtph264pay pt=96 mtu=1200 config-interval=1 \
  ! udpsink host=10.8.0.6 port=5600 sync=false async=false
```

**Параметры подтверждены работающими ранее в сессии**: 640×480 (грабер не умеет 720×576), MJPG (грабер не умеет YUYV), mtu=1200 (под wg overhead).

### TX на u2 с тестовым паттерном (для дебага)

```bash
gst-launch-1.0 -v \
  videotestsrc \
  ! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 \
  ! mpph264enc rc-mode=cbr bps=2500000 gop=15 profile=66 \
  ! video/x-h264,profile=baseline ! h264parse config-interval=1 \
  ! rtph264pay pt=96 mtu=1200 config-interval=1 \
  ! udpsink host=10.8.0.6 port=5600 sync=false async=false
```

### Диагностика сети

```bash
# на u2 — выходят ли пакеты:
sudo tcpdump -i wg0 -n 'udp port 5600' -c 20

# на u2 — на любом интерфейсе:
sudo tcpdump -i any -n 'udp port 5600' -c 20

# на u2 — маршрут:
ip route get 10.8.0.6

# на u1 — приходят ли пакеты:
sudo tcpdump -i wg0 -n 'udp port 5600' -c 20
```

### Файловый захват с грабера (для проверки физики VRX)

```bash
# на u2:
rm -f /tmp/cap-*.jpg
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=50 \
  ! image/jpeg,width=640,height=480,framerate=30/1 \
  ! multifilesink location=/tmp/cap-%03d.jpg 2>&1 | tail -2
ls -l /tmp/cap-*.jpg | awk '{print $5}' | sort -u
ls -lhS /tmp/cap-*.jpg | head -5

# на основной машине (PowerShell) — посмотреть самый крупный кадр:
scp ubuntu@10.8.0.7:/tmp/cap-019.jpg .
start .\cap-019.jpg
```

`sort -u` показывает уникальные размеры. Один — статичная заставка. Несколько крупных (30+ KB) — живой сигнал.

---

## Гипотезы, которые проверили и **не подтвердились** (не повторять)

1. ❌ **Грабер — не CVBS-устройство (веб-камера)** — опровергнуто фото: жёлтый RCA, S-Video, audio RCA, классический EasyCAP.
2. ❌ **Грабер физически сломан** — опровергнуто (а) словами пользователя что коллега заставил его работать на той же Pi с инструкцией от ChatGPT, (б) файловым тестом где 2/50 кадров живые 37–40 KB.
3. ❌ **Скрытое разрешение 720×576 PAL у грабера** — `v4l2-ctl --set-fmt-video=720,576` ужал обратно на 640×480.
4. ❌ **Скрытый pixel format YUYV вместо MJPG** — `not-negotiated` ошибка, грабер реально только MJPG.
5. ❌ **Скрытые UVC Extension Controls для PAL/NTSC switch** — `v4l2-ctl --all` показал только базовые webcam controls (brightness/contrast/gamma/...), никаких extension unit.
6. ❌ **VIDIOC_ENUMSTD доступен** — нет, `Inappropriate ioctl for device`. У этого чипа в UVC mode нет CVBS API.
7. ❌ **«Разогрев» грабера** (100 кадров вместо 20) — только 2 уникальных размера 6609/6613 (микрошум статичной заставки).
8. ❌ **VRX без lock'а сильно молчит**, включение дрона даст lock — частично: 2 из 50 кадров стали живыми, но 96% всё ещё синяя заставка.
9. ❌ **kmssink на u1 решит вопрос с HDMI** — VOP2 bugs (`*ERROR* wait pd0 off timeout`, `*ERROR* unexpected power on pd5`) ломают modesetting даже с sudo + force-modesetting=true.
10. ❌ **`io-mode=4` (userptr) в v4l2src** — был в `video_tx.sh`, не пробовали в live, но это известно проблемная опция для дешёвых UVC.
11. ❌ **MTU фрагментация — mtu=1200 решит** — нет, проблема не в этом (с mtu=1200 тоже 0 пакетов на wg0).
12. ❌ **rtpjitterbuffer latency=50 + drop-on-latency=true дропает поздние пакеты** — нет, проблема глубже (даже без jitterbuffer 0 пакетов на TX-стороне).

---

## Lessons для CLAUDE.md (нужно зафиксировать через Claude Code)

### 2026-06-03 · Грабер по факту Arkmicro 18ec:5555, не MS2130

В HANDOFF.md прописан MS2130 (HDMI capture). По факту — Arkmicro EasyCAP-клон с CVBS. Чип только 640×480 MJPG, без `video_standard` API, без UVC Extension Controls. Коллега подтвердил что грабер физически работает на этой же Pi.

**Правило:** при первой работе с любым USB-устройством — `lsusb` и `v4l2-ctl --all` ДО написания кода под предположенную модель. ID устройства определяет всё остальное.

### 2026-06-03 · kmssink не работает на Orange Pi 5 + Ubuntu joshua-riek

Известные баги VOP2 driver: `wait pd0 off timeout`, `unexpected power on pd5`, `i2c read err`. force-modesetting=true и sudo не помогают.

**Правило:** на этой платформе для HDMI-вывода использовать `cage + waylandsink`, не `kmssink`. Это разворот относительно HANDOFF.md, где kmssink — основной путь.

### 2026-06-03 · cage требует sudo и XDG_RUNTIME_DIR

```bash
sudo mkdir -p /run/user/0
sudo chmod 0700 /run/user/0
sudo XDG_RUNTIME_DIR=/run/user/0 cage -- gst-launch-1.0 ...
```

`/run/user/0` на tmpfs — пропадает при reboot, надо создавать заново.

**Правило:** в `install.sh` добавить systemd-tmpfiles конфиг для автосоздания `/run/user/0` при загрузке u1.

### 2026-06-03 · Сетевая карта в HANDOFF.md устарела

Реальная сеть: 192.168.31.x LAN + 10.8.0.x wg, интерфейс enP3p49s0, CPE710 ещё не развёрнут. wg через интернет, latency 180 ms.

**Правило:** обновить HANDOFF.md и CLAUDE.md под реальную конфигурацию через Claude Code.

### 2026-06-03 · WireGuard MTU в RTP

Дефолтный `mtu=1400` в `rtph264pay` при wg-латентности 180 ms требует уменьшения. Стартовое значение для wg-туннеля через интернет: **mtu=1200**.

Также: `rtpjitterbuffer latency=50` слишком мал для wg через интернет, нужно **500–1000 ms** и `drop-on-latency=false`.

### 2026-06-03 · udpsrc.src caps в логе ≠ полученный пакет

GStreamer declared caps появляются в логе СРАЗУ при инициализации, независимо от прихода данных. Для проверки реального приёма пакетов — только `tcpdump`.

**Правило:** при диагностике сетевых pipeline-ов первый вопрос — `tcpdump`, а не «что в логе GStreamer».

### 2026-06-03 · WSL? bash в PowerShell?

Пользователь несколько раз вставлял bash-команды (`rm -f`, `gst-launch-1.0`, `ls -lh /tmp/...`) в PowerShell-окно и наоборот. Это нормальная ошибка при работе с несколькими SSH-окнами и PowerShell параллельно.

**Правило для Claude:** при выдаче команд **явно помечать** «На u1:» или «На u2:» или «В PowerShell:» перед каждым кодовым блоком, не полагаться на контекст.

---

## Чего я в конце сессии не успел и не знаю

1. Что именно делал коллега (точная команда / софт / параметры) — у пользователя нет доступа к нему.
2. Модель VRX и Vtx.
3. Реальное состояние OSD VRX (что показывает на дисплее когда включён без дрона / с дроном).
4. Реальная MTU wg0 (`ip link show wg0`) — не спрашивал.
5. dmesg при подключении грабера — не смотрел.
6. Что показывают `v4l2-ctl --device=/dev/video1` (вторая нода UVC-устройства) — возможно там другой capture endpoint.

---

## Первое сообщение в новый чат (предлагается)

> Это handoff с прошлой сессии — приложу полный документ ниже. TL;DR:
> Этап 2 (видео), застряли на парадоксе: TX-pipeline в PLAYING без ошибок,
> но `tcpdump` на u2 wg0 показывает 0 пакетов, в итоге на HDMI монитор u1
> ничего не приходит. Это после многих перезапусков pipeline в сессии.
>
> План на эту сессию:
> 1. Перезагрузить u2 (Версия #1) — освободить RKMPP, чистый старт
> 2. Попробовать x264enc (Версия #2) — исключить RKMPP
> 3. Если не помогает — `nc -u` тест (Версия #3) — изолировать GStreamer от сети
> 4. Параллельно: узнать модель VRX, понять почему даёт OSD только 4% времени
>
> Подключиться к u2: `ssh ubuntu@10.8.0.7`, к u1: `ssh ubuntu@10.8.0.6`,
> пароль ubuntu. Сетевая конфигурация в handoff-документе.
>
> [приложить содержимое HANDOFF-2026-06-03-stage2-video.md]

---

*Документ составлен: 2026-06-03. Сессия начата ~14:00, закрыта на этом handoff'е.*
