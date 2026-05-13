# verify.ps1 — контракт самопроверки.
# Прогоняет: ruff lint, ruff format check, mypy strict, pytest.
# (shellcheck для .sh-скриптов добавим, когда они появятся в Stage 3.)
# Запуск: .\verify.ps1

$ErrorActionPreference = "Continue"

Write-Host "`n[1/4] ruff check (lint)..." -ForegroundColor Cyan
uv run ruff check common tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Lint failed. Try .\format.ps1 для авто-починки." -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/4] ruff format check..." -ForegroundColor Cyan
uv run ruff format --check common tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Format check failed. Запусти .\format.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "`n[3/4] mypy (types, strict)..." -ForegroundColor Cyan
uv run mypy common tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Typecheck failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n[4/4] pytest (tests)..." -ForegroundColor Cyan
uv run pytest
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Tests failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n[OK] All checks passed" -ForegroundColor Green
