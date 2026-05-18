"""Unit tests для timing-хелперов bench/loopback.py.

Bench-скрипт не покрыт интеграционными тестами (он гоняет реальные serial
порты), но pure-function хелперы echo_deadline/period_cap критичны — баг
207ff66 (cap отстригал echo_deadline) обошёлся в две bench-сессии
chasing ghost'ов. Этот файл — страховка от регрессии той же логики.
"""

import pytest
from bench.loopback import FRAME_SIZE, compute_echo_deadline, compute_period_cap


class TestComputeEchoDeadline:
    def test_420k_baud_margin_dominates(self) -> None:
        # frame_tx = 26×10/420000 = 619 µs, 2× + 20 ms = 21.24 ms — на high-baud
        # сам overhead-margin доминирует, wire-time почти не виден.
        expected = 2 * (FRAME_SIZE * 10 / 420_000) + 0.020
        assert compute_echo_deadline(420_000) == pytest.approx(expected)
        assert compute_echo_deadline(420_000) > 0.020

    def test_9600_baud(self) -> None:
        # frame_tx = 26×10/9600 = 27.083 ms, 2× + 20 = 74.17 ms
        expected = 2 * (FRAME_SIZE * 10 / 9600) + 0.020
        assert compute_echo_deadline(9600) == pytest.approx(expected)

    def test_1200_baud(self) -> None:
        # frame_tx = 26×10/1200 = 216.67 ms, 2× + 20 = 453.3 ms — измеренный
        # на u1-pi реальный RT ≈ 443 мс, deadline даёт ~10 мс запаса.
        expected = 2 * (FRAME_SIZE * 10 / 1200) + 0.020
        assert compute_echo_deadline(1200) == pytest.approx(expected)


class TestComputePeriodCap:
    def test_cap_leaves_5ms_setup_margin_when_period_loose(self) -> None:
        # 9600 / 10 Hz: period=100 ms, deadline≈74 ms → cap = max(95, 74) = 95 ms
        deadline = compute_echo_deadline(9600)
        cap = compute_period_cap(0.1, deadline)
        assert cap == pytest.approx(0.095)
        assert cap > deadline  # echo_deadline применяется полностью

    def test_cap_clamps_to_echo_deadline_when_period_too_short(self) -> None:
        # 420k / 500 Hz: period=2 ms, deadline≈21 ms, period-5 = -3 ms
        # → cap должен быть deadline (~21 ms), не -3 ms.
        deadline = compute_echo_deadline(420_000)
        cap = compute_period_cap(0.002, deadline)
        assert cap == deadline

    def test_regression_207ff66_low_baud_cap_does_not_clip_deadline(self) -> None:
        """Регрессия 207ff66: на низких baud cap (period × 0.8) обрезал deadline.

        Pre-fix: 1200 baud / 2 Hz → period=500ms, deadline=435ms, cap=400ms
        → echo обрубалось за 36 ms до приезда последнего байта → 100% false-FAIL.
        Инвариант: cap ≥ deadline ВСЕГДА, на любой паре (baud, rate).
        """
        cases = [
            (1200, 2),  # оригинальный failing case
            (9600, 10),  # mid-baud sanity
            (115_200, 100),  # промежуточный
            (420_000, 500),  # production CRSF на 500 Hz
            (420_000, 250),  # production CRSF на 250 Hz
        ]
        for baud, rate in cases:
            deadline = compute_echo_deadline(baud)
            period = 1.0 / rate
            cap = compute_period_cap(period, deadline)
            assert cap >= deadline, (
                f"baud={baud} rate={rate}: cap={cap * 1000:.2f} ms < "
                f"deadline={deadline * 1000:.2f} ms — bug 207ff66 регрессировал"
            )
