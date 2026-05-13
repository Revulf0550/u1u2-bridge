"""Smoke-тест: проверяет, что pytest pipeline собран корректно.

Будет заменён реальными тестами на crsf_bridge в Stage 3, когда код переедет
из HANDOFF.md в `common/crsf_bridge.py`.
"""

import sys


def test_python_version() -> None:
    """Базовая проверка: Python 3.12+."""
    assert sys.version_info >= (3, 12), f"Need Python 3.12+, got {sys.version_info}"


def test_common_package_importable() -> None:
    """`common` пакет находится через pythonpath."""
    import common  # noqa: F401
