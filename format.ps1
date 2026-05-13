# format.ps1 — авто-починка форматирования и простых линт-ошибок.
# Запуск: .\format.ps1

uv run ruff format common tests
uv run ruff check --fix common tests
Write-Host "`n[OK] Formatted" -ForegroundColor Green
