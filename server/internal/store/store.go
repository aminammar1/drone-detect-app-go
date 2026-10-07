// Package store holds the MongoDB repositories behind small interfaces so
// the decision logic can be tested with fakes. See DESCRIPTION.md section 2.
package store

import (
	"context"
	"errors"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"drone-detect-app/server/internal/model"
)

// ErrNotFound is returned when a document does not exist.
var ErrNotFound = errors.New("not found")

// Drones reads drone registrations.
type Drones interface {
	FindBySerial(ctx context.Context, serial string) (*model.Drone, error)
}

// Owners reads owner records.
type Owners interface {
	FindByID(ctx context.Context, id bson.ObjectID) (*model.Owner, error)
}

// Zones reads surveilled areas.
type Zones interface {
	FindZoneByID(ctx context.Context, id string) (*model.Zone, error)
}

// Authorizations reads flight permits. Lookups use event time (detected_at),
// never server time, so replayed videos stay deterministic.
type Authorizations interface {
	FindActive(ctx context.Context, droneID bson.ObjectID, zoneID string, at time.Time) (*model.Authorization, error)
}

// Detections persists detection outcomes. EventID is unique: a resent event
// must return the stored decision instead of inserting a duplicate.
type Detections interface {
	FindByEventID(ctx context.Context, eventID string) (*model.StoredDetection, error)
	Insert(ctx context.Context, doc *model.StoredDetection) error
	// FindUnexported returns detections still needing export (export_status
	// pending or failed), oldest first, for the export worker's startup
	// requeue (DESCRIPTION.md section 7).
	FindUnexported(ctx context.Context, limit int) ([]*model.StoredDetection, error)
	// SetExportStatus records export progress for one detection.
	SetExportStatus(ctx context.Context, eventID, status string) error
}

// MongoStore is the MongoDB implementation of all repository interfaces.
// It holds no globals; wire one per process in main.
type MongoStore struct {
	db *mongo.Database
}

// New returns repositories over db.
func New(db *mongo.Database) *MongoStore {
	return &MongoStore{db: db}
}

// EnsureDetectionIndexes creates the detections indexes (unique event_id,
// plus export_status for the export worker's startup requeue). The seed tool
// creates the full index set; this keeps a fresh DB safe.
func (s *MongoStore) EnsureDetectionIndexes(ctx context.Context) error {
	if _, err := s.db.Collection("detections").Indexes().CreateOne(ctx,
		mongo.IndexModel{Keys: bson.D{{Key: "event_id", Value: 1}}, Options: options.Index().SetUnique(true)}); err != nil {
		return err
	}
	_, err := s.db.Collection("detections").Indexes().CreateOne(ctx,
		mongo.IndexModel{Keys: bson.D{{Key: "export_status", Value: 1}, {Key: "detected_at", Value: 1}}})
	return err
}

// FindBySerial returns the drone with this serial, or ErrNotFound.
func (s *MongoStore) FindBySerial(ctx context.Context, serial string) (*model.Drone, error) {
	var d model.Drone
	if err := s.db.Collection("drones").FindOne(ctx, bson.M{"serial_number": serial}).Decode(&d); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &d, nil
}

// FindByID returns the owner, or ErrNotFound.
func (s *MongoStore) FindByID(ctx context.Context, id bson.ObjectID) (*model.Owner, error) {
	var o model.Owner
	if err := s.db.Collection("owners").FindOne(ctx, bson.M{"_id": id}).Decode(&o); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &o, nil
}

// FindZoneByID returns the zone, or ErrNotFound.
func (s *MongoStore) FindZoneByID(ctx context.Context, id string) (*model.Zone, error) {
	var z model.Zone
	if err := s.db.Collection("zones").FindOne(ctx, bson.M{"_id": id}).Decode(&z); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &z, nil
}

// FindActive returns an active authorization covering (drone, zone, at),
// or ErrNotFound when there is none.
func (s *MongoStore) FindActive(ctx context.Context, droneID bson.ObjectID, zoneID string, at time.Time) (*model.Authorization, error) {
	var a model.Authorization
	filter := bson.M{
		"drone_id":   droneID,
		"zone_id":    zoneID,
		"status":     "active",
		"valid_from": bson.M{"$lte": at},
		"valid_to":   bson.M{"$gte": at},
	}
	opts := options.FindOne().SetSort(bson.D{{Key: "valid_from", Value: -1}})
	if err := s.db.Collection("authorizations").FindOne(ctx, filter, opts).Decode(&a); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &a, nil
}

// FindByEventID returns the stored detection, or ErrNotFound.
func (s *MongoStore) FindByEventID(ctx context.Context, eventID string) (*model.StoredDetection, error) {
	var d model.StoredDetection
	if err := s.db.Collection("detections").FindOne(ctx, bson.M{"event_id": eventID}).Decode(&d); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &d, nil
}

// Insert persists a detection outcome.
func (s *MongoStore) Insert(ctx context.Context, doc *model.StoredDetection) error {
	_, err := s.db.Collection("detections").InsertOne(ctx, doc)
	return err
}

// FindUnexported returns up to limit detections with export_status pending
// or failed, oldest first.
func (s *MongoStore) FindUnexported(ctx context.Context, limit int) ([]*model.StoredDetection, error) {
	opts := options.Find().
		SetSort(bson.D{{Key: "detected_at", Value: 1}}).
		SetLimit(int64(limit))
	cur, err := s.db.Collection("detections").Find(ctx,
		bson.M{"export_status": bson.M{"$in": bson.A{"pending", "failed"}}}, opts)
	if err != nil {
		return nil, err
	}
	defer func() {
		_ = cur.Close(ctx)
	}()
	var docs []*model.StoredDetection
	if err := cur.All(ctx, &docs); err != nil {
		return nil, err
	}
	return docs, nil
}

// SetExportStatus records export progress (pending/exported/failed).
func (s *MongoStore) SetExportStatus(ctx context.Context, eventID, status string) error {
	_, err := s.db.Collection("detections").UpdateOne(ctx,
		bson.M{"event_id": eventID},
		bson.M{"$set": bson.M{"export_status": status}})
	return err
}
