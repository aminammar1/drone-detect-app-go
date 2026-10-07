// Package authz is the authorization decision engine.
// It implements DESCRIPTION.md section 5 in order; the first match wins.
// All time comparisons use the event's detected_at, never server time.
package authz

import (
	"context"
	"errors"
	"fmt"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"

	"drone-detect-app/server/internal/identity"
	"drone-detect-app/server/internal/model"
	"drone-detect-app/server/internal/store"
)

// Decider needs zone and authorization lookups. The identity comes from
// the Resolver (explicit identifier in M2, beacons in M5).
type Decider struct {
	Zones Zones
	Authz Authorizations
}

// Zones finds a zone by ID.
type Zones interface {
	FindZoneByID(ctx context.Context, id string) (*model.Zone, error)
}

// Authorizations finds the active permit for (drone, zone, at).
type Authorizations interface {
	FindActive(ctx context.Context, droneID bson.ObjectID, zoneID string, at time.Time) (*model.Authorization, error)
}

// Outcome is a decision with its human-readable reason.
type Outcome struct {
	Decision string
	Reason   string
	Drone    *model.Drone
}

// Decide evaluates DESCRIPTION.md section 5 rules in order.
// A store failure returns an error; the caller must log it and answer
// "unidentified" (never crash, never authorize on error).
func (d *Decider) Decide(ctx context.Context, det *model.Detection, id identity.Result) (Outcome, error) {
	switch id.Outcome {
	case model.IdentityNone:
		return Outcome{Decision: model.DecisionUnidentified, Reason: "no identifier and no Remote ID broadcast"}, nil
	case model.IdentityAmbiguous:
		return Outcome{Decision: model.DecisionUnidentified, Reason: "multiple matching drones"}, nil
	case model.IdentityMismatch:
		return Outcome{Decision: model.DecisionUnidentified, Reason: "claimed identity does not match visual attributes (possible spoofing)"}, nil
	}
	if id.Drone == nil {
		return Outcome{Decision: model.DecisionUnidentified, Reason: "identifier not registered"}, nil
	}
	drone := id.Drone
	if drone.Status == "stolen" || drone.Status == "revoked" {
		return Outcome{Decision: model.DecisionUnauthorized, Reason: fmt.Sprintf("drone status: %s", drone.Status), Drone: drone}, nil
	}
	zone, err := d.Zones.FindZoneByID(ctx, det.ZoneID)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return Outcome{Decision: model.DecisionUnauthorized, Reason: fmt.Sprintf("unknown zone %s", det.ZoneID), Drone: drone}, nil
		}
		return Outcome{}, fmt.Errorf("zone lookup: %w", err)
	}
	if zone == nil {
		return Outcome{Decision: model.DecisionUnauthorized, Reason: fmt.Sprintf("unknown zone %s", det.ZoneID), Drone: drone}, nil
	}
	if zone.RestrictionLevel == "no-fly" {
		return Outcome{Decision: model.DecisionUnauthorized, Reason: "no-fly zone", Drone: drone}, nil
	}
	auth, err := d.Authz.FindActive(ctx, drone.ID, det.ZoneID, det.DetectedAt)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			auth = nil // normal case: simply no permit
		} else {
			return Outcome{}, fmt.Errorf("authorization lookup: %w", err)
		}
	}
	if auth != nil {
		return Outcome{Decision: model.DecisionAuthorized, Reason: fmt.Sprintf("authorized for zone %s", det.ZoneID), Drone: drone}, nil
	}
	return Outcome{Decision: model.DecisionUnauthorized, Reason: fmt.Sprintf("no active authorization for zone %s", det.ZoneID), Drone: drone}, nil
}

// Ensure Decider works against the Mongo implementation at compile time.
var (
	_ Zones          = (*store.MongoStore)(nil)
	_ Authorizations = (*store.MongoStore)(nil)
)
