// Package export appends one row per detection to a Google Sheet, with a
// local CSV fallback (DESCRIPTION.md section 7). A background Worker batches
// stored detections up to EXPORT_BATCH_SIZE rows or every EXPORT_FLUSH_SECONDS
// and tracks progress in MongoDB via export_status (pending/exported/failed).
package export

import (
	"context"
	"strconv"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"

	"drone-detect-app/server/internal/model"
)

// Export statuses stored on detections (DESCRIPTION.md section 2).
const (
	StatusPending  = "pending"
	StatusExported = "exported"
	StatusFailed   = "failed"
)

// Exporter appends a batch of rows to one sink (a sheet tab or a CSV file).
// Implementations must be safe for use by the worker's single goroutine;
// Append honors ctx cancellation.
type Exporter interface {
	Append(ctx context.Context, rows [][]any) error
}

// DroneLookup resolves a registration by serial for row enrichment.
type DroneLookup interface {
	FindBySerial(ctx context.Context, serial string) (*model.Drone, error)
}

// OwnerLookup resolves an owner name for row enrichment.
type OwnerLookup interface {
	FindByID(ctx context.Context, id bson.ObjectID) (*model.Owner, error)
}

// ExportStore is the worker's narrow MongoDB surface: progress tracking and
// startup re-queue.
type ExportStore interface {
	FindUnexported(ctx context.Context, limit int) ([]*model.StoredDetection, error)
	SetExportStatus(ctx context.Context, eventID, status string) error
}

// Columns is the exact sheet column order (DESCRIPTION.md section 7).
// Change it only together with that section.
var Columns = []string{
	"detected_at",
	"event_id",
	"zone_id",
	"source_id",
	"track_id",
	"confidence",
	"decision",
	"reason",
	"identity_method",
	"serial_number",
	"manufacturer",
	"model",
	"model_version",
	"model_family",
	"airframe_type_seen",
	"airframe_type_registered",
	"category",
	"owner_name",
	"year_sold",
	"snapshot_path",
}

// Row builds one export row in Columns order. drone may be nil (no unique
// drone identified); ownerName is "" when the owner is unknown. Native types
// are kept (Sheets receives numbers, the CSV writer stringifies them).
func Row(doc *model.StoredDetection, drone *model.Drone, ownerName string) []any {
	row := make([]any, 0, len(Columns))
	seen := ""
	if doc.Visual != nil {
		seen = doc.Visual.AirframeType
	}
	serial, maker, mod, modVer, family, registered, category, year := "", "", "", "", "", "", "", ""
	if drone != nil {
		serial = drone.SerialNumber
		maker = drone.Manufacturer
		mod = drone.Model
		modVer = drone.ModelVersion
		family = drone.ModelFamily
		registered = drone.AirframeType
		category = drone.Category
		year = strconv.Itoa(drone.YearSold)
	} else {
		ownerName = ""
	}
	return append(row,
		doc.DetectedAt.UTC().Format(time.RFC3339),
		doc.EventID,
		doc.ZoneID,
		doc.Source.ID,
		doc.TrackID,
		doc.Confidence,
		doc.Decision,
		doc.Reason,
		doc.Identity.Method,
		serial,
		maker,
		mod,
		modVer,
		family,
		seen,
		registered,
		category,
		ownerName,
		year,
		doc.SnapshotPath,
	)
}
