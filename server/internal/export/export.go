// Package export appends rows to Sheets with CSV fallback; DESCRIPTION.md section 7.
package export

import (
	"context"
	"strconv"

	"go.mongodb.org/mongo-driver/v2/bson"

	"drone-detect-app/server/internal/model"
)

// Export statuses mirror detections.export_status; DESCRIPTION.md section 2.
const (
	StatusPending  = "pending"
	StatusExported = "exported"
	StatusFailed   = "failed"
)

// Exporter appends a batch; single-goroutine use, honors cancellation.
type Exporter interface {
	Append(ctx context.Context, rows [][]any) error
}

// DroneLookup resolves a serial for row enrichment.
type DroneLookup interface {
	FindBySerial(ctx context.Context, serial string) (*model.Drone, error)
}

// OwnerLookup resolves an owner name for row enrichment.
type OwnerLookup interface {
	FindByID(ctx context.Context, id bson.ObjectID) (*model.Owner, error)
}

// ExportStore tracks progress and requeues unfinished exports.
type ExportStore interface {
	FindUnexported(ctx context.Context, limit int) ([]*model.StoredDetection, error)
	SetExportStatus(ctx context.Context, eventID, status string) error
}

// Columns is the sheet order; keep in sync with DESCRIPTION.md section 7.
var Columns = []string{
	"Time",
	"Event",
	"Zone",
	"Camera",
	"Track",
	"Conf",
	"Decision",
	"Reason",
	"Method",
	"Serial",
	"Maker",
	"Model",
	"Version",
	"Family",
	"Visual model",
	"Visual conf",
	"Seen",
	"Registered",
	"Category",
	"Owner",
	"Sold",
	"Snapshot",
}

// humanTime is UTC; Sheets parses it as datetime.
const humanTime = "2006-01-02 15:04:05"

// Row builds a Columns-ordered row; nil drone yields empty registration cells.
func Row(doc *model.StoredDetection, drone *model.Drone, ownerName string) []any {
	row := make([]any, 0, len(Columns))
	seen, visualModel, visualConf := "", "", any("")
	if doc.Visual != nil {
		seen = doc.Visual.AirframeType
		visualModel = doc.Visual.ModelFamily
		if doc.Visual.ModelFamily != "" {
			visualConf = doc.Visual.ModelConfidence
		}
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
		doc.DetectedAt.UTC().Format(humanTime),
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
		visualModel,
		visualConf,
		seen,
		registered,
		category,
		ownerName,
		year,
		doc.SnapshotPath,
	)
}
