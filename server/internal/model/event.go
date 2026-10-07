// Package model holds shared structs for events, identity, decisions, and
// MongoDB documents. Field names follow DESCRIPTION.md sections 2-3.
package model

import (
	"fmt"
	"time"
)

// Message types on the wire (DESCRIPTION.md section 3).
const (
	MsgDetection = "detection"
	MsgBeacon    = "beacon"
	MsgAck       = "ack"
	MsgError     = "error"
	MsgAlert     = "alert"
)

// Decisions.
const (
	DecisionAuthorized   = "authorized"
	DecisionUnauthorized = "unauthorized"
	DecisionUnidentified = "unidentified"
)

// Identity outcomes produced by the resolver.
const (
	IdentityIdentified = "identified"
	IdentityNone       = "none"
	IdentityAmbiguous  = "ambiguous"
	IdentityMismatch   = "mismatch"
)

// Identity methods.
const (
	MethodExplicit     = "explicit"
	MethodBeacon       = "beacon"
	MethodBeaconVisual = "beacon+visual"
	MethodNone         = "none"
)

// Identifier kinds.
const (
	IdentifierSerial   = "serial"
	IdentifierRemoteID = "remote_id"
	IdentifierQR       = "qr"
	IdentifierNone     = "none"
)

// Envelope carries just the message type so handlers can dispatch.
type Envelope struct {
	Type    string `json:"type"`
	EventID string `json:"event_id,omitempty"`
}

// Source identifies where a detection was seen.
type Source struct {
	ID   string `json:"id" bson:"id"`
	Kind string `json:"kind" bson:"kind"`
	URI  string `json:"uri" bson:"uri"`
}

// BBox is a bounding box in pixels.
type BBox struct {
	X1 float64 `json:"x1" bson:"x1"`
	Y1 float64 `json:"y1" bson:"y1"`
	X2 float64 `json:"x2" bson:"x2"`
	Y2 float64 `json:"y2" bson:"y2"`
}

// Visual holds optional classifier attributes. Absent when the detector
// has no attribute model; the resolver then skips the cross-check.
type Visual struct {
	AirframeType       string  `json:"airframe_type,omitempty" bson:"airframe_type,omitempty"`
	AirframeConfidence float64 `json:"airframe_confidence,omitempty" bson:"airframe_confidence,omitempty"`
	ModelFamily        string  `json:"model_family,omitempty" bson:"model_family,omitempty"`
	ModelConfidence    float64 `json:"model_confidence,omitempty" bson:"model_confidence,omitempty"`
}

// Identifier is an explicit identity claim. Absent means {"kind": "none"}.
type Identifier struct {
	Kind  string `json:"kind" bson:"kind"`
	Value string `json:"value,omitempty" bson:"value,omitempty"`
}

// Detection is a detector-to-server event (DESCRIPTION.md section 3.1).
type Detection struct {
	Type         string     `json:"type" bson:"-"`
	EventID      string     `json:"event_id" bson:"event_id"`
	DetectedAt   time.Time  `json:"detected_at" bson:"detected_at"`
	Source       Source     `json:"source" bson:"source"`
	ZoneID       string     `json:"zone_id" bson:"zone_id"`
	TrackID      int64      `json:"track_id" bson:"track_id"`
	Class        string     `json:"class" bson:"class"`
	Confidence   float64    `json:"confidence" bson:"confidence"`
	BBox         BBox       `json:"bbox" bson:"bbox"`
	FrameIndex   int64      `json:"frame_index" bson:"frame_index"`
	SnapshotPath string     `json:"snapshot_path,omitempty" bson:"snapshot_path,omitempty"`
	Visual       *Visual    `json:"visual,omitempty" bson:"visual,omitempty"`
	Identifier   Identifier `json:"identifier" bson:"identifier"`
}

// Normalize applies documented defaults: a missing identifier is
// {"kind": "none"} (DESCRIPTION.md section 3.1).
func (d *Detection) Normalize() {
	if d.Identifier.Kind == "" {
		d.Identifier.Kind = IdentifierNone
	}
}

// Validate checks schema, required fields, and ranges (FR-S5).
// It never mutates the event; call Normalize first.
func (d *Detection) Validate() error {
	if d.Type != MsgDetection {
		return fmt.Errorf("type must be %q", MsgDetection)
	}
	if d.EventID == "" {
		return fmt.Errorf("event_id is required")
	}
	if d.DetectedAt.IsZero() {
		return fmt.Errorf("detected_at is required")
	}
	if d.Source.ID == "" {
		return fmt.Errorf("source.id is required")
	}
	if d.ZoneID == "" {
		return fmt.Errorf("zone_id is required")
	}
	if d.Class == "" {
		return fmt.Errorf("class is required")
	}
	if d.Confidence < 0 || d.Confidence > 1 {
		return fmt.Errorf("confidence must be between 0 and 1")
	}
	if d.TrackID < 0 {
		return fmt.Errorf("track_id must not be negative")
	}
	if d.FrameIndex < 0 {
		return fmt.Errorf("frame_index must not be negative")
	}
	if d.BBox.X2 <= d.BBox.X1 || d.BBox.Y2 <= d.BBox.Y1 {
		return fmt.Errorf("bbox must have x2 > x1 and y2 > y1")
	}
	switch d.Identifier.Kind {
	case IdentifierSerial, IdentifierRemoteID, IdentifierQR:
		if d.Identifier.Value == "" {
			return fmt.Errorf("identifier.value is required for kind %q", d.Identifier.Kind)
		}
	case IdentifierNone:
	default:
		return fmt.Errorf("identifier.kind must be serial, remote_id, qr, or none")
	}
	return nil
}

// Beacon is a Remote ID broadcast (DESCRIPTION.md section 3.2).
// Beacons live only in the server's in-memory buffer, never in MongoDB.
type Beacon struct {
	Type         string    `json:"type"`
	SerialNumber string    `json:"serial_number"`
	ZoneID       string    `json:"zone_id"`
	Timestamp    time.Time `json:"timestamp"`
	Source       string    `json:"source,omitempty"`
}

// Identity is the resolver output stored on the detection and sent in acks.
type Identity struct {
	Method     string  `json:"method" bson:"method"`
	Result     string  `json:"result" bson:"result"`
	Candidates int     `json:"candidates" bson:"candidates"`
	Confidence float64 `json:"confidence" bson:"confidence"`
}

// DroneInfo is the public drone summary inside ack/alert messages.
type DroneInfo struct {
	SerialNumber string `json:"serial_number" bson:"serial_number"`
	Manufacturer string `json:"manufacturer" bson:"manufacturer"`
	Model        string `json:"model" bson:"model"`
	AirframeType string `json:"airframe_type" bson:"airframe_type"`
	OwnerName    string `json:"owner_name" bson:"owner_name"`
}

// Ack is the server-to-detector reply (DESCRIPTION.md section 3.3).
type Ack struct {
	Type     string     `json:"type"`
	EventID  string     `json:"event_id"`
	Decision string     `json:"decision"`
	Reason   string     `json:"reason"`
	Identity Identity   `json:"identity"`
	Drone    *DroneInfo `json:"drone"`
}

// ErrorMsg is the server-to-detector rejection (section 3.4).
type ErrorMsg struct {
	Type    string `json:"type"`
	EventID string `json:"event_id,omitempty"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

// Alert is broadcast on /ws/alerts: ack fields plus event context (3.5).
type Alert struct {
	Type         string     `json:"type"`
	EventID      string     `json:"event_id"`
	DetectedAt   time.Time  `json:"detected_at"`
	ZoneID       string     `json:"zone_id"`
	Confidence   float64    `json:"confidence"`
	SnapshotPath string     `json:"snapshot_path,omitempty"`
	Decision     string     `json:"decision"`
	Reason       string     `json:"reason"`
	Identity     Identity   `json:"identity"`
	Drone        *DroneInfo `json:"drone"`
}
