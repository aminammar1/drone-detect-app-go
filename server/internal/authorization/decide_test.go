package authorization

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.mongodb.org/mongo-driver/v2/bson"

	"drone-detect-app/server/internal/identity"
	"drone-detect-app/server/internal/model"
	"drone-detect-app/server/internal/store"
)

var (
	testAt      = time.Date(2026, 6, 9, 14, 3, 22, 0, time.UTC)
	droneID     = bson.NewObjectID()
	activeDorn  = &model.Drone{ID: droneID, SerialNumber: "SER1", Status: "active"}
	stolenDorn  = &model.Drone{ID: droneID, SerialNumber: "SER2", Status: "stolen"}
	revokedDorn = &model.Drone{ID: droneID, SerialNumber: "SER3", Status: "revoked"}
	openZone    = &model.Zone{ID: "north-gate", RestrictionLevel: "low"}
	noFlyZone   = &model.Zone{ID: "airport-approach", RestrictionLevel: "no-fly"}
	permit      = &model.Authorization{Status: "active"}
)

type fakeZones struct {
	zone *model.Zone
	err  error
}

func (f *fakeZones) FindZoneByID(_ context.Context, _ string) (*model.Zone, error) {
	return f.zone, f.err
}

type fakeAuthorizations struct {
	auth  *model.Authorization
	err   error
	gotAt time.Time
}

func (f *fakeAuthorizations) FindActive(_ context.Context, _ bson.ObjectID, _ string, at time.Time) (*model.Authorization, error) {
	f.gotAt = at
	return f.auth, f.err
}

func identified(drone *model.Drone) identity.Result {
	return identity.Result{Method: model.MethodExplicit, Outcome: model.IdentityIdentified, Drone: drone, Candidates: 1, Confidence: 1}
}

func TestDecide(t *testing.T) {
	ctx := context.Background()
	newDet := func() *model.Detection {
		return &model.Detection{EventID: "e1", DetectedAt: testAt, ZoneID: "north-gate"}
	}
	tests := []struct {
		name         string
		identity     identity.Result
		zone         *model.Zone
		zoneErr      error
		auth         *model.Authorization
		authErr      error
		wantDecision string
		wantReason   string
		wantErr      bool
	}{
		{name: "none", identity: identity.Result{Outcome: model.IdentityNone}, wantDecision: model.DecisionUnidentified, wantReason: "no identifier and no Remote ID broadcast"},
		{name: "ambiguous", identity: identity.Result{Outcome: model.IdentityAmbiguous}, wantDecision: model.DecisionUnidentified, wantReason: "multiple matching drones"},
		{name: "mismatch", identity: identity.Result{Outcome: model.IdentityMismatch}, wantDecision: model.DecisionUnidentified, wantReason: "claimed identity does not match visual attributes (possible spoofing)"},
		{name: "not registered", identity: identified(nil), wantDecision: model.DecisionUnidentified, wantReason: "identifier not registered"},
		{name: "stolen", identity: identified(stolenDorn), zone: openZone, wantDecision: model.DecisionUnauthorized, wantReason: "drone status: stolen"},
		{name: "revoked status", identity: identified(revokedDorn), zone: openZone, wantDecision: model.DecisionUnauthorized, wantReason: "drone status: revoked"},
		{name: "unknown zone", identity: identified(activeDorn), zone: nil, wantDecision: model.DecisionUnauthorized, wantReason: "unknown zone north-gate"},
		{name: "unknown zone via store", identity: identified(activeDorn), zoneErr: store.ErrNotFound, wantDecision: model.DecisionUnauthorized, wantReason: "unknown zone north-gate"},
		{name: "no-fly zone", identity: identified(activeDorn), zone: noFlyZone, wantDecision: model.DecisionUnauthorized, wantReason: "no-fly zone"},
		{name: "authorized", identity: identified(activeDorn), zone: openZone, auth: permit, wantDecision: model.DecisionAuthorized, wantReason: "authorized for zone north-gate"},
		{name: "no authorization", identity: identified(activeDorn), zone: openZone, auth: nil, wantDecision: model.DecisionUnauthorized, wantReason: "no active authorization for zone north-gate"},
		{name: "no authorization via store", identity: identified(activeDorn), zone: openZone, authErr: store.ErrNotFound, wantDecision: model.DecisionUnauthorized, wantReason: "no active authorization for zone north-gate"},
		{name: "zone lookup error", identity: identified(activeDorn), zoneErr: errors.New("db down"), wantErr: true},
		{name: "auth lookup error", identity: identified(activeDorn), zone: openZone, authErr: errors.New("db down"), wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			zones := &fakeZones{zone: tt.zone, err: tt.zoneErr}
			permits := &fakeAuthorizations{auth: tt.auth, err: tt.authErr}
			d := &Decider{Zones: zones, Authorizations: permits}
			got, err := d.Decide(ctx, newDet(), tt.identity)
			if tt.wantErr {
				require.Error(t, err)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantDecision, got.Decision)
			assert.Equal(t, tt.wantReason, got.Reason)
		})
	}
}

// Event time keeps replays deterministic.
func TestDecideUsesEventTime(t *testing.T) {
	permits := &fakeAuthorizations{auth: permit}
	d := &Decider{Zones: &fakeZones{zone: openZone}, Authorizations: permits}
	det := &model.Detection{EventID: "e1", DetectedAt: testAt, ZoneID: "north-gate"}
	_, err := d.Decide(context.Background(), det, identified(activeDorn))
	require.NoError(t, err)
	assert.True(t, permits.gotAt.Equal(testAt), "lookup used %v, want event time %v", permits.gotAt, testAt)
}
