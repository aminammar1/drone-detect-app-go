"""Tests for per-track annotation colors (no fake model names)."""

from types import SimpleNamespace

import numpy as np

from detector.detect import Detector, TrackedDetection, annotate, track_color


def _detector_with(targets: set[str], names: dict[int, str]) -> Detector:
    """Detector without loading weights; only _kept/_names/_targets matter."""
    det = Detector.__new__(Detector)
    det._targets = targets
    det._names = names
    return det


def test_kept_relabels_stand_in_as_drone() -> None:
    det = _detector_with({"airplane"}, {4: "airplane"})
    kept = det._kept(4, 0.18, [0, 0, 10, 10])
    assert kept is not None
    assert kept.class_name == "drone"


def test_kept_keeps_drone_as_drone() -> None:
    det = _detector_with({"drone"}, {0: "drone"})
    kept = det._kept(0, 0.9, [0, 0, 10, 10])
    assert kept is not None
    assert kept.class_name == "drone"


def test_track_color_stable_and_default() -> None:
    assert track_color(None) == (0, 255, 0)
    assert track_color(3) == track_color(3)
    assert track_color(1) != track_color(2)


def test_annotate_uses_track_color_without_touching_input() -> None:
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    dets = [
        TrackedDetection(class_name="drone", confidence=0.9, bbox=(40, 40, 90, 90), track_id=1),
        TrackedDetection(class_name="drone", confidence=0.8, bbox=(110, 110, 160, 160), track_id=2),
    ]
    out = annotate(frame, dets)
    assert out is not frame
    assert np.count_nonzero(frame) == 0  # input untouched
    # Border pixels of each box carry that track's color.
    assert tuple(out[40, 40].tolist()) == track_color(1)
    assert tuple(out[110, 110].tolist()) == track_color(2)


def test_reset_tracker_keeps_tracker_instances_for_persisted_model() -> None:
    class FakeTracker:
        def __init__(self) -> None:
            self.reset_calls = 0

        def reset(self) -> None:
            self.reset_calls += 1

    det = Detector.__new__(Detector)
    trackers = [FakeTracker(), FakeTracker()]
    det._model = SimpleNamespace(predictor=SimpleNamespace(trackers=trackers))

    det.reset_tracker()

    assert det._model.predictor.trackers is trackers
    assert [tracker.reset_calls for tracker in trackers] == [1, 1]
