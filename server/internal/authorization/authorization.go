// Package authorization implements DESCRIPTION.md section 5; first match wins on event time.
package authorization

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

// Decider checks permits; identity is resolver output.
type Decider struct {
	Zones          Zones
	Authorizations Authorizations
}

// Zones looks up a zone by ID.
type Zones interface {
	FindZoneByID(ctx context.Context, id string) (*model.Zone, error)
}

// Authorizations finds the covering permit for (drone, zone, at).
type Authorizations interface {
	FindActive(ctx context.Context, droneID bson.ObjectID, zoneID string, at time.Time) (*model.Authorization, error)
}

// Outcome pairs a decision with its reason.
type Outcome struct {
	Decision string
	Reason   string
	Drone    *model.Drone
}

// Decide applies DESCRIPTION.md section 5 in order; store errors fail closed to unidentified.
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
	auth, err := d.Authorizations.FindActive(ctx, drone.ID, det.ZoneID, det.DetectedAt)
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

// Wiring check against MongoStore.
var (
	_ Zones          = (*store.MongoStore)(nil)
	_ Authorizations = (*store.MongoStore)(nil)
)
