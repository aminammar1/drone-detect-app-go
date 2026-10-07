package identity

import (
	"context"
	"strings"
	"time"

	"drone-detect-app/server/internal/model"
	"drone-detect-app/server/internal/store"
)

// Explicit claims outrank radio; ambiguity/mismatch carry no confidence.
const (
	confidenceExplicit  = 1.0
	confidenceBeacon    = 0.9
	confidenceAmbiguous = 0.5
)

const gracePollInterval = 50 * time.Millisecond

// Correlator implements DESCRIPTION.md section 4; never uses track_id as identity.
type Correlator struct {
	Drones store.Drones
	Buffer *Buffer
	// Window bounds |beacon.timestamp - detected_at|.
	Window time.Duration
	// Grace delays none so late beacons still correlate.
	Grace time.Duration
	// VisualMinConf ignores weak visual evidence.
	VisualMinConf float64
}

// Resolve maps a detection to a Result.
func (r *Correlator) Resolve(ctx context.Context, det *model.Detection) (Result, error) {
	// Explicit claims short-circuit beacons.
	if det.Identifier.Kind != model.IdentifierNone && det.Identifier.Value != "" {
		drone, err := lookupDrone(ctx, r.Drones, det.Identifier.Value)
		if err != nil {
			return Result{}, err
		}
		return Result{
			Method: model.MethodExplicit, Outcome: model.IdentityIdentified,
			Serial: det.Identifier.Value, Drone: drone, Candidates: 1,
			Confidence: confidenceExplicit,
		}, nil
	}

	// Beacon candidates share zone and event-time window.
	candidates := r.Buffer.Match(det.ZoneID, det.DetectedAt, r.Window)
	if len(candidates) == 0 && r.Grace > 0 {
		candidates = r.waitForLateBeacon(ctx, det)
	}
	// No candidates means visible but silent.
	if len(candidates) == 0 {
		if err := ctx.Err(); err != nil {
			return Result{}, err
		}
		return Result{Method: model.MethodBeacon, Outcome: model.IdentityNone}, nil
	}

	drones := make([]*model.Drone, len(candidates))
	for i, cand := range candidates {
		drone, err := lookupDrone(ctx, r.Drones, cand.SerialNumber)
		if err != nil {
			return Result{}, err
		}
		drones[i] = drone
	}

	// Cross-check only on confident visual.
	if usableVisual(det.Visual, r.VisualMinConf) {
		return r.crossCheck(det, candidates, drones), nil
	}
	return r.fromCandidates(candidates, drones, model.MethodBeacon), nil
}

// waitForLateBeacon waits for event-time beacons that arrive late.
func (r *Correlator) waitForLateBeacon(ctx context.Context, det *model.Detection) []model.Beacon {
	deadline := time.Now().Add(r.Grace)
	for {
		if candidates := r.Buffer.Match(det.ZoneID, det.DetectedAt, r.Window); len(candidates) > 0 {
			return candidates
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return nil
		}
		wait := gracePollInterval
		if wait > remaining {
			wait = remaining
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(wait):
		}
	}
}

// usableVisual gates the cross-check per DESCRIPTION.md section 4 rule 3.
func usableVisual(v *model.Visual, minConf float64) bool {
	return v != nil && v.AirframeType != "" && v.AirframeConfidence >= minConf
}

// crossCheck filters by visual; unregistered serials survive for the decision step.
func (r *Correlator) crossCheck(det *model.Detection, candidates []model.Beacon, drones []*model.Drone) Result {
	if len(candidates) == 1 {
		if drones[0] != nil && !compatible(det.Visual, drones[0], r.VisualMinConf) {
			return Result{
				Method: model.MethodBeaconVisual, Outcome: model.IdentityMismatch,
				Serial: candidates[0].SerialNumber, Candidates: 1,
			}
		}
		return Result{
			Method: model.MethodBeacon, Outcome: model.IdentityIdentified,
			Serial: candidates[0].SerialNumber, Drone: drones[0], Candidates: 1,
			Confidence: confidenceBeacon,
		}
	}
	keptBeacons := candidates[:0]
	keptDrones := drones[:0]
	for i, cand := range candidates {
		if drones[i] == nil || compatible(det.Visual, drones[i], r.VisualMinConf) {
			keptBeacons = append(keptBeacons, cand)
			keptDrones = append(keptDrones, drones[i])
		}
	}
	switch len(keptBeacons) {
	case 0:
		// All claims contradict the camera.
		return Result{
			Method: model.MethodBeaconVisual, Outcome: model.IdentityMismatch,
			Candidates: len(candidates),
		}
	case 1:
		return Result{
			Method: model.MethodBeaconVisual, Outcome: model.IdentityIdentified,
			Serial: keptBeacons[0].SerialNumber, Drone: keptDrones[0], Candidates: 1,
			Confidence: confidenceBeacon,
		}
	default:
		return Result{
			Method: model.MethodBeaconVisual, Outcome: model.IdentityAmbiguous,
			Candidates: len(keptBeacons), Confidence: confidenceAmbiguous,
		}
	}
}

// fromCandidates resolves without visual: one is identified, many is ambiguous.
func (r *Correlator) fromCandidates(candidates []model.Beacon, drones []*model.Drone, method string) Result {
	if len(candidates) == 1 {
		return Result{
			Method: method, Outcome: model.IdentityIdentified,
			Serial: candidates[0].SerialNumber, Drone: drones[0], Candidates: 1,
			Confidence: confidenceBeacon,
		}
	}
	return Result{
		Method: method, Outcome: model.IdentityAmbiguous,
		Candidates: len(candidates), Confidence: confidenceAmbiguous,
	}
}

// compatible exact-matches airframe; family is case-insensitive when confident.
func compatible(v *model.Visual, drone *model.Drone, minConf float64) bool {
	if v.AirframeType != drone.AirframeType {
		return false
	}
	if v.ModelFamily == "" || drone.ModelFamily == "" || v.ModelConfidence < minConf {
		return true
	}
	return strings.EqualFold(v.ModelFamily, drone.ModelFamily)
}
