// Package store hides Mongo behind interfaces for fakes; DESCRIPTION.md section 2.
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

// ErrNotFound signals a missing document.
var ErrNotFound = errors.New("not found")

// Drones reads registrations.
type Drones interface {
	FindBySerial(ctx context.Context, serial string) (*model.Drone, error)
}

// Owners reads owners.
type Owners interface {
	FindByID(ctx context.Context, id bson.ObjectID) (*model.Owner, error)
}

// Zones reads zones.
type Zones interface {
	FindZoneByID(ctx context.Context, id string) (*model.Zone, error)
}

// Authorizations reads permits by event time so replays stay deterministic.
type Authorizations interface {
	FindActive(ctx context.Context, droneID bson.ObjectID, zoneID string, at time.Time) (*model.Authorization, error)
}

// Detections persists outcomes; event_id is unique for idempotent resends.
type Detections interface {
	FindByEventID(ctx context.Context, eventID string) (*model.StoredDetection, error)
	Insert(ctx context.Context, doc *model.StoredDetection) error
	// FindUnexported returns pending/failed oldest-first for startup requeue.
	FindUnexported(ctx context.Context, limit int) ([]*model.StoredDetection, error)
	// SetExportStatus records export progress.
	SetExportStatus(ctx context.Context, eventID, status string) error
}

// MongoStore implements all repositories; wire one per process.
type MongoStore struct {
	db *mongo.Database
}

// New wraps db.
func New(db *mongo.Database) *MongoStore {
	return &MongoStore{db: db}
}

// EnsureDetectionIndexes keeps a fresh DB safe; seed owns the full set.
func (s *MongoStore) EnsureDetectionIndexes(ctx context.Context) error {
	if _, err := s.db.Collection("detections").Indexes().CreateOne(ctx,
		mongo.IndexModel{Keys: bson.D{{Key: "event_id", Value: 1}}, Options: options.Index().SetUnique(true)}); err != nil {
		return err
	}
	_, err := s.db.Collection("detections").Indexes().CreateOne(ctx,
		mongo.IndexModel{Keys: bson.D{{Key: "export_status", Value: 1}, {Key: "detected_at", Value: 1}}})
	return err
}

// FindBySerial looks up by serial or returns ErrNotFound.
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

// FindByID looks up owner or returns ErrNotFound.
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

// FindZoneByID looks up zone or returns ErrNotFound.
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

// FindActive returns the covering permit or ErrNotFound.
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

// FindByEventID looks up stored detection or returns ErrNotFound.
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

// Insert persists a detection.
func (s *MongoStore) Insert(ctx context.Context, doc *model.StoredDetection) error {
	_, err := s.db.Collection("detections").InsertOne(ctx, doc)
	return err
}

// FindUnexported returns up to limit pending/failed, oldest first.
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

// SetExportStatus records pending/exported/failed.
func (s *MongoStore) SetExportStatus(ctx context.Context, eventID, status string) error {
	_, err := s.db.Collection("detections").UpdateOne(ctx,
		bson.M{"event_id": eventID},
		bson.M{"$set": bson.M{"export_status": status}})
	return err
}
