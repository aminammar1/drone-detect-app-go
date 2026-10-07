"""Track dedupe with cooldown (FR-D3, FR-D4).

One event per new `track_id`; the same track re-emits only after
TRACK_COOLDOWN_SECONDS has passed. Comparisons use event time
(`detected_at`), never arrival time. No model or OpenCV here, so this is
fully unit-testable with a fake clock.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Wall clock (production). Tests use a fake."""

    def now(self) -> datetime: ...


class SystemClock:
    """Production clock: real time, always timezone-aware."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class TrackDeduplicator:
    """Remembers the last emission per track; `should_emit` gates events."""

    def __init__(self, cooldown: timedelta, max_tracks: int = 10_000) -> None:
        if cooldown < timedelta(0):
            raise ValueError("cooldown must not be negative")
        self._cooldown = cooldown
        self._max_tracks = max_tracks
        self._last_emission: dict[int, datetime] = {}

    def should_emit(self, track_id: int, at: datetime) -> bool:
        """True on first sighting, or when `cooldown` elapsed since last emit."""
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
        """Number of tracks currently remembered (for logs/tests)."""
        return len(self._last_emission)

    def _prune(self, at: datetime) -> None:
        """Drop tracks quiet for longer than the cooldown (bounded memory)."""
        if len(self._last_emission) <= self._max_tracks:
            return
        quiet_since = at - self._cooldown
        stale = [tid for tid, last in self._last_emission.items() if last <= quiet_since]
        for tid in stale:
            del self._last_emission[tid]
