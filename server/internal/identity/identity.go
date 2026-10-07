// Package identity resolves detections per DESCRIPTION.md section 4.
package identity

import (
	"context"
	"errors"

	"drone-detect-app/server/internal/model"
	"drone-detect-app/server/internal/store"
)

// Result is resolver output; unregistered explicit claims keep Serial for the decision step.
type Result struct {
	Method     string
	Outcome    string
	Serial     string
	Drone      *model.Drone
	Candidates int
	Confidence float64
}

// Resolver maps a detection to a Result.
type Resolver interface {
	Resolve(ctx context.Context, det *model.Detection) (Result, error)
}

// Wiring check against MongoStore.
var _ store.Drones = (*store.MongoStore)(nil)

// droneLookup maps serial to registration; unknown serials stay candidates.
func lookupDrone(ctx context.Context, drones store.Drones, serial string) (*model.Drone, error) {
	drone, err := drones.FindBySerial(ctx, serial)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return nil, nil
		}
		return nil, err
	}
	return drone, nil
}
