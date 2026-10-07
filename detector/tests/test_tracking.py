"""Tests for track dedupe/cooldown (FR-D4): fake clock, no model."""

from datetime import UTC, datetime, timedelta

import pytest

from detector.tracking import SystemClock, TrackDeduplicator

START = datetime(2026, 6, 9, 14, 0, 0, tzinfo=UTC)
COOLDOWN = timedelta(seconds=30)


class FakeClock:
    """Manual clock: event time is fully scripted."""

    def __init__(self, start: datetime = START) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now += timedelta(seconds=seconds)
        return self._now


def test_first_sighting_emits() -> None:
    dedupe = TrackDeduplicator(COOLDOWN)
    assert dedupe.should_emit(1, START) is True


def test_drone_visible_10s_at_30fps_emits_exactly_once() -> None:
    """The M4 acceptance case: 300 frames, one track, one event."""
    dedupe = TrackDeduplicator(COOLDOWN)
    clock = FakeClock()
    count = 0
    for _ in range(300):  # 10 s at 30 FPS
        if dedupe.should_emit(7, clock.now()):
            count += 1
        clock.advance(1 / 30)
    assert count == 1


def test_reemits_after_cooldown() -> None:
    dedupe = TrackDeduplicator(COOLDOWN)
    clock = FakeClock()
    assert dedupe.should_emit(1, clock.now()) is True
    clock.advance(29.9)
    assert dedupe.should_emit(1, clock.now()) is False
    clock.advance(0.1)  # exactly 30 s since the emission
    assert dedupe.should_emit(1, clock.now()) is True


def test_tracks_are_independent() -> None:
    dedupe = TrackDeduplicator(COOLDOWN)
    assert dedupe.should_emit(1, START) is True
    assert dedupe.should_emit(2, START) is True
    assert dedupe.should_emit(1, START) is False
    assert dedupe.tracked_count == 2


def test_zero_cooldown_always_emits() -> None:
    dedupe = TrackDeduplicator(timedelta(0))
    assert dedupe.should_emit(1, START) is True
    assert dedupe.should_emit(1, START) is True


def test_negative_cooldown_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        TrackDeduplicator(timedelta(seconds=-1))


def test_naive_event_time_rejected() -> None:
    dedupe = TrackDeduplicator(COOLDOWN)
    with pytest.raises(ValueError, match="timezone-aware"):
        dedupe.should_emit(1, datetime(2026, 6, 9, 14, 0, 0))  # noqa: DTZ001


def test_system_clock_is_aware() -> None:
    assert SystemClock().now().tzinfo is not None


def test_memory_stays_bounded() -> None:
    dedupe = TrackDeduplicator(COOLDOWN, max_tracks=100)
    for track_id in range(500):
        dedupe.should_emit(track_id, START)
    # All tracks from START are quiet past the cooldown, so they are pruned
    # and only the fresh one remains.
    dedupe.should_emit(9999, START + COOLDOWN + timedelta(seconds=1))
    assert dedupe.tracked_count == 1
