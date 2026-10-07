"""Stage B (airframe mapping) and Stage C (family classifier) tests (M8).

No weights, no network: the classifier is exercised with a fake YOLO-cls
model. See PROJECT.md 5.4 and docs/TRAINING.md.
"""

import numpy as np
import pytest

from detector.attributes import ModelFamilyClassifier, crop_box
from detector.detect import AIRFRAME_TYPES, airframe_from_class
from detector.events import DetectionEvent


def test_airframe_exact_types() -> None:
    for name in sorted(AIRFRAME_TYPES):
        assert airframe_from_class(name) == name
        assert airframe_from_class(name.upper()) == name


def test_airframe_aliases() -> None:
    assert airframe_from_class("fixed-wing") == "fixed_wing"
    assert airframe_from_class("fixed wing") == "fixed_wing"
    assert airframe_from_class("heli") == "helicopter"
    assert airframe_from_class("quad") == "quadcopter"


def test_airframe_no_info_returns_none() -> None:
    for name in ("drone", "airplane", "bird", "multirotor_heavy", "unknown-thing"):
        assert airframe_from_class(name) is None


def test_visual_event_with_airframe_and_family() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    event = DetectionEvent.model_validate(
        {
            "type": "detection",
            "event_id": str(uuid4()),
            "detected_at": datetime(2026, 6, 9, 14, 3, 22, tzinfo=UTC).isoformat(),
            "source": {"id": "cam-01", "kind": "image", "uri": "images/image.png"},
            "zone_id": "north-gate",
            "track_id": 1,
            "class": "quadcopter",
            "confidence": 0.91,
            "bbox": {"x1": 1, "y1": 1, "x2": 10, "y2": 10},
            "frame_index": 0,
            "snapshot_path": "data/snapshots/2026-06-09/abc.jpg",
            "visual": {
                "airframe_type": "quadcopter",
                "airframe_confidence": 0.91,
                "model_family": "Mavic",
                "model_confidence": 0.61,
            },
        }
    )
    assert event.visual is not None
    assert event.visual.airframe_type == "quadcopter"


class _FakeProbs:
    def __init__(self, top1: int, conf: float) -> None:
        self.top1 = top1
        self.top1conf = conf


class _FakeResult:
    def __init__(self, top1: int, conf: float) -> None:
        self.probs = _FakeProbs(top1, conf)


class _FakeClsModel:
    def __init__(self, top1: int = 0, conf: float = 0.9) -> None:
        self.names = {0: "Mavic", 1: "Mini"}
        self._top1 = top1
        self._conf = conf

    def predict(self, crop, verbose=False):
        return [_FakeResult(self._top1, self._conf)]


def _crop(h: int = 64, w: int = 64) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_family_classifier_hit() -> None:
    clf = ModelFamilyClassifier.__new__(ModelFamilyClassifier)
    clf._model = _FakeClsModel(0, 0.9)
    clf._min_conf = 0.5
    assert clf.predict_crop(_crop()) == ("Mavic", 0.9)


def test_family_classifier_below_threshold_is_none() -> None:
    clf = ModelFamilyClassifier.__new__(ModelFamilyClassifier)
    clf._model = _FakeClsModel(1, 0.2)
    clf._min_conf = 0.5
    assert clf.predict_crop(_crop()) is None


def test_family_classifier_bad_crops_are_none() -> None:
    clf = ModelFamilyClassifier.__new__(ModelFamilyClassifier)
    clf._model = _FakeClsModel()
    clf._min_conf = 0.5
    assert clf.predict_crop(np.zeros((0, 0, 3), dtype=np.uint8)) is None
    assert clf.predict_crop(np.zeros((4, 4, 3), dtype=np.uint8)) is None


def test_family_classifier_missing_weights_fails_loudly(tmp_path) -> None:
    from pathlib import Path

    with pytest.raises(FileNotFoundError, match="family classifier weights"):
        ModelFamilyClassifier(Path("nope.pt"), tmp_path)


def test_crop_box_clamps_to_frame() -> None:
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    crop = crop_box(frame, (-10.0, -5.0, 50.0, 40.0))
    assert crop.shape == (40, 50, 3)
    empty = crop_box(frame, (10.0, 10.0, 5.0, 5.0))
    assert empty.size == 0
