# DEPLOYMENT — развёртывание u1u2-bridge на Orange Pi 5

> ⚠️ **ВНИМАНИЕ: ДОКУМЕНТ ЧАСТИЧНО УСТАРЕЛ.** Сам деплой через `install.sh`
> (§4) остаётся актуальным каноном. Но **ручные env- и udev-шаги ниже
> устарели** (RS485-эра) и при дословном копировании дадут несовместимый с
> текущим стендом env. Источник истины по значениям — `install.sh`, плюс
> `CLAUDE.md` (раздел «Сеть — UDP и WireGuard») и эталонные env в
> `docs/baseline/`. Конкретные расхождения тела с каноном:
>
> - **CRSF-инстансы:** пара `crsf-bridge@tx1`/`@tx2` на узле → в каноне по
>   одному CRSF-инстансу на узел: `@p1` (u1) и `@elrs` (u2).
> - **UDP-порт CRSF:** `14550`/`14551` → канон `14552`.
> - **UART-устройства (§5):** `/dev/ttyACM-CRSF1/2` + `setup_udev.sh` — это
>   RS485-эра; текущая привязка serial иная.
> - **WireGuard (§6):** подсеть `10.10.0.x` — проектный overlay-Этап, не
>   развёрнут; живой bench-WG — `10.8.0.x`.
> - **Железо:** «Orange Pi 5 / `end0`» — стенд на «5 Max» (`enP3p49s0`).
>
> Переписывание тела на канон — отдельная задача (реестр
> `docs/roadmap/task2-stack-audit.md`, P2-deployment-stale).

Runbook на обе роли (`u1` — мастер-пульт, `u2` — выносная база). Везде,
где шаги расходятся между ролями, есть call-out:

> **На u1:** ...
> **На u2:** ...

Идёте по разделам сверху вниз, по одному устройству за раз. Параллельно
не пытайтесь — две Pi на одном CPE710 в момент `netplan apply` могут
помешать друг другу (сами поднимаются на одинаковом дефолтном DHCP-адресе
до применения статики).

---

## 1. Prerequisites

Эта инструкция предполагает что у вас уже:

- **Ubuntu 24.04 LTS на Orange Pi 5** от
  [joshua-riek/ubuntu-rockchip](https://github.com/Joshua-Riek/ubuntu-rockchip)
  (release: server-24.04). Armbian тоже работает, но gstreamer1.0-rockchip1
  у joshua-riek проверен и собран корректно — на Armbian возможны сюрпризы
  с `mpph264enc`.
- **SSH-доступ работает** под пользователем `ubuntu` (или вашим), пользователь
  в группе `sudo`. Установка ОС и базовая настройка SSH — за пределами этого
  документа.
- **Роль каждой Pi определена** заранее: одна — `u1` (мастер-пульт,
  HDMI-вывод видео в очки), вторая — `u2` (выносная база, видео-граббер +
  ELRS). Промаркируйте корпуса физически.
- **Пара CPE710 настроена** по `docs/CPE710-SETUP.md`. Pi подключаются к
  CPE710 LAN-портам (через PoE-инжекторы), но настройка CPE сама по себе
  должна быть завершена и radio-link проверен ДО начала этого деплоя.

> **Если ОС ещё не залита:** ставьте joshua-riek по их официальной
> инструкции и возвращайтесь сюда. Залив образа, расширение rootfs, SSH —
> чистая «вендорская» процедура, не наше дело.

---

## 2. Подключение Pi к CPE710

Физика:

1. Возьмите Pi для нужной роли.
2. Включите её через USB-C 5V/4A (не от слабого зарядника — RK3588S под
   нагрузкой жрёт до 3 A).
3. Подключите Ethernet от Pi к **LAN-порту PoE-инжектора того CPE,
   который этой Pi соответствует**:

   > **На u1:** Pi → PoE-инжектор slave CPE (тот что Client, IP `192.168.1.3`).
   > **На u2:** Pi → PoE-инжектор master CPE (тот что AP, IP `192.168.1.2`).

4. Зайдите на Pi по SSH (на этом этапе она ещё на DHCP или старом
   статическом адресе — то что вы настроили при заливке ОС).

5. Проверьте, что Ethernet-интерфейс поднят:

   ```
   ip -br link
   ```

   Ожидается одна `lo` плюс хотя бы один Ethernet-интерфейс в состоянии
   `UP`. Имя зависит от платы — обычно `end0` (Pi 5) или `enP3p49s0` (Pi
   5 Max). Если интерфейс `DOWN` — проверьте кабель и/или питание CPE.

> **Статика IP** будет настроена `install.sh` на следующем шаге. До
> этого Pi может видеть CPE710 и наоборот, но единого `192.168.1.0/24`
> с обеими Pi пока нет.

---

## 3. Получение кода

На Pi:

```
sudo apt update
sudo apt install -y git
cd ~
git clone https://github.com/Revulf0550/u1u2-bridge.git
cd u1u2-bridge
git checkout v0.3.0     # или main, если хотите последнее
```

> **Замечание для тех, кто переносит код через scp с Windows:** копируйте
> репо ИЗ локального PowerShell (`PS C:\...>`), не из SSH-сессии. См.
> урок 2026-05-18 в `CLAUDE.md` — `scp src ubuntu@pi:~/` падает с
> `Could not resolve hostname C` если запустить из bash-сессии на Pi.

---

## 4. Запуск install.sh

```
sudo ./install.sh u1   # на мастер-пульте
sudo ./install.sh u2   # на выносной базе
```

Что он делает:

- `apt install` зависимостей: `python3-serial`, `gstreamer1.0-rockchip1`
  и весь стек gstreamer, `wireguard-tools`, `v4l-utils`, `curl`.
- Проверка что `mpph264enc` доступен (если нет — FAIL с сообщением, что
  это не joshua-riek образ).
- Авто-определение Ethernet-интерфейса (см. §2). Можно переопределить:
  `IFACE=end0 sudo ./install.sh u1`.
- Запись `netplan`-конфигурации со статическим IP:
  > **На u1:** `192.168.1.20/24`
  > **На u2:** `192.168.1.10/24`
- Копирование кода в `/opt/u1u2-bridge/`, env-файлов в `/etc/u1u2-bridge/`,
  systemd-юнитов в `/etc/systemd/system/`.
- Напоминание про `setup_udev.sh` — udev-правила для UART **не** записываются
  здесь, см. §5.
- `sysctl` для увеличенных UDP-буферов.
- `systemctl enable --now` для `crsf-bridge@tx1/tx2` и видео-юнита по роли.

> **ВАЖНО — SSH оборвётся.** `netplan apply` меняет IP Pi на статический
> `192.168.1.x`. Если вы заходили на старый адрес — сессия упадёт. После
> переподключитесь по новому IP:
>
> > **На u1:** `ssh ubuntu@192.168.1.20`
> > **На u2:** `ssh ubuntu@192.168.1.10`
>
> С ноутбука, подключённого LAN-кабелем к LAN-порту того же PoE-инжектора
> (ноутбук тоже должен быть в `192.168.1.0/24`, например `.100`).

После переподключения проверьте:

```
systemctl status crsf-bridge@tx1 crsf-bridge@tx2
```

Скорее всего оба сервиса в `failed` или `activating (auto-restart)` —
это нормально, пока нет `/dev/ttyACM-CRSF1/2` (см. §5).

---

## 5. Регистрация UART-адаптеров через setup_udev.sh

> **Пропустите этот раздел, если адаптеры ещё не пришли.** Вернётесь к
> нему после получения hardware. `crsf-bridge@tx*` юниты до этого будут
> рестартиться в loop — это ожидаемо.

> **На u1 в режиме drone (одна Pi на дроне):** UART-адаптеров нет,
> `setup_udev.sh` запускать не нужно. На bench и production Pi с
> ELRS-передатчиками — нужно.

Когда адаптеры пришли — подключайте по ОДНОМУ:

1. Отсоедините оба адаптера от Pi (если до этого были подключены).
2. На Pi:

   ```
   cd ~/u1u2-bridge
   sudo ./setup_udev.sh
   ```

3. Скрипт попросит подключить адаптер для CRSF1 и нажать ENTER. Подключите
   физический адаптер `№1` (тот, что у вас по плану идёт на ELRS Tx1 или
   П1 trainer-port), дождитесь индикатора, нажмите ENTER.
4. То же самое для CRSF2.
5. Скрипт извлечёт VID/PID и серийники, запишет `/etc/udev/rules.d/90-u1u2-uart.rules`,
   сделает `udevadm reload + trigger + settle`, и проверит что появились:

   ```
   /dev/ttyACM-CRSF1
   /dev/ttyACM-CRSF2
   ```

6. Если оба symlinks на месте — рестартните сервисы:

   ```
   sudo systemctl restart crsf-bridge@tx1 crsf-bridge@tx2
   ```

> **Если у Pi только один адаптер (bench-фаза):** запустите `setup_udev.sh`
> когда подключите оба, либо отредактируйте `/etc/udev/rules.d/90-u1u2-uart.rules`
> вручную — оставьте только нужную строку.

---

## 6. WireGuard-туннель (опционально, рекомендуется перед полевыми)

WireGuard добавляет второй слой шифрования поверх Wi-Fi и стабильные
имена пиров (`10.10.0.1`, `10.10.0.2`) независимо от транспорта. Без него
полёт возможен через прямые `192.168.1.x`, но для production-устойчивости
лучше с туннелем.

### 6.1. Установка пакетов

```
sudo apt install -y wireguard wireguard-tools
```

(install.sh уже это сделал, но убедитесь.)

### 6.2. Генерация ключей

На КАЖДОЙ Pi:

```
cd /etc/wireguard
sudo wg genkey | sudo tee privatekey | sudo wg pubkey | sudo tee publickey
sudo chmod 600 privatekey
```

Сохраните `publickey` каждой Pi — его нужно вставить в конфиг ПАРТНЁРА.

### 6.3. Конфиг

> **На u1** — создайте `/etc/wireguard/wg0.conf`:
>
> ```
> [Interface]
> Address = 10.10.0.1/24
> PrivateKey = <содержимое /etc/wireguard/privatekey НА u1>
> ListenPort = 51820
>
> [Peer]
> PublicKey = <publickey ИЗ u2>
> Endpoint = 192.168.1.10:51820
> AllowedIPs = 10.10.0.2/32
> PersistentKeepalive = 15
> ```

> **На u2** — создайте `/etc/wireguard/wg0.conf`:
>
> ```
> [Interface]
> Address = 10.10.0.2/24
> PrivateKey = <содержимое /etc/wireguard/privatekey НА u2>
> ListenPort = 51820
>
> [Peer]
> PublicKey = <publickey ИЗ u1>
> Endpoint = 192.168.1.20:51820
> AllowedIPs = 10.10.0.1/32
> PersistentKeepalive = 15
> ```

> **Почему `AllowedIPs = 10.10.0.x/32`, а не `0.0.0.0/0`:** последнее
> создаёт default route через WG, ломая локальный доступ к CPE и LAN
> ноутбука. См. урок 2026-05-18 «wg-easy дефолт `AllowedIPs=0.0.0.0/0`
> ломает локалку».

### 6.4. Запуск

На обеих Pi:

```
sudo chmod 600 /etc/wireguard/wg0.conf
sudo systemctl enable --now wg-quick@wg0
```

### 6.5. Проверка

```
sudo wg show
```

Ожидается: `latest handshake` свежий (несколько секунд назад), счётчики
`transfer` ненулевые после `ping`.

С u1:

```
ping -c 3 10.10.0.2
```

Должен пройти. Если нет — handshake не случился, обычно из-за неправильно
скопированных публичных ключей или asymmetric NAT (которого у нас не
должно быть в bridge-сети).

### 6.6. Переключение env-файлов на WG-адреса

После того как туннель подтверждён, переключаем CRSF-мосты на пиринг
через WG:

> **На u1** — `/etc/u1u2-bridge/crsf-tx1.env` и `crsf-tx2.env`:
> поменять `PEER=192.168.1.10:14550` (и `:14551`) на `PEER=10.10.0.2:14550`
> и `PEER=10.10.0.2:14551` соответственно.

> **На u2** — симметрично, заменить на `PEER=10.10.0.1:14550` / `:14551`.

После правки:

```
sudo systemctl restart crsf-bridge@tx1 crsf-bridge@tx2
```

---

## 7. Smoke-test

```
sudo ./smoke_test.sh u1   # или u2
```

Зелёный вывод ожидается такой:

```
== systemd units
  [ OK ] crsf-bridge@tx1 активен
  [ OK ] crsf-bridge@tx2 активен
  [ OK ] video-rx.service активен            # u1; на u2 будет video-tx
== udev symlinks
  [ OK ] /dev/ttyACM-CRSF1 существует
  [ OK ] /dev/ttyACM-CRSF2 существует
== RKMPP (hardware H.264)
  [ OK ] mpph264enc доступен
== network: peer через CPE710
  [ OK ] ping 192.168.1.10 проходит         # с u1; с u2 — 192.168.1.20
== network: WireGuard туннель
  [ OK ] ping 10.10.0.2 через wg0 проходит  # если WG поднят
== мост гоняет байты (требует ≥10s после старта)
  [ OK ] crsf-bridge@tx1 пишет stats line за последнюю минуту

Все проверки прошли.
```

Если WireGuard ещё не настроен (§6 пропущен) — там будет `[WARN]` вместо
`[FAIL]`, общий exit code остаётся 0. Это нормально для bench-фазы.

Если есть FAIL — смотрите §8.

---

## 8. Troubleshooting

| Симптом | Куда смотреть |
| --- | --- |
| `crsf-bridge@tx*` в restart loop | `/dev/ttyACM-CRSF1/2` существуют? Если нет → §5 (`setup_udev.sh`). Если да → `journalctl -u crsf-bridge@tx1 -n 50`, искать ошибку открытия порта или прав (см. ниже про `dialout`). |
| `ping 192.168.1.x` не идёт | Это не Pi, это CPE710. Возвращайтесь к `docs/CPE710-SETUP.md` §5 (контрольная проверка через прямой LAN-кабель). |
| `mpph264enc` not found на install.sh | Это не тот образ Ubuntu — нужен joshua-riek/ubuntu-rockchip. На Armbian / generic Ubuntu Server `gstreamer1.0-rockchip1` либо отсутствует, либо нерабочий. См. §1. |
| SSH оборвался после `install.sh` и не пускает | `netplan apply` сменил IP. Переподключайтесь на новый адрес — см. ремарку в §4. |
| `wg show` показывает `latest handshake (never)` | Endpoint IP в конфиге пира неправильный, или ListenPort заблокирован на промежуточном CPE (но в bridge-режиме CPE не должен фильтровать). Проверь что оба `wg-quick@wg0` запущены: `systemctl status wg-quick@wg0`. |
| `crsf-bridge@tx*` стартует, но `smoke_test.sh` ругается на "stats line" | Подождите 30 секунд после старта (статистика пишется раз в 10s, нужно минимум 1-2 цикла). Если и через минуту нет — физически нет CRSF-трафика на UART (ELRS не подключён? питания нет?). |
| `Permission denied` на `/dev/ttyACM-CRSF*` в логе crsf-bridge | Пользователь, под которым крутится юнит, не в группе `dialout`. `sudo usermod -aG dialout ubuntu` + logout/login. install.sh уже предупреждает об этом в финальной секции — проверь её вывод. |

---

## 9. Final checklists

Скопируйте команды, прогоните на соответствующей Pi. Ожидаемый результат —
в комментарии справа.

### 9.1. u1 готов

```
ip -br addr show | grep 192.168.1.20             # одна строка, IP на правильном интерфейсе
ping -c 3 -W 1 192.168.1.10                       # 3 ответа, 0% loss
ls -l /dev/ttyACM-CRSF1 /dev/ttyACM-CRSF2         # оба symlinks существуют
systemctl is-active crsf-bridge@tx1 crsf-bridge@tx2 video-rx.service
                                                  # три "active"
gst-inspect-1.0 mpph264enc | head -1              # "Factory Details:" или подобное
sudo wg show | grep -E 'latest handshake|transfer'
                                                  # если WG поднят — handshake свежий
sudo ./smoke_test.sh u1                           # exit 0 + все [ OK ]
```

### 9.2. u2 готов

```
ip -br addr show | grep 192.168.1.10              # одна строка, IP на правильном интерфейсе
ping -c 3 -W 1 192.168.1.20                       # 3 ответа, 0% loss
ls -l /dev/ttyACM-CRSF1 /dev/ttyACM-CRSF2         # оба symlinks существуют
systemctl is-active crsf-bridge@tx1 crsf-bridge@tx2 video-tx.service
                                                  # три "active"
gst-inspect-1.0 mpph264enc | head -1              # "Factory Details:" или подобное
v4l2-ctl --list-devices                           # должен быть виден USB видеограббер
sudo wg show | grep -E 'latest handshake|transfer'
                                                  # если WG поднят — handshake свежий
sudo ./smoke_test.sh u2                           # exit 0 + все [ OK ]
```

После того как оба чек-листа зелёные — Pi готовы к подключению к Аппаратуре
(У1 8-pin разъём, У2 видеограббер и ELRS-передатчики). Финальная стыковка с
hardware и полевые испытания — за пределами этого runbook.
