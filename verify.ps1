# verify.ps1 — контракт самопроверки.
# Прогоняет: ruff lint, ruff format check, mypy strict, pytest, shellcheck.
# Запуск: .\verify.ps1

$ErrorActionPreference = "Continue"

Write-Host "`n[1/5] ruff check (lint)..." -ForegroundColor Cyan
uv run ruff check common tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Lint failed. Try .\format.ps1 для авто-починки." -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/5] ruff format check..." -ForegroundColor Cyan
uv run ruff format --check common tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Format check failed. Запусти .\format.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "`n[3/5] mypy (types, strict)..." -ForegroundColor Cyan
uv run mypy common tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Typecheck failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n[4/5] pytest (tests)..." -ForegroundColor Cyan
uv run pytest
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Tests failed" -ForegroundColor Red
    exit 1
}

# shellcheck — все .sh в репо (root + u1/ + u2/). Рекурсивно через Get-ChildItem -Recurse.
Write-Host "`n[5/5] shellcheck (all .sh)..." -ForegroundColor Cyan
$shCmd = Get-Command shellcheck -ErrorAction SilentlyContinue
if (-not $shCmd) {
    Write-Host "[FAIL] shellcheck not on PATH." -ForegroundColor Red
    Write-Host "       Установить:  winget install --id koalaman.shellcheck" -ForegroundColor Yellow
    exit 1
}
# Исключаем .venv (если когда-то туда попадут чужие .sh) — путь нормализуем через FullName.
$scripts = Get-ChildItem -Path . -Filter *.sh -File -Recurse |
    Where-Object { $_.FullName -notmatch '\\\.venv\\' } |
    ForEach-Object { Resolve-Path -Relative $_.FullName }
if (-not $scripts) {
    Write-Host "[WARN] нет .sh в репо — пропускаю" -ForegroundColor Yellow
} else {
    Write-Host ("       checking: " + ($scripts -join ", "))
    & shellcheck @scripts
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n[FAIL] Shellcheck failed" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n[OK] All checks passed" -ForegroundColor Green
