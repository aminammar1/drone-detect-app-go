// Package model defines MongoDB documents; DESCRIPTION.md section 2.
package model

import (
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

// Drone is a drones row.
type Drone struct {
	ID               bson.ObjectID `bson:"_id,omitempty"`
	SerialNumber     string        `bson:"serial_number"`
	Manufacturer     string        `bson:"manufacturer"`
	Model            string        `bson:"model"`
	ModelVersion     string        `bson:"model_version"`
	ModelFamily      string        `bson:"model_family"`
	AirframeType     string        `bson:"airframe_type"`
	Category         string        `bson:"category"`
	WeightG          int           `bson:"weight_g"`
	Color            string        `bson:"color"`
	OwnerID          bson.ObjectID `bson:"owner_id"`
	YearManufactured int           `bson:"year_manufactured"`
	YearSold         int           `bson:"year_sold"`
	Status           string        `bson:"status"`
	RemoteIDEnabled  bool          `bson:"remote_id_enabled"`
	CreatedAt        time.Time     `bson:"created_at"`
}

// Owner is an owners row.
type Owner struct {
	ID        bson.ObjectID `bson:"_id,omitempty"`
	Name      string        `bson:"name"`
	Type      string        `bson:"type"`
	Email     string        `bson:"email"`
	Country   string        `bson:"country"`
	CreatedAt time.Time     `bson:"created_at"`
}

// Zone is a surveilled area keyed by string ID.
type Zone struct {
	ID               string   `bson:"_id"`
	Name             string   `bson:"name"`
	Description      string   `bson:"description"`
	RestrictionLevel string   `bson:"restriction_level"`
	CameraIDs        []string `bson:"camera_ids"`
}

// Authorization permits a drone in a zone over a range.
type Authorization struct {
	ID        bson.ObjectID `bson:"_id,omitempty"`
	DroneID   bson.ObjectID `bson:"drone_id"`
	ZoneID    string        `bson:"zone_id"`
	ValidFrom time.Time     `bson:"valid_from"`
	ValidTo   time.Time     `bson:"valid_to"`
	Purpose   string        `bson:"purpose"`
	IssuedBy  string        `bson:"issued_by"`
	Status    string        `bson:"status"`
}

// StoredDetection persists identity+decision; DESCRIPTION.md section 2.
type StoredDetection struct {
	ID           bson.ObjectID  `bson:"_id,omitempty"`
	EventID      string         `bson:"event_id"`
	DetectedAt   time.Time      `bson:"detected_at"`
	ReceivedAt   time.Time      `bson:"received_at"`
	Source       Source         `bson:"source"`
	ZoneID       string         `bson:"zone_id"`
	TrackID      int64          `bson:"track_id"`
	Class        string         `bson:"class"`
	Confidence   float64        `bson:"confidence"`
	BBox         BBox           `bson:"bbox"`
	FrameIndex   int64          `bson:"frame_index"`
	SnapshotPath string         `bson:"snapshot_path,omitempty"`
	Visual       *Visual        `bson:"visual,omitempty"`
	Identifier   Identifier     `bson:"identifier"`
	Identity     Identity       `bson:"identity"`
	DroneID      *bson.ObjectID `bson:"drone_id,omitempty"`
	Drone        *DroneInfo     `bson:"drone,omitempty"`
	Decision     string         `bson:"decision"`
	Reason       string         `bson:"reason"`
	ExportStatus string         `bson:"export_status"`
}
