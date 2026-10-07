"""Unit tests for evaluate.py math (M8). No weights or media needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from evaluate import fp_per_minute, scaled_total


def test_fp_per_minute_basic() -> None:
    assert fp_per_minute(30, 60.0) == 30.0
    assert fp_per_minute(0, 60.0) == 0.0
    assert fp_per_minute(10, 0.0) == 0.0
    assert fp_per_minute(10, -5.0) == 0.0


def test_fp_per_minute_scales() -> None:
    # 6 boxes in 30 s -> 12 per minute.
    assert fp_per_minute(6, 30.0) == 12.0


def test_scaled_total() -> None:
    assert scaled_total(5, 1) == 5
    assert scaled_total(5, 3) == 15
    assert scaled_total(0, 5) == 0
