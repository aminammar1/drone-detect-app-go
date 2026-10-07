// Package config loads env per DESCRIPTION.md section 8; main loads .env.
package config

import (
	"os"
	"strconv"
)

// Config centralizes settings; nothing hard-codes hosts or secrets.
type Config struct {
	ServerAddr         string
	GinMode            string
	MongoURI           string
	MongoDB            string
	ExportBackend      string
	GoogleCredsFile    string
	GoogleSheetID      string
	ExportBatchSize    int
	ExportFlushSeconds int
	AlertOnAuthorized  bool
	// AlertToken guards /ws/alerts; empty disables auth. ?token= exists because browsers can't set WS headers.
	AlertToken string
	// AlertQueueSize bounds per-client buffers; slow clients get evicted, never block.
	AlertQueueSize int
	// ExportIdentifiedOnly sends only server-confirmed identified drones to
	// Sheets/CSV. MongoDB still stores every detection (audit, idempotency).
	ExportIdentifiedOnly bool
	BeaconWindowS        float64
	BeaconRetentionS     float64
	ResolveGraceMS       int
	VisualMinConf        float64
	DetectorToken        string
	SnapshotDir          string
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getenvInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func getenvFloat(key string, def float64) float64 {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.ParseFloat(v, 64); err == nil {
			return n
		}
	}
	return def
}

func getenvBool(key string, def bool) bool {
	if v := os.Getenv(key); v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			return b
		}
	}
	return def
}

// Load reads env with DESCRIPTION.md section 8 defaults.
func Load() Config {
	return Config{
		ServerAddr:           getenv("SERVER_ADDR", ":8080"),
		GinMode:              getenv("GIN_MODE", "debug"),
		MongoURI:             getenv("MONGO_URI", "mongodb://localhost:27017"),
		MongoDB:              getenv("MONGO_DB", "drone_detect_app"),
		ExportBackend:        getenv("EXPORT_BACKEND", "csv"),
		GoogleCredsFile:      getenv("GOOGLE_CREDENTIALS_FILE", ""),
		GoogleSheetID:        getenv("GOOGLE_SHEET_ID", ""),
		ExportBatchSize:      getenvInt("EXPORT_BATCH_SIZE", 50),
		ExportFlushSeconds:   getenvInt("EXPORT_FLUSH_SECONDS", 5),
		AlertOnAuthorized:    getenvBool("ALERT_ON_AUTHORIZED", false),
		AlertToken:           getenv("ALERT_TOKEN", ""),
		AlertQueueSize:       getenvInt("ALERT_QUEUE_SIZE", 64),
		ExportIdentifiedOnly: getenvBool("EXPORT_IDENTIFIED_ONLY", true),
		BeaconWindowS:        getenvFloat("BEACON_WINDOW_S", 3),
		BeaconRetentionS:     getenvFloat("BEACON_RETENTION_S", 60),
		ResolveGraceMS:       getenvInt("RESOLVE_GRACE_MS", 1500),
		VisualMinConf:        getenvFloat("VISUAL_MIN_CONF", 0.5),
		DetectorToken:        getenv("DETECTOR_TOKEN", ""),
		SnapshotDir:          getenv("SNAPSHOT_DIR", "../data/snapshots"),
	}
}
