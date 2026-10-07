"""Tests for the detection event models (DESCRIPTION.md section 3.1)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from detector.events import BBox, DetectionEvent, EventSource, Identifier

NOW = datetime(2026, 6, 9, 14, 3, 22, 418000, tzinfo=UTC)


def _event(**overrides) -> dict:
    base: dict = {
        "type": "detection",
        "event_id": str(uuid4()),
        "detected_at": NOW.isoformat(),
        "source": {"id": "cam-01", "kind": "image", "uri": "images/image.png"},
        "zone_id": "north-gate",
        "track_id": 1,
        "class": "airplane",
        "confidence": 0.91,
        "bbox": {"x1": 120, "y1": 80, "x2": 260, "y2": 170},
        "frame_index": 0,
        "snapshot_path": "data/snapshots/2026-06-09/abc.jpg",
    }
    base.update(overrides)
    return base


def test_valid_event_defaults_identifier_to_none_and_omits_visual() -> None:
    event = DetectionEvent.model_validate(_event())
    assert event.identifier == Identifier(kind="none", value="")
    assert event.visual is None
    wire = event.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert wire["class"] == "airplane"
    assert "class_name" not in wire
    assert "visual" not in wire
    assert wire["identifier"] == {"kind": "none", "value": ""}


def test_wire_json_round_trips() -> None:
    event = DetectionEvent.model_validate(_event())
    assert DetectionEvent.model_validate_json(event.to_json()) == event


def test_confidence_bounds() -> None:
    for ok in (0.0, 1.0, 0.35):
        DetectionEvent.model_validate(_event(confidence=ok))
    for bad in (-0.1, 1.5):
        with pytest.raises(ValidationError):
            DetectionEvent.model_validate(_event(confidence=bad))


def test_naive_detected_at_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        DetectionEvent.model_validate(_event(detected_at="2026-06-09T14:03:22"))


def test_bad_event_id_rejected() -> None:
    with pytest.raises(ValidationError):
        DetectionEvent.model_validate(_event(event_id="not-a-uuid"))


def test_bbox_must_be_complete() -> None:
    with pytest.raises(ValidationError):
        DetectionEvent.model_validate(_event(bbox={"x1": 120, "y1": 80, "x2": 260}))
    TypeAdapter(BBox).validate_python({"x1": 0, "y1": 0, "x2": 10, "y2": 10})


def test_source_kind_limited_to_image_or_video() -> None:
    EventSource.model_validate({"id": "cam-01", "kind": "video", "uri": "videos/a.mp4"})
    with pytest.raises(ValidationError):
        DetectionEvent.model_validate(_event(source={"id": "cam-01", "kind": "stream", "uri": "x"}))


def test_explicit_serial_identifier() -> None:
    event = DetectionEvent.model_validate(
        _event(identifier={"kind": "serial", "value": "1581F5FJC231Q0012345"})
    )
    assert event.identifier.value == "1581F5FJC231Q0012345"


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        DetectionEvent.model_validate(_event(track_id_typo=1))
