"""Tests for per-track annotation colors (no fake model names)."""

import numpy as np

from detector.detect import TrackedDetection, annotate, track_color


def test_track_color_stable_and_default() -> None:
    assert track_color(None) == (0, 255, 0)
    assert track_color(3) == track_color(3)
    assert track_color(1) != track_color(2)


def test_annotate_uses_track_color_without_touching_input() -> None:
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    dets = [
        TrackedDetection(class_name="drone", confidence=0.9, bbox=(5, 5, 20, 20), track_id=1),
        TrackedDetection(class_name="drone", confidence=0.8, bbox=(22, 22, 35, 35), track_id=2),
    ]
    out = annotate(frame, dets)
    assert out is not frame
    assert np.count_nonzero(frame) == 0  # input untouched
    # Border pixels of each box carry that track's color.
    assert tuple(out[5, 5].tolist()) == track_color(1)
    assert tuple(out[22, 22].tolist()) == track_color(2)
