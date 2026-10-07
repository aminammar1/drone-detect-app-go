package identity

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"drone-detect-app/server/internal/model"
	"drone-detect-app/server/internal/store"
)

// fakeDrones serves a map; missing serials are unregistered.
type fakeDrones struct {
	bySerial map[string]*model.Drone
}

func (f *fakeDrones) FindBySerial(_ context.Context, serial string) (*model.Drone, error) {
	if d, ok := f.bySerial[serial]; ok {
		return d, nil
	}
	return nil, store.ErrNotFound
}

var (
	quadAnafi = &model.Drone{SerialNumber: "QUAD-1", AirframeType: "quadcopter", ModelFamily: "Anafi"}
	quadMavic = &model.Drone{SerialNumber: "QUAD-2", AirframeType: "quadcopter", ModelFamily: "Mavic"}
	wingDisco = &model.Drone{SerialNumber: "WING-1", AirframeType: "fixed_wing", ModelFamily: "Disco"}
)

func testSetup() (*fakeDrones, *Buffer, time.Time) {
	drones := &fakeDrones{bySerial: map[string]*model.Drone{
		"QUAD-1": quadAnafi, "QUAD-2": quadMavic, "WING-1": wingDisco,
	}}
	at := time.Date(2026, 6, 9, 14, 0, 10, 0, time.UTC)
	return drones, NewBuffer(time.Minute), at
}

func addBeacon(buf *Buffer, serial, zone string, at time.Time) {
	buf.Add(model.Beacon{
		Type: "beacon", SerialNumber: serial, ZoneID: zone,
		Timestamp: at, Source: "test",
	}, time.Now())
}

func detection(zone string, at time.Time) *model.Detection {
	return &model.Detection{
		Type: "detection", EventID: "e1", DetectedAt: at,
		ZoneID: zone, Identifier: model.Identifier{Kind: model.IdentifierNone},
	}
}

func visual(airframe, family string, airConf, modelConf float64) *model.Visual {
	return &model.Visual{
		AirframeType: airframe, AirframeConfidence: airConf,
		ModelFamily: family, ModelConfidence: modelConf,
	}
}

func TestCorrelator(t *testing.T) {
	window := 3 * time.Second
	newResolver := func(drones *fakeDrones, buf *Buffer) *Correlator {
		return &Correlator{Drones: drones, Buffer: buf, Window: window}
	}

	t.Run("one beacon match", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "north-gate", at)
		got, err := newResolver(drones, buf).Resolve(context.Background(), detection("north-gate", at))
		require.NoError(t, err)
		require.Equal(t, Result{
			Method: model.MethodBeacon, Outcome: model.IdentityIdentified,
			Serial: "QUAD-1", Drone: quadAnafi, Candidates: 1, Confidence: confidenceBeacon,
		}, got)
	})

	t.Run("no beacon is rogue", func(t *testing.T) {
		drones, buf, at := testSetup()
		got, err := newResolver(drones, buf).Resolve(context.Background(), detection("north-gate", at))
		require.NoError(t, err)
		require.Equal(t, model.IdentityNone, got.Outcome)
		require.Equal(t, model.MethodBeacon, got.Method)
	})

	t.Run("two beacons disambiguated by visual", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "north-gate", at)
		addBeacon(buf, "WING-1", "north-gate", at)
		det := detection("north-gate", at)
		det.Visual = visual("quadcopter", "Anafi", 0.88, 0.61)
		got, err := newResolver(drones, buf).Resolve(context.Background(), det)
		require.NoError(t, err)
		require.Equal(t, model.IdentityIdentified, got.Outcome)
		require.Equal(t, model.MethodBeaconVisual, got.Method)
		require.Equal(t, "QUAD-1", got.Serial)
		require.Equal(t, 1, got.Candidates)
	})

	t.Run("two beacons not disambiguated is ambiguous", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "north-gate", at)
		addBeacon(buf, "QUAD-2", "north-gate", at)
		det := detection("north-gate", at)
		det.Visual = visual("quadcopter", "", 0.88, 0)
		got, err := newResolver(drones, buf).Resolve(context.Background(), det)
		require.NoError(t, err)
		require.Equal(t, model.IdentityAmbiguous, got.Outcome)
		require.Equal(t, 2, got.Candidates)
	})

	t.Run("visual mismatch is spoofer", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "north-gate", at)
		det := detection("north-gate", at)
		det.Visual = visual("fixed_wing", "Disco", 0.9, 0.7)
		got, err := newResolver(drones, buf).Resolve(context.Background(), det)
		require.NoError(t, err)
		require.Equal(t, model.IdentityMismatch, got.Outcome)
		require.Equal(t, model.MethodBeaconVisual, got.Method)
	})

	t.Run("beacon outside the time window is ignored", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "north-gate", at.Add(-10*time.Second))
		addBeacon(buf, "QUAD-1", "north-gate", at.Add(10*time.Second))
		got, err := newResolver(drones, buf).Resolve(context.Background(), detection("north-gate", at))
		require.NoError(t, err)
		require.Equal(t, model.IdentityNone, got.Outcome)
	})

	t.Run("beacon from another zone is ignored", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "warehouse-yard", at)
		got, err := newResolver(drones, buf).Resolve(context.Background(), detection("north-gate", at))
		require.NoError(t, err)
		require.Equal(t, model.IdentityNone, got.Outcome)
	})

	t.Run("explicit identifier overrides beacons", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "north-gate", at)
		addBeacon(buf, "WING-1", "north-gate", at)
		det := detection("north-gate", at)
		det.Identifier = model.Identifier{Kind: model.IdentifierSerial, Value: "WING-1"}
		got, err := newResolver(drones, buf).Resolve(context.Background(), det)
		require.NoError(t, err)
		require.Equal(t, model.MethodExplicit, got.Method)
		require.Equal(t, model.IdentityIdentified, got.Outcome)
		require.Equal(t, "WING-1", got.Serial)
		require.Same(t, wingDisco, got.Drone)
	})

	t.Run("explicit unregistered serial stays a claim", func(t *testing.T) {
		drones, buf, at := testSetup()
		det := detection("north-gate", at)
		det.Identifier = model.Identifier{Kind: model.IdentifierSerial, Value: "NOPE-1"}
		got, err := newResolver(drones, buf).Resolve(context.Background(), det)
		require.NoError(t, err)
		require.Equal(t, model.MethodExplicit, got.Method)
		require.Equal(t, model.IdentityIdentified, got.Outcome)
		require.Equal(t, "NOPE-1", got.Serial)
		require.Nil(t, got.Drone)
	})

	t.Run("unregistered beacon serial stays a candidate", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "NOPE-1", "north-gate", at)
		got, err := newResolver(drones, buf).Resolve(context.Background(), detection("north-gate", at))
		require.NoError(t, err)
		require.Equal(t, model.IdentityIdentified, got.Outcome)
		require.Equal(t, "NOPE-1", got.Serial)
		require.Nil(t, got.Drone)
	})

	t.Run("low confidence visual is skipped", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "north-gate", at)
		addBeacon(buf, "QUAD-2", "north-gate", at)
		det := detection("north-gate", at)
		det.Visual = visual("fixed_wing", "", 0.2, 0) // Too weak to count.
		r := newResolver(drones, buf)
		r.VisualMinConf = 0.5
		got, err := r.Resolve(context.Background(), det)
		require.NoError(t, err)
		require.Equal(t, model.IdentityAmbiguous, got.Outcome)
		require.Equal(t, model.MethodBeacon, got.Method)
	})

	t.Run("compatible visual keeps beacon method", func(t *testing.T) {
		drones, buf, at := testSetup()
		addBeacon(buf, "QUAD-1", "north-gate", at)
		det := detection("north-gate", at)
		det.Visual = visual("quadcopter", "anafi", 0.88, 0.61) // Family is case-insensitive.
		got, err := newResolver(drones, buf).Resolve(context.Background(), det)
		require.NoError(t, err)
		require.Equal(t, model.IdentityIdentified, got.Outcome)
		require.Equal(t, model.MethodBeacon, got.Method)
	})
}

func TestCorrelatorLateBeacon(t *testing.T) {
	t.Run("beacon arriving inside the grace period resolves", func(t *testing.T) {
		drones, buf, at := testSetup()
		r := &Correlator{
			Drones: drones, Buffer: buf,
			Window: 3 * time.Second, Grace: 2 * time.Second,
		}
		go func() {
			time.Sleep(100 * time.Millisecond)
			addBeacon(buf, "QUAD-1", "north-gate", at)
		}()
		got, err := r.Resolve(context.Background(), detection("north-gate", at))
		require.NoError(t, err)
		require.Equal(t, model.IdentityIdentified, got.Outcome)
		require.Equal(t, "QUAD-1", got.Serial)
	})

	t.Run("beacon arriving after the grace period is too late", func(t *testing.T) {
		drones, buf, at := testSetup()
		r := &Correlator{
			Drones: drones, Buffer: buf,
			Window: 3 * time.Second, Grace: 100 * time.Millisecond,
		}
		go func() {
			time.Sleep(500 * time.Millisecond)
			addBeacon(buf, "QUAD-1", "north-gate", at)
		}()
		got, err := r.Resolve(context.Background(), detection("north-gate", at))
		require.NoError(t, err)
		require.Equal(t, model.IdentityNone, got.Outcome)
	})
}

func TestBufferMatchDedupesBySerial(t *testing.T) {
	_, buf, at := testSetup()
	addBeacon(buf, "QUAD-1", "north-gate", at.Add(-time.Second))
	addBeacon(buf, "QUAD-1", "north-gate", at.Add(time.Second))
	addBeacon(buf, "QUAD-2", "north-gate", at)
	got := buf.Match("north-gate", at, 3*time.Second)
	require.Len(t, got, 2)
}
