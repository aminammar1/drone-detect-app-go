package identity

import (
	"sync"
	"time"

	"drone-detect-app/server/internal/model"
)

// bufferedBeacon is a beacon plus its arrival time. Retention is measured
// from arrival (wall clock): correlation itself always uses the beacon's
// event-time `timestamp`, so preloaded scenario beacons stay usable for the
// whole demo while the buffer still forgets stale radio traffic.
type bufferedBeacon struct {
	model.Beacon
	receivedAt time.Time
}

// Buffer is the in-memory Remote ID beacon store (FR-S6). One per process,
// shared by the /ws/beacons handler (writes) and the resolver (reads).
type Buffer struct {
	mu        sync.RWMutex
	beacons   []bufferedBeacon
	retention time.Duration
}

// NewBuffer returns a buffer that drops beacons older than retention.
func NewBuffer(retention time.Duration) *Buffer {
	return &Buffer{retention: retention}
}

// Add stores a beacon and prunes entries past the retention window.
func (b *Buffer) Add(beacon model.Beacon, now time.Time) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.beacons = append(b.beacons, bufferedBeacon{Beacon: beacon, receivedAt: now})
	b.pruneLocked(now)
}

// Match returns beacons in zone whose event-time timestamp is within window
// of at, deduplicated by serial (closest timestamp wins ties by arrival).
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

// pruneLocked drops beacons received longer ago than the retention window.
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
