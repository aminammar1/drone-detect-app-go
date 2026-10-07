"""Track dedupe with cooldown (FR-D3, FR-D4).

Event time only, never arrival time. No CV here, so fake-clock tests stay cheap.
Frames are held by reference only (caller passes an owned copy); no numpy import.
"""

import typing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Production clock; tests inject a fake."""

    def now(self) -> datetime: ...


class SystemClock:
    """Real time, always timezone-aware."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class TrackDeduplicator:
    """Last emission per track; should_emit gates events."""

    def __init__(self, cooldown: timedelta, max_tracks: int = 10_000) -> None:
        if cooldown < timedelta(0):
            raise ValueError("cooldown must not be negative")
        self._cooldown = cooldown
        self._max_tracks = max_tracks
        self._last_emission: dict[int, datetime] = {}

    def should_emit(self, track_id: int, at: datetime) -> bool:
        """First sighting or cooldown elapsed since last emit."""
        if at.tzinfo is None:
            raise ValueError("event time must be timezone-aware")
        last = self._last_emission.get(track_id)
        if last is None or at - last >= self._cooldown:
            self._last_emission[track_id] = at
            self._prune(at)
            return True
        return False

    @property
    def tracked_count(self) -> int:
        """Tracks currently remembered; for logs/tests."""
        return len(self._last_emission)

    def _prune(self, at: datetime) -> None:
        """Drop quiet tracks; bounds memory."""
        if len(self._last_emission) <= self._max_tracks:
            return
        quiet_since = at - self._cooldown
        stale = [tid for tid, last in self._last_emission.items() if last <= quiet_since]
        for tid in stale:
            del self._last_emission[tid]


@dataclass
class TrackSummary:
    """Best detection of one track for the end-of-file summary emit.

    `frame` is the caller-owned best-frame copy (full BGR image, not a crop).
    """

    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]
    frame_index: int
    detected_at: datetime
    frames_seen: int
    first_detected_at: datetime
    # Raw frame array from the best sighting; the caller never mutates it
    # afterwards (cap.read output), so no defensive copy is held per update.
    frame: typing.Any = field(repr=False)


class TrackSummarizer:
    """Best-per-track collector for file sources (one summary emit per drone).

    Live streaming still uses TrackDeduplicator; files wait until the footage
    ends so each drone costs one event, one snapshot, and one sheet row.
    Tracks seen in fewer than `min_frames` frames never emit (FP filter).
    """

    def __init__(self, min_frames: int = 3) -> None:
        if min_frames < 1:
            raise ValueError("min_frames must be >= 1")
        self._min_frames = min_frames
        self._tracks: dict[int, TrackSummary] = {}

    def update(
        self,
        track_id: int,
        *,
        class_name: str,
        confidence: float,
        bbox: tuple[float, float, float, float],
        frame: typing.Any,
        frame_index: int,
        detected_at: datetime,
    ) -> None:
        """Fold one tracked box in; keeps the highest-confidence frame."""
        if detected_at.tzinfo is None:
            raise ValueError("event time must be timezone-aware")
        cur = self._tracks.get(track_id)
        if cur is None:
            self._tracks[track_id] = TrackSummary(
                track_id=track_id,
                class_name=class_name,
                confidence=confidence,
                bbox=bbox,
                frame_index=frame_index,
                detected_at=detected_at,
                frames_seen=1,
                first_detected_at=detected_at,
                frame=frame,
            )
            return
        seen = cur.frames_seen + 1
        if confidence > cur.confidence:
            self._tracks[track_id] = TrackSummary(
                track_id=track_id,
                class_name=class_name,
                confidence=confidence,
                bbox=bbox,
                frame_index=frame_index,
                detected_at=detected_at,
                frames_seen=seen,
                first_detected_at=cur.first_detected_at,
                frame=frame,
            )
        else:
            cur.frames_seen = seen

    def confirmed(self) -> list[TrackSummary]:
        """Tracks seen often enough to emit, oldest first (stable order)."""
        ready = [t for t in self._tracks.values() if t.frames_seen >= self._min_frames]
        ready.sort(key=lambda t: (t.first_detected_at, t.track_id))
        return ready

    @property
    def tracked_count(self) -> int:
        """Distinct tracks observed; for logs/tests."""
        return len(self._tracks)
