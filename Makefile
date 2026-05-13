.PHONY: help install verify test typecheck lint format clean

help: ## Список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости через uv
	uv sync --all-groups

verify: lint typecheck test ## Все проверки разом (контракт перед commit/push)
	@echo ""
	@echo "[OK] All checks passed"

test: ## pytest
	uv run pytest

typecheck: ## mypy strict
	uv run mypy common tests

lint: ## ruff check + format check
	uv run ruff check common tests
	uv run ruff format --check common tests

format: ## Авто-починка
	uv run ruff format common tests
	uv run ruff check --fix common tests

clean: ## Удалить кэши
	rm -rf .mypy_cache .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
