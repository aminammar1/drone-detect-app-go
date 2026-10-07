// Package api owns routing; Recovery keeps bad events from crashing the server.
package api

import (
	"log/slog"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// Handlers are injected by main; no globals.
type Handlers struct {
	Detector gin.HandlerFunc
	Beacons  gin.HandlerFunc
	Alerts   gin.HandlerFunc
}

// NewRouter builds the engine from injected handlers.
func NewRouter(logger *slog.Logger, h Handlers) *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(requestLogger(logger))

	r.GET("/", DashboardHandler())
	health := func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
	r.GET("/health", health)
	r.GET("/healthz", health) // legacy alias
	r.GET("/ws/detector", h.Detector)
	r.GET("/ws/beacons", h.Beacons)
	r.GET("/ws/alerts", h.Alerts)

	return r
}

func requestLogger(logger *slog.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		logger.Info("http request",
			"method", c.Request.Method,
			"path", c.Request.URL.Path,
			"status", c.Writer.Status(),
			"latency_ms", time.Since(start).Milliseconds(),
		)
	}
}
