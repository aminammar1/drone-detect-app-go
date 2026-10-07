package model

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func validDetection() *Detection {
	return &Detection{
		Type:       MsgDetection,
		EventID:    "b2f4c8a0-6e0b-4c61-9a4e-3a9d7c1f0e11",
		DetectedAt: time.Date(2026, 6, 9, 14, 3, 22, 0, time.UTC),
		Source:     Source{ID: "cam-01", Kind: "video", URI: "videos/test1.mp4"},
		ZoneID:     "north-gate",
		TrackID:    17,
		Class:      "drone",
		Confidence: 0.91,
		BBox:       BBox{X1: 120, Y1: 80, X2: 260, Y2: 170},
		FrameIndex: 1234,
		Identifier: Identifier{Kind: IdentifierNone},
	}
}

func TestDetectionValidate(t *testing.T) {
	tests := []struct {
		name    string
		mutate  func(*Detection)
		wantErr string
	}{
		{name: "valid", mutate: func(*Detection) {}, wantErr: ""},
		{name: "valid with identifier", mutate: func(d *Detection) {
			d.Identifier = Identifier{Kind: IdentifierSerial, Value: "SER1"}
		}, wantErr: ""},
		{name: "wrong type", mutate: func(d *Detection) { d.Type = "beacon" }, wantErr: `type must be "detection"`},
		{name: "missing event_id", mutate: func(d *Detection) { d.EventID = "" }, wantErr: "event_id is required"},
		{name: "missing detected_at", mutate: func(d *Detection) { d.DetectedAt = time.Time{} }, wantErr: "detected_at is required"},
		{name: "missing source", mutate: func(d *Detection) { d.Source.ID = "" }, wantErr: "source.id is required"},
		{name: "missing zone", mutate: func(d *Detection) { d.ZoneID = "" }, wantErr: "zone_id is required"},
		{name: "missing class", mutate: func(d *Detection) { d.Class = "" }, wantErr: "class is required"},
		{name: "confidence too high", mutate: func(d *Detection) { d.Confidence = 1.5 }, wantErr: "confidence must be between 0 and 1"},
		{name: "confidence negative", mutate: func(d *Detection) { d.Confidence = -0.1 }, wantErr: "confidence must be between 0 and 1"},
		{name: "negative track", mutate: func(d *Detection) { d.TrackID = -1 }, wantErr: "track_id must not be negative"},
		{name: "inverted bbox", mutate: func(d *Detection) { d.BBox = BBox{X1: 5, Y1: 5, X2: 5, Y2: 9} }, wantErr: "bbox must have x2 > x1 and y2 > y1"},
		{name: "identifier without value", mutate: func(d *Detection) {
			d.Identifier = Identifier{Kind: IdentifierSerial}
		}, wantErr: `identifier.value is required for kind "serial"`},
		{name: "unknown identifier kind", mutate: func(d *Detection) {
			d.Identifier = Identifier{Kind: "plate", Value: "X"}
		}, wantErr: "identifier.kind must be serial, remote_id, qr, or none"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			d := validDetection()
			tt.mutate(d)
			err := d.Validate()
			if tt.wantErr == "" {
				require.NoError(t, err)
			} else {
				require.EqualError(t, err, tt.wantErr)
			}
		})
	}
}

func TestDetectionNormalize(t *testing.T) {
	d := validDetection()
	d.Identifier = Identifier{}
	d.Normalize()
	assert.Equal(t, IdentifierNone, d.Identifier.Kind)
	require.NoError(t, d.Validate())
}
