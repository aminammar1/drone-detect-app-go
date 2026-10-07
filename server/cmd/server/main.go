// Command server starts the Drone Detect App Go server (Gin).
//
// Detector and beacon WebSockets feed the identity resolver and the
// authorization decision pipeline; every stored detection is queued for
// Sheets/CSV export by a background worker, and alerts fan out to subscribers.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"drone-detect-app/server/internal/api"
	"drone-detect-app/server/internal/authorization"
	"drone-detect-app/server/internal/config"
	"drone-detect-app/server/internal/export"
	"drone-detect-app/server/internal/identity"
	"drone-detect-app/server/internal/notify"
	"drone-detect-app/server/internal/store"
	"drone-detect-app/server/internal/ws"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))

	// Load repo-root .env in dev; missing file is fine (env may be set directly).
	_ = godotenv.Load("../.env", ".env", "../../.env")

	cfg := config.Load()
	gin.SetMode(cfg.GinMode)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	client, err := mongo.Connect(options.Client().ApplyURI(cfg.MongoURI))
	if err != nil {
		logger.Error("mongodb connect failed", "err", err)
		os.Exit(1)
	}
	if err := client.Ping(ctx, nil); err != nil {
		logger.Error("mongodb ping failed", "uri", cfg.MongoURI, "err", err)
		_ = client.Disconnect(context.Background())
		os.Exit(1)
	}
	defer func() {
		if err := client.Disconnect(context.Background()); err != nil {
			logger.Error("mongodb disconnect failed", "err", err)
		}
	}()
	logger.Info("mongodb connected", "db", cfg.MongoDB)

	repos := store.New(client.Database(cfg.MongoDB))
	if err := repos.EnsureDetectionIndexes(ctx); err != nil {
		logger.Error("detection index setup failed", "err", err)
		os.Exit(1)
	}

	hub := ws.NewHub()
	beacons := identity.NewBuffer(
		time.Duration(cfg.BeaconRetentionS * float64(time.Second)),
	)
	resolver := &identity.Correlator{
		Drones:        repos,
		Buffer:        beacons,
		Window:        time.Duration(cfg.BeaconWindowS * float64(time.Second)),
		Grace:         time.Duration(cfg.ResolveGraceMS) * time.Millisecond,
		VisualMinConf: cfg.VisualMinConf,
	}
	decider := &authorization.Decider{Zones: repos, Authorizations: repos}
	notifier := buildNotifier(logger, cfg)
	exporter, fallback := buildExporter(ctx, logger, cfg)
	worker := export.NewWorker(export.Deps{
		Logger:        logger,
		Primary:       exporter,
		Fallback:      fallback,
		Detections:    repos,
		Drones:        repos,
		Owners:        repos,
		BatchSize:     cfg.ExportBatchSize,
		FlushInterval: time.Duration(cfg.ExportFlushSeconds) * time.Second,
	})
	exportCtx, cancelExport := context.WithCancel(context.Background())
	defer cancelExport()
	go worker.Run(exportCtx)
	router := api.NewRouter(logger, api.Handlers{
		Detector: ws.DetectorHandler(ws.DetectorDeps{
			Logger:            logger,
			Detections:        repos,
			Owners:            repos,
			Resolver:          resolver,
			Decider:           decider,
			Hub:               hub,
			DetectorToken:     cfg.DetectorToken,
			AlertOnAuthorized: cfg.AlertOnAuthorized,
			Notifier:          notifier,
			OnStored:          worker.Enqueue,
		}),
		Beacons: ws.BeaconsHandler(ws.BeaconDeps{Logger: logger, Buffer: beacons}),
		Alerts: ws.AlertsHandlerWithDeps(ws.AlertsDeps{
			Hub: hub, Logger: logger,
			Token: cfg.AlertToken, QueueSize: cfg.AlertQueueSize,
		}),
	})
	api.MountSnapshots(router, snapshotDir(cfg))

	srv := &http.Server{
		Addr:              cfg.ServerAddr,
		Handler:           router,
		ReadHeaderTimeout: 10 * time.Second,
	}

	// Graceful shutdown: stop accepting connections, flush the export queue,
	// then close MongoDB.
	stopCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		logger.Info("server listening", "addr", cfg.ServerAddr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server error", "err", fmt.Errorf("listen: %w", err))
			stop()
		}
	}()

	<-stopCtx.Done()
	logger.Info("shutting down")

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer shutdownCancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error("graceful shutdown failed", "err", fmt.Errorf("shutdown: %w", err))
		os.Exit(1)
	}
	// Flush the export queue before closing MongoDB so no detection is left
	// behind unexported.
	cancelExport()
	select {
	case <-worker.Done():
		logger.Info("export queue flushed")
	case <-shutdownCtx.Done():
		logger.Error("export flush timed out")
	}
	logger.Info("server stopped")
}

// buildNotifier returns the console notifier. Google Sheets export is
// separate (buildExporter); alerts only log, never block the pipeline.
func buildNotifier(logger *slog.Logger, _ config.Config) notify.Notifier {
	return &notify.ConsoleNotifier{Logger: logger}
}

// snapshotDir resolves the snapshots directory: configured value first,
// then the usual repo-root and server-local fallbacks.
func snapshotDir(cfg config.Config) string {
	for _, dir := range []string{cfg.SnapshotDir, "../data/snapshots", "data/snapshots"} {
		if dir == "" {
			continue
		}
		if st, err := os.Stat(dir); err == nil && st.IsDir() {
			return dir
		}
	}
	return cfg.SnapshotDir
}

// buildExporter selects the export sink. EXPORT_BACKEND=csv needs no Google
// setup; sheets fails fast with a clear message when authentication or the
// sheet ID is missing (DESCRIPTION.md section 7).
func buildExporter(ctx context.Context, logger *slog.Logger, cfg config.Config) (export.Exporter, *export.CSVExporter) {
	const dir = "data/exports"
	switch cfg.ExportBackend {
	case "csv":
		csvExp, err := export.NewCSVExporter(dir)
		if err != nil {
			logger.Error("csv exporter setup failed", "dir", dir, "err", err)
			os.Exit(1)
		}
		return csvExp, nil
	case "sheets":
		sheetsExp, err := export.NewSheetsExporter(ctx, cfg.GoogleCredsFile, cfg.GoogleSheetID)
		if err != nil {
			logger.Error("sheets exporter setup failed",
				"hint", "set GOOGLE_SHEET_ID and configure ADC (leave GOOGLE_CREDENTIALS_FILE empty) or a key file",
				"err", err)
			os.Exit(1)
		}
		fallback, err := export.NewCSVExporter(dir)
		if err != nil {
			logger.Error("csv fallback setup failed", "dir", dir, "err", err)
			os.Exit(1)
		}
		return sheetsExp, fallback
	default:
		logger.Error("invalid EXPORT_BACKEND", "want", "csv or sheets", "got", cfg.ExportBackend)
		os.Exit(1)
		return nil, nil
	}
}
