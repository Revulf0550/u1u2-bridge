#requires -Version 7
<#
.SYNOPSIS
  Переключатель транспорта u1u2-bridge между Режимом №1 (tunnel / WireGuard)
  и Режимом №2 (direct / радио CPE710).

.DESCRIPTION
  Делает ТОЛЬКО софт-флип: деплоит текущий HEAD на обе Pi с нужным TRANSPORT
  (пишет CRSF-env + video.env + ufw под целевой режим) и, по подтверждению,
  рестартит сервисы. Физику и WireGuard скрипт НЕ трогает.

  netplan НЕ меняется намеренно: на Pi сосуществуют статика 192.168.1.x
  (99-u1u2-bridge.yaml) и cloud-init DHCP (50-cloud-init.yaml), конфиг
  location-adaptive — на мосту живёт статика, дома DHCP даёт интернет для WG.

  ПЕРЕД запуском (руками):
    1. Обе Pi физически переставлены в место целевого режима:
         tunnel = домашний свитч;  direct = концы радиомоста CPE710.
    2. WireGuard на ARDOR выставлен под целевой режим:
         tunnel -> WG ВКЛЮЧЁН  (Pi доступны по 10.8.0.6/.7)
         direct -> WG ВЫКЛЮЧЕН (Pi доступны по 192.168.1.20/.10)

.PARAMETER Mode
  Целевой режим: tunnel | direct.

.PARAMETER NoRestart
  Только деплой конфига на диск, без рестарта сервисов (CRSF не дёргается).
  Применится последующим ручным рестартом или ребутом.

.EXAMPLE
  .\switch-mode.ps1 direct
.EXAMPLE
  .\switch-mode.ps1 tunnel -NoRestart
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('tunnel', 'direct')]
    [string]$Mode,

    [switch]$NoRestart
)

$ErrorActionPreference = 'Stop'
$Key  = Join-Path $HOME '.ssh\u1u2'
$Repo = $PSScriptRoot

# Карта: роль -> (адрес в ЦЕЛЕВОМ режиме, имена сервисов).
# u1 = RX/монитор, u2 = TX. Имена сервисов от режима не зависят.
if ($Mode -eq 'tunnel') {
    $WgHint = 'ВКЛЮЧЁН (доступ к Pi по 10.8.0.x)'
    $Nodes = @(
        @{ Role = 'u1'; Ip = '10.8.0.6'; Crsf = 'crsf-bridge@p1';   Video = 'video-rx' }
        @{ Role = 'u2'; Ip = '10.8.0.7'; Crsf = 'crsf-bridge@elrs'; Video = 'video-tx' }
    )
}
else {
    $WgHint = 'ВЫКЛЮЧЕН (доступ к Pi по 192.168.1.x)'
    $Nodes = @(
        @{ Role = 'u1'; Ip = '192.168.1.20'; Crsf = 'crsf-bridge@p1';   Video = 'video-rx' }
        @{ Role = 'u2'; Ip = '192.168.1.10'; Crsf = 'crsf-bridge@elrs'; Video = 'video-tx' }
    )
}

function Invoke-PiSsh {
    param([string]$Ip, [string]$Cmd)
    ssh -i $Key -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "ubuntu@$Ip" $Cmd
    if ($LASTEXITCODE -ne 0) { throw "ssh ubuntu@$Ip -> код $LASTEXITCODE" }
}

Write-Host "==> Переключение транспорта в режим: $Mode" -ForegroundColor Cyan
Write-Host "    WireGuard должен быть: $WgHint"
Write-Host "    Pi: u1=$($Nodes[0].Ip)  u2=$($Nodes[1].Ip)"
Write-Host ""

# --- 0. preflight: обе Pi доступны -------------------------------------------
foreach ($n in $Nodes) {
    Write-Host "--> ping $($n.Role) $($n.Ip)"
    if (-not (Test-Connection -TargetName $n.Ip -Count 2 -Quiet)) {
        throw "Pi $($n.Role) ($($n.Ip)) недоступна. Проверь физику и WG: $WgHint"
    }
}

# --- 1. архив текущего HEAD --------------------------------------------------
$Tar = Join-Path $env:TEMP 'u1u2-deploy.tar'
Write-Host "--> git archive HEAD -> $Tar"
git -C $Repo archive --format=tar -o $Tar HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive -> код $LASTEXITCODE" }

# --- 2. деплой на каждую Pi (неразрушающий: install.sh без restart) ----------
foreach ($n in $Nodes) {
    Write-Host ""
    Write-Host "==> [$($n.Role)] $($n.Ip): деплой HEAD (TRANSPORT=$Mode)" -ForegroundColor Cyan
    scp -i $Key -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new $Tar "ubuntu@$($n.Ip):~/deploy.tar"
    if ($LASTEXITCODE -ne 0) { throw "scp -> $($n.Ip): код $LASTEXITCODE" }

    $deploy = "rm -rf ~/u1u2-deploy && mkdir -p ~/u1u2-deploy && " +
              "tar -xf ~/deploy.tar -C ~/u1u2-deploy && cd ~/u1u2-deploy && " +
              "sudo TRANSPORT=$Mode SKIP_APT=1 SKIP_NETPLAN=1 MODE=bench ./install.sh $($n.Role)"
    Invoke-PiSsh -Ip $n.Ip -Cmd $deploy
}

# --- 3. рестарт сервисов (с подтверждением — рвёт CRSF ~2 с) ------------------
if ($NoRestart) {
    Write-Host ""
    Write-Host "==> -NoRestart: конфиг на диске, сервисы крутят старый. Применить рестартом/ребутом." -ForegroundColor Yellow
}
else {
    Write-Host ""
    Write-Host "!! Рестарт CRSF/видео разорвёт управление на ~2 с." -ForegroundColor Yellow
    Write-Host "!! ДРОН должен быть ВЫКЛЮЧЕН / на земле." -ForegroundColor Yellow
    $ans = Read-Host "Рестартить сервисы на обеих Pi сейчас? [y/N]"
    if ($ans -match '^[yY]$') {
        foreach ($n in $Nodes) {
            Write-Host "--> [$($n.Role)] restart $($n.Crsf) + $($n.Video)"
            Invoke-PiSsh -Ip $n.Ip -Cmd "sudo systemctl daemon-reload && sudo systemctl restart $($n.Crsf) $($n.Video)"
        }
    }
    else {
        Write-Host "==> Рестарт пропущен. Конфиг на диске, применится рестартом/ребутом." -ForegroundColor Yellow
    }
}

# --- 4. проверка состояния (диагностика, exit-код игнорируем) ----------------
Write-Host ""
Write-Host "==> Проверка состояния" -ForegroundColor Cyan
foreach ($n in $Nodes) {
    Write-Host "----- $($n.Role) $($n.Ip) -----"
    $check = "systemctl is-active $($n.Crsf) $($n.Video); echo --crsf--; " +
             "journalctl -u $($n.Crsf) -n 2 --no-pager"
    ssh -i $Key -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "ubuntu@$($n.Ip)" $check
}

Write-Host ""
Write-Host "==> Готово. Целевой режим: $Mode." -ForegroundColor Green
