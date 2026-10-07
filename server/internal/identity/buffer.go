package identity

import (
	"sync"
	"time"

	"drone-detect-app/server/internal/model"
)

// bufferedBeacon pairs event-time beacon with wall-clock arrival; retention uses arrival only.
type bufferedBeacon struct {
	model.Beacon
	receivedAt time.Time
}

// Buffer is the process-wide beacon store (FR-S6); writes from /ws/beacons, reads from resolver.
type Buffer struct {
	mu        sync.RWMutex
	beacons   []bufferedBeacon
	retention time.Duration
}

// NewBuffer drops beacons older than retention.
func NewBuffer(retention time.Duration) *Buffer {
	return &Buffer{retention: retention}
}

// Add stores a beacon and prunes expired entries.
func (b *Buffer) Add(beacon model.Beacon, now time.Time) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.beacons = append(b.beacons, bufferedBeacon{Beacon: beacon, receivedAt: now})
	b.pruneLocked(now)
}

// Match correlates by zone and event time; dedupes by serial, closest wins.
func (b *Buffer) Match(zone string, at time.Time, window time.Duration) []model.Beacon {
	b.mu.RLock()
	defer b.mu.RUnlock()
	best := make(map[string]bufferedBeacon)
	for _, cand := range b.beacons {
		if cand.ZoneID != zone {
			continue
		}
		delta := cand.Timestamp.Sub(at)
		if delta < 0 {
			delta = -delta
		}
		if delta > window {
			continue
		}
		prev, seen := best[cand.SerialNumber]
		if !seen || delta < absDuration(prev.Timestamp.Sub(at)) {
			best[cand.SerialNumber] = cand
		}
	}
	out := make([]model.Beacon, 0, len(best))
	for _, cand := range best {
		out = append(out, cand.Beacon)
	}
	return out
}

func (b *Buffer) pruneLocked(now time.Time) {
	kept := b.beacons[:0]
	for _, cand := range b.beacons {
		if now.Sub(cand.receivedAt) <= b.retention {
			kept = append(kept, cand)
		}
	}
	b.beacons = kept
}

func absDuration(d time.Duration) time.Duration {
	if d < 0 {
		return -d
	}
	return d
}
