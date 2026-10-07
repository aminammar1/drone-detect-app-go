package identity

import (
	"context"
	"strings"
	"time"

	"drone-detect-app/server/internal/model"
	"drone-detect-app/server/internal/store"
)

// Identification confidence for resolved matches. Explicit claims outrank
// radio correlation; ambiguity and mismatch carry no confidence.
const (
	confidenceExplicit  = 1.0
	confidenceBeacon    = 0.9
	confidenceAmbiguous = 0.5
)

// gracePollInterval is how often a grace wait rechecks the buffer.
const gracePollInterval = 50 * time.Millisecond

// Correlator is the DESCRIPTION.md section 4 resolver: explicit identifier,
// then beacon correlation by zone and event-time window, then the visual
// cross-check. It never uses track_id as identity.
type Correlator struct {
	Drones store.Drones
	Buffer *Buffer
	// Window is BEACON_WINDOW_S: |beacon.timestamp - detected_at| bound.
	Window time.Duration
	// Grace is RESOLVE_GRACE_MS: how long to wait for a late beacon before
	// finalizing "none". Applies only when no beacon matches yet.
	Grace time.Duration
	// VisualMinConf is VISUAL_MIN_CONF: visual evidence below it is ignored.
	VisualMinConf float64
}

// Resolve maps one detection to an identity Result.
func (r *Correlator) Resolve(ctx context.Context, det *model.Detection) (Result, error) {
	// Step 1 (explicit): an identifier claim short-circuits beacons.
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

	// Step 1 (beacon): same zone, event-time window, one entry per serial.
	candidates := r.Buffer.Match(det.ZoneID, det.DetectedAt, r.Window)
	if len(candidates) == 0 && r.Grace > 0 {
		candidates = r.waitForLateBeacon(ctx, det)
	}
	// Step 2: no candidates -> none (rogue: visible, not broadcasting).
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

	// Step 3: visual cross-check, only with confident attributes.
	if usableVisual(det.Visual, r.VisualMinConf) {
		return r.crossCheck(det, candidates, drones), nil
	}
	return r.fromCandidates(candidates, drones, model.MethodBeacon), nil
}

// waitForLateBeacon polls the buffer until a beacon arrives or the grace
// period (or context) expires. Late beacons carry event-time timestamps, so
// they still correlate by detected_at when they show up in time.
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

// usableVisual reports whether the detection carries visual evidence worth
// checking (FR-D8, DESCRIPTION.md section 4 rule 3).
func usableVisual(v *model.Visual, minConf float64) bool {
	return v != nil && v.AirframeType != "" && v.AirframeConfidence >= minConf
}

// crossCheck applies the visual filter over beacon candidates:
// compatible registrations survive; a lone incompatible registration is a
// mismatch (possible spoofing). Serials with no DB row are never filtered
// here — the decision step reports them as "not registered".
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
		// Every claimed identity contradicts what the camera saw.
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

// fromCandidates resolves without visual evidence: one left is identified,
// more than one is ambiguous.
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

// compatible compares seen attributes against the registration:
// airframe_type is an exact match; model_family is case-insensitive and
// only counts when the detection is confident about it.
func compatible(v *model.Visual, drone *model.Drone, minConf float64) bool {
	if v.AirframeType != drone.AirframeType {
		return false
	}
	if v.ModelFamily == "" || drone.ModelFamily == "" || v.ModelConfidence < minConf {
		return true
	}
	return strings.EqualFold(v.ModelFamily, drone.ModelFamily)
}
