// Package identity resolves which registered drone (if any) a detection shows.
//
// M5 implements the full resolver from DESCRIPTION.md section 4: explicit
// identifier, beacon correlation by zone and event-time window, and the
// visual cross-check. See resolver.go for the algorithm.
package identity

import (
	"context"
	"errors"

	"drone-detect-app/server/internal/model"
	"drone-detect-app/server/internal/store"
)

// Result is the resolver output: exactly one candidate, none, ambiguous,
// or a visual mismatch. Serial is always the claimed serial when the event
// carries an explicit identifier, even if it is not registered (the
// decision step then reports "identifier not registered"). For beacon
// matches, Serial is set only when exactly one candidate remains.
type Result struct {
	Method     string
	Outcome    string
	Serial     string
	Drone      *model.Drone
	Candidates int
	Confidence float64
}

// Resolver maps a detection to an identity Result.
type Resolver interface {
	Resolve(ctx context.Context, det *model.Detection) (Result, error)
}

// Compile-time check that the store satisfies the resolver's needs.
var _ store.Drones = (*store.MongoStore)(nil)

// droneLookup is the resolver's only database need: serial -> registration.
// A serial with no row is still a candidate (decision: "not registered").
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
