package export

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"go.mongodb.org/mongo-driver/v2/bson"

	"drone-detect-app/server/internal/model"
)

func testDoc(eventID string) *model.StoredDetection {
	return &model.StoredDetection{
		EventID:    eventID,
		DetectedAt: time.Date(2026, 6, 9, 14, 3, 22, 418000000, time.UTC),
		Source:     model.Source{ID: "cam-01", Kind: "video", URI: "videos/test1.mp4"},
		ZoneID:     "north-gate",
		TrackID:    17,
		Class:      "drone",
		Confidence: 0.91,
		Identity:   model.Identity{Method: model.MethodBeaconVisual, Result: "identified", Candidates: 1, Confidence: 0.9},
		Visual:     &model.Visual{AirframeType: "quadcopter", AirframeConfidence: 0.88, ModelFamily: "Mavic", ModelConfidence: 0.61},
		Decision:   model.DecisionUnauthorized,
		Reason:     "no active authorization for zone north-gate",
		Drone: &model.DroneInfo{
			SerialNumber: "1581F5FJC231Q0012345", Manufacturer: "DJI",
			Model: "Mavic 3", AirframeType: "quadcopter", OwnerName: "Amira Haddad",
		},
		SnapshotPath: "data/snapshots/2026-06-09/b2f4c8a0.jpg",
		ExportStatus: StatusPending,
	}
}

func testDrone() *model.Drone {
	return &model.Drone{
		ID: bson.NewObjectID(), SerialNumber: "1581F5FJC231Q0012345",
		Manufacturer: "DJI", Model: "Mavic 3", ModelVersion: "v2",
		ModelFamily: "Mavic", AirframeType: "quadcopter", Category: "consumer",
		OwnerID: bson.NewObjectID(), YearSold: 2024,
	}
}

func TestColumnsExactOrder(t *testing.T) {
	require.Len(t, Columns, 22)
	require.Equal(t, "Time", Columns[0])
	require.Equal(t, "Method", Columns[8])
	require.Equal(t, "Visual model", Columns[14])
	require.Equal(t, "Visual conf", Columns[15])
	require.Equal(t, "Seen", Columns[16])
	require.Equal(t, "Registered", Columns[17])
	require.Equal(t, "Snapshot", Columns[21])
}

func TestRowFull(t *testing.T) {
	drone := testDrone()
	got := Row(testDoc("e1"), drone, "Amira Haddad")
	require.Len(t, got, len(Columns))
	require.Equal(t, []any{
		"2026-06-09 14:03:22",
		"e1",
		"north-gate",
		"cam-01",
		int64(17),
		0.91,
		"unauthorized",
		"no active authorization for zone north-gate",
		"beacon+visual",
		"1581F5FJC231Q0012345",
		"DJI",
		"Mavic 3",
		"v2",
		"Mavic",
		"Mavic", // visual family prediction
		0.61,
		"quadcopter", // seen
		"quadcopter", // registered
		"consumer",
		"Amira Haddad",
		"2024",
		"data/snapshots/2026-06-09/b2f4c8a0.jpg",
	}, got)
}

func TestRowNoDroneNoVisual(t *testing.T) {
	doc := testDoc("e2")
	doc.Visual = nil
	doc.Drone = nil
	got := Row(doc, nil, "Ghost")
	require.Len(t, got, len(Columns))
	// Registration cells stay empty when unidentified.
	require.Equal(t, "beacon+visual", got[8])
	for _, i := range []int{9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20} {
		require.Equal(t, "", got[i], "column %s", Columns[i])
	}
	require.Equal(t, "e2", got[1])
}
