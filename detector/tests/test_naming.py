"""Identified model names in boxes and snapshots (names come from acks, never pixels)."""

from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from detector.detect import TrackedDetection, annotate
from detector.events import Identifier
from detector.main import _RunContext


def _ctx(tmp_path: Path) -> _RunContext:
    return _RunContext(
        source_id="cam-01",
        zone_id="north-gate",
        identifier=Identifier(kind="none"),
        snapshot_base=tmp_path,
        repo_root=tmp_path,
        client=None,  # type: ignore[arg-type] -- naming never touches the socket
        session_date=datetime.now(UTC).date(),
    )


def _ack(serial: str = "SEED000158Q100000") -> dict:
    return {
        "type": "ack",
        "event_id": "e1",
        "decision": "authorized",
        "reason": "authorized for zone north-gate",
        "identity": {
            "method": "explicit",
            "result": "identified",
            "candidates": 1,
            "confidence": 1.0,
        },
        "drone": {
            "serial_number": serial,
            "manufacturer": "DJI",
            "model": "Mavic 3",
            "airframe_type": "quadcopter",
            "owner_name": "Amira Haddad",
        },
    }


def test_annotate_prefers_identified_name_over_class() -> None:
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    dets = [TrackedDetection(class_name="drone", confidence=0.9, bbox=(5, 5, 20, 20), track_id=7)]
    plain = annotate(frame, dets)
    named = annotate(frame, dets, labels={7: "DJI Mavic 3"})
    assert not np.array_equal(plain, named)  # pixels differ: name is drawn
    # Unknown tracks keep the class label; same pixels as no labels at all.
    fallback = annotate(frame, dets, labels={99: "DJI Mavic 3"})
    assert np.array_equal(plain, fallback)


def test_refresh_names_folds_only_new_identified_acks(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.event_tracks["e1"] = 5
    assert ctx.refresh_names({"e1": _ack()}) == 1
    assert ctx.track_names[5] == "DJI Mavic 3"
    assert ctx.refresh_names({"e1": _ack()}) == 0  # seen: not rescanned
    ctx.event_tracks["e2"] = 6
    assert ctx.refresh_names({"e1": _ack(), "e2": {"type": "error"}}) == 0


def test_stamp_identified_writes_name_onto_snapshot(tmp_path: Path) -> None:
    shot = tmp_path / "snap.jpg"
    assert cv2.imwrite(str(shot), np.zeros((60, 200, 3), dtype=np.uint8))
    before = shot.stat().st_size
    ctx = _ctx(tmp_path)
    ctx.emitted["e1"] = shot
    assert ctx.stamp_identified({"e1": _ack()}) == 1
    assert cv2.imread(str(shot)) is not None
    assert shot.stat().st_size != before  # text pixels were added
    # No identified ack -> untouched.
    assert ctx.stamp_identified({"e1": {"type": "error"}}) == 0
