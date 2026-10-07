// Package config loads server configuration from environment variables
// (optionally via a .env file loaded by main). Variable names and defaults
// come from DESCRIPTION.md section 8.
package config

import (
	"os"
	"strconv"
)

// Config holds all server settings. No hard-coded hosts, ports, or secrets
// elsewhere in the code.
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
	// AlertToken guards /ws/alerts and the dashboard when set. Empty disables
	// the check (local dev). Browsers pass it as ?token= (WS cannot set
	// headers); programmatic clients may also use X-Alert-Token or
	// Authorization: Bearer.
	AlertToken string
	// AlertQueueSize is the per-client buffered send queue for /ws/alerts.
	// Bounded so a slow client can be evicted instead of blocking the server.
	AlertQueueSize   int
	BeaconWindowS    float64
	BeaconRetentionS float64
	ResolveGraceMS   int
	VisualMinConf    float64
	DetectorToken    string
	SnapshotDir      string
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

// Load reads configuration from the environment with DESCRIPTION.md defaults.
func Load() Config {
	return Config{
		ServerAddr:         getenv("SERVER_ADDR", ":8080"),
		GinMode:            getenv("GIN_MODE", "debug"),
		MongoURI:           getenv("MONGO_URI", "mongodb://localhost:27017"),
		MongoDB:            getenv("MONGO_DB", "drone_detect_app"),
		ExportBackend:      getenv("EXPORT_BACKEND", "csv"),
		GoogleCredsFile:    getenv("GOOGLE_CREDENTIALS_FILE", ""),
		GoogleSheetID:      getenv("GOOGLE_SHEET_ID", ""),
		ExportBatchSize:    getenvInt("EXPORT_BATCH_SIZE", 50),
		ExportFlushSeconds: getenvInt("EXPORT_FLUSH_SECONDS", 5),
		AlertOnAuthorized:  getenvBool("ALERT_ON_AUTHORIZED", false),
		AlertToken:         getenv("ALERT_TOKEN", ""),
		AlertQueueSize:     getenvInt("ALERT_QUEUE_SIZE", 64),
		BeaconWindowS:      getenvFloat("BEACON_WINDOW_S", 3),
		BeaconRetentionS:   getenvFloat("BEACON_RETENTION_S", 60),
		ResolveGraceMS:     getenvInt("RESOLVE_GRACE_MS", 1500),
		VisualMinConf:      getenvFloat("VISUAL_MIN_CONF", 0.5),
		DetectorToken:      getenv("DETECTOR_TOKEN", ""),
		SnapshotDir:        getenv("SNAPSHOT_DIR", "../data/snapshots"),
	}
}
