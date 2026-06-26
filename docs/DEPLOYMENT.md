# DEPLOYMENT — развёртывание u1u2-bridge на Orange Pi 5 / 5 Max

> ✅ **Документ приведён к канону 2026-06-26.** Источник истины по значениям —
> `install.sh` и эталонные env в `docs/baseline/`; этот runbook им
> соответствует. Если расходится — верить `install.sh`/`baseline`, а
> расхождение завести в реестр `docs/roadmap/task2-stack-audit.md`.
>
> Краткая карта канона (что важно знать перед чтением тела):
>
> - **CRSF-инстанс — один на узел:** `crsf-bridge@p1` (u1) и
>   `crsf-bridge@elrs` (u2). Пары `@tx1`/`@tx2` больше нет.
> - **UDP-порт CRSF:** `14552` (один порт, двунаправленно).
> - **UART-устройства:** u1 — CH340 напрямую `/dev/ttyUSB0`; u2 — UART7
>   overlay `/dev/ttyS7`. udev-symlink'ов `/dev/ttyACM-*` нет (см. §5).
> - **WireGuard (bench):** подсеть `10.8.0.0/24` (u1 `10.8.0.6`,
>   u2 `10.8.0.7`).
> - **Транспорт двухрежимный:** `tunnel` (WG `10.8.0.x`) или `direct`
>   (CPE710 LAN `192.168.1.x`). `install.sh` пишет env по выбранному
>   `TRANSPORT` — не хардкодьте подсеть руками.
> - **Железо:** Orange Pi 5 (`end0`) или 5 Max (`enP3p49s0`); стенд — 5 Max.

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
2. Включите её через USB-C 5V/4A (не от слабого зарядника — RK3588(S) под
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
  это не joshua-riek образ). Пакет `gstreamer1.0-rockchip1` атомарен:
  есть `mpph264enc` → есть и `mppvideodec` (декодер для u1).
- Авто-определение Ethernet-интерфейса (см. §2). Можно переопределить:
  `IFACE=enP3p49s0 sudo ./install.sh u1`.
- Запись `netplan`-конфигурации со статическим IP:
  > **На u1:** `192.168.1.20/24`
  > **На u2:** `192.168.1.10/24`
- Копирование кода в `/opt/u1u2-bridge/`, env-файлов в `/etc/u1u2-bridge/`,
  systemd-юнитов в `/etc/systemd/system/`. env-файл — по роли:
  `crsf-p1.env` (u1) или `crsf-elrs.env` (u2).
- Выбор транспорта для env: `TRANSPORT=tunnel` (WG `10.8.0.x`, дефолт) или
  `TRANSPORT=direct` (CPE710 LAN `192.168.1.x`). Подставляется в `PEER=`
  при записи env — см. §6.
- `sysctl` для увеличенных UDP-буферов.
- `systemctl enable --now` для CRSF-инстанса роли (`crsf-bridge@p1` на u1 /
  `crsf-bridge@elrs` на u2) и видео-юнита по роли (`video-rx` на u1 /
  `video-tx` на u2).

> **UART-устройства udev НЕ требуют** на текущем железе: u1 берёт CH340
> напрямую как `/dev/ttyUSB0`, u2 — UART7 как `/dev/ttyS7` (ставится
> overlay'ем, не udev). Подробности и почему — §5.

> **ВАЖНО — SSH оборвётся.** `netplan apply` меняет IP Pi на статический
> `192.168.1.x`. Если вы заходили на старый адрес — сессия упадёт. После
> переподключитесь по новому IP:
>
> > **На u1:** `ssh ubuntu@192.168.1.20`
> > **На u2:** `ssh ubuntu@192.168.1.10`
>
> С ноутбука, подключённого LAN-кабелем к LAN-порту того же PoE-инжектора
> (ноутбук тоже должен быть в `192.168.1.0/24`, например `.100`).

После переподключения проверьте статус CRSF-инстанса роли:

> **На u1:** `systemctl status crsf-bridge@p1`
> **На u2:** `systemctl status crsf-bridge@elrs`

Если serial-устройство роли ещё не на месте (`/dev/ttyUSB0` на u1 —
адаптер не воткнут; `/dev/ttyS7` на u2 — overlay не активен), сервис
будет в `activating (auto-restart)`. Это ожидаемо — см. §5.

---

## 5. UART-устройства (текущее железо)

> **udev-регистрация для текущего железа не нужна.** Раздел описывает,
> где CRSF-мост берёт serial на каждой роли и что проверить, если порта
> нет. Старый `setup_udev.sh` (RS485-эра, symlink'и `/dev/ttyACM-*`) для
> этой конфигурации не запускается.

### 5.1. u1 — CH340 напрямую

На u1 CRSF в П1 (trainer-port) идёт через USB↔UART CH340, который
появляется как `/dev/ttyUSB0`. udev-symlink сделать нельзя: чип CH340
рапортует `SerialNumber=0` (нет уникального серийника), привязать
стабильное имя не по чему — поэтому env указывает прямой узел:

```
SERIAL_DEV=/dev/ttyUSB0
```

Проверка:

```
ls -l /dev/ttyUSB0
udevadm info /dev/ttyUSB0 | grep -E 'ID_VENDOR_ID|ID_MODEL_ID'   # ожид. 1a86:7523 (CH340)
```

> **Один адаптер на u1.** Если в системе появляется второй `ttyUSB*`
> (другой USB-serial), порядок `ttyUSB0/1` может «поехать» между
> перезагрузками. На текущем стенде у u1 один CH340 — конфликта нет.

### 5.2. u2 — UART7 (`/dev/ttyS7`)

На u2 CRSF к ELRS-передатчику идёт через аппаратный UART7 RK3588,
включаемый device-tree overlay'ем (UART7_M2, pin 26). Узел —
`/dev/ttyS7`, USB тут не участвует:

```
SERIAL_DEV=/dev/ttyS7
```

Проверка, что overlay активен и узел существует:

```
ls -l /dev/ttyS7
```

> Конфигурация overlay (`extlinux.conf` / `u-boot`) — вне этого runbook;
> на собранном стенде она уже активна. Если `/dev/ttyS7` отсутствует —
> overlay не подхватился, это отдельная hardware-задача, не udev.

### 5.3. Рестарт CRSF после появления порта

> ⚠️ **Drone-safety gate:** перед рестартом любого CRSF-сервиса — **винты
> сняты, Boxer (передатчик) выключен.** Рестарт на лету = непредсказуемый
> выход управления.

Когда serial-устройство роли на месте:

> **На u1:** `sudo systemctl restart crsf-bridge@p1`
> **На u2:** `sudo systemctl restart crsf-bridge@elrs`

---

## 6. WireGuard-туннель (транспорт `tunnel`)

WireGuard добавляет второй слой шифрования поверх Wi-Fi и стабильные
имена пиров (`10.8.0.6`, `10.8.0.7`) независимо от нижележащей сети. Это
дефолтный транспорт (`TRANSPORT=tunnel`). Полёт возможен и без него — на
прямых `192.168.1.x` (`TRANSPORT=direct`), но для production-устойчивости
рекомендуется туннель.

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
> Address = 10.8.0.6/24
> PrivateKey = <содержимое /etc/wireguard/privatekey НА u1>
> ListenPort = 51820
>
> [Peer]
> PublicKey = <publickey ИЗ u2>
> Endpoint = 192.168.1.10:51820
> AllowedIPs = 10.8.0.7/32
> PersistentKeepalive = 15
> ```

> **На u2** — создайте `/etc/wireguard/wg0.conf`:
>
> ```
> [Interface]
> Address = 10.8.0.7/24
> PrivateKey = <содержимое /etc/wireguard/privatekey НА u2>
> ListenPort = 51820
>
> [Peer]
> PublicKey = <publickey ИЗ u1>
> Endpoint = 192.168.1.20:51820
> AllowedIPs = 10.8.0.6/32
> PersistentKeepalive = 15
> ```

> **Почему `AllowedIPs = 10.8.0.x/32`, а не `0.0.0.0/0`:** на Pi↔Pi линке
> широкий `AllowedIPs` создал бы default route через WG и сломал бы
> локальный доступ к CPE и LAN. Узкий `/32` пускает в туннель только
> трафик к адресу партнёра. (Это про Pi-конфиг; kill-switch
> `0.0.0.0/0` на стороне ARDOR-ноутбука — отдельная, осознанная
> история.)

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
ping -c 3 10.8.0.7
```

С u2:

```
ping -c 3 10.8.0.6
```

Должен пройти. Если нет — handshake не случился, обычно из-за неправильно
скопированных публичных ключей или asymmetric NAT (которого у нас не
должно быть в bridge-сети).

### 6.6. env: транспорт и переключение

CRSF-мост пирится с партнёром по адресу из `PEER=` в env-файле роли
(`/etc/u1u2-bridge/crsf-p1.env` на u1, `crsf-elrs.env` на u2). Канон по
транспорту:

| Транспорт | u1 `PEER=` | u2 `PEER=` |
| --- | --- | --- |
| `tunnel` (WG, дефолт) | `10.8.0.7:14552` | `10.8.0.6:14552` |
| `direct` (CPE710 LAN) | `192.168.1.10:14552` | `192.168.1.20:14552` |

`install.sh` подставляет нужный `PEER=` по `TRANSPORT` при записи env —
**предпочитайте переустановку/`switch-mode`, а не ручную правку.** Если
правите вручную:

> **На u1:** в `crsf-p1.env` поменяйте `PEER=` на адрес u2 нужного
> транспорта.
> **На u2:** в `crsf-elrs.env` — на адрес u1.

После правки (помня про drone-safety gate из §5.3):

> **На u1:** `sudo systemctl restart crsf-bridge@p1`
> **На u2:** `sudo systemctl restart crsf-bridge@elrs`

---

## 7. Smoke-test

```
sudo ./smoke_test.sh u1   # или u2
```

`smoke_test.sh` проверяет состояние **по роли** (не пара `@tx*`, как было
в RS485-эре). Что зелёного ожидать:

- **systemd-юниты роли активны:** CRSF-инстанс (`crsf-bridge@p1` на u1 /
  `crsf-bridge@elrs` на u2) и видео-юнит (`video-rx` на u1 /
  `video-tx` на u2).
- **serial роли на месте:** `/dev/ttyUSB0` (u1) или `/dev/ttyS7` (u2).
- **RKMPP-элемент роли доступен:** `mppvideodec` на u1 (декодер для
  `video_rx`), `mpph264enc` на u2 (энкодер для `video_tx`). Проверяется
  именно используемый ролью элемент — u1 на энкодере не падает молча.
- **peer-ping по транспорту:** в `tunnel` — `10.8.0.x` через `wg0`; в
  `direct` — `192.168.1.x` через CPE710.
- **мост гоняет байты:** CRSF-инстанс роли пишет строку статистики
  (нужно ≥10 c после старта — статистика раз в 10 c).

> Точный формат вывода и пороги — в самом `smoke_test.sh`; если WireGuard
> не поднят в bench-фазе, WG-проверка даёт WARN, а не FAIL (exit 0).

Если есть FAIL — смотрите §8.

---

## 8. Troubleshooting

| Симптом | Куда смотреть |
| --- | --- |
| CRSF-инстанс роли (`@p1`/`@elrs`) в restart loop | serial роли на месте? u1 → `ls -l /dev/ttyUSB0`; u2 → `ls -l /dev/ttyS7` (см. §5). Если да → `journalctl -u crsf-bridge@p1 -n 50` (или `@elrs`), искать ошибку открытия порта или прав (см. ниже про `dialout`). |
| `ping 192.168.1.x` не идёт | Это не Pi, это CPE710. Возвращайтесь к `docs/CPE710-SETUP.md` (контрольная проверка через прямой LAN-кабель). |
| `mpph264enc` not found на install.sh | Это не тот образ Ubuntu — нужен joshua-riek/ubuntu-rockchip. На Armbian / generic Ubuntu Server `gstreamer1.0-rockchip1` либо отсутствует, либо нерабочий. См. §1. |
| SSH оборвался после `install.sh` и не пускает | `netplan apply` сменил IP. Переподключайтесь на новый адрес — см. ремарку в §4. |
| `wg show` показывает `latest handshake (never)` | Endpoint IP в конфиге пира неправильный, или ListenPort заблокирован на промежуточном CPE (но в bridge-режиме CPE не должен фильтровать). Проверь что оба `wg-quick@wg0` запущены: `systemctl status wg-quick@wg0`. |
| CRSF-инстанс стартует, но `smoke_test.sh` ругается на "stats line" | Подождите 30 секунд после старта (статистика пишется раз в 10s, нужно минимум 1-2 цикла). Если и через минуту нет — физически нет CRSF-трафика на UART (ELRS/П1 не подключён? питания нет?). |
| `Permission denied` на serial-порту в логе crsf-bridge | Пользователь, под которым крутится юнит, не в группе `dialout`. `sudo usermod -aG dialout ubuntu` + logout/login. Актуально для `/dev/ttyUSB0` (u1) и `/dev/ttyS7` (u2). |

---

## 9. Final checklists

Скопируйте команды, прогоните на соответствующей Pi. Ожидаемый результат —
в комментарии справа. Адреса показаны для транспорта `tunnel` (WG); для
`direct` подставьте `192.168.1.x`.

### 9.1. u1 готов

```
ip -br addr show | grep 192.168.1.20             # одна строка, IP на правильном интерфейсе
ping -c 3 -W 1 192.168.1.10                       # 3 ответа, 0% loss (peer по CPE710 LAN)
ls -l /dev/ttyUSB0                                # CH340 на месте (1a86:7523)
systemctl is-active crsf-bridge@p1 video-rx.service
                                                  # два "active"
gst-inspect-1.0 mppvideodec | head -1             # "Factory Details:" или подобное (декодер u1)
sudo wg show | grep -E 'latest handshake|transfer'
                                                  # если WG поднят — handshake свежий
ping -c 3 10.8.0.7                                # peer через wg0 (если tunnel)
sudo ./smoke_test.sh u1                           # exit 0 + всё зелёное
```

### 9.2. u2 готов

```
ip -br addr show | grep 192.168.1.10              # одна строка, IP на правильном интерфейсе
ping -c 3 -W 1 192.168.1.20                       # 3 ответа, 0% loss (peer по CPE710 LAN)
ls -l /dev/ttyS7                                  # UART7 overlay активен
systemctl is-active crsf-bridge@elrs video-tx.service
                                                  # два "active"
gst-inspect-1.0 mpph264enc | head -1              # "Factory Details:" или подобное (энкодер u2)
v4l2-ctl --list-devices                           # должен быть виден USB видеограббер
sudo wg show | grep -E 'latest handshake|transfer'
                                                  # если WG поднят — handshake свежий
ping -c 3 10.8.0.6                                # peer через wg0 (если tunnel)
sudo ./smoke_test.sh u2                           # exit 0 + всё зелёное
```

После того как оба чек-листа зелёные — Pi готовы к подключению к Аппаратуре
(У1 8-pin разъём, У2 видеограббер и ELRS-передатчики). Финальная стыковка с
hardware и полевые испытания — за пределами этого runbook.
