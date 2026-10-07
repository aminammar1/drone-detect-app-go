// Package api builds the Gin router: gin.New() with gin.Recovery() and a
// log/slog request-logging middleware. Serves GET /, GET /healthz,
// GET /ws/detector, GET /ws/beacons and GET /ws/alerts.
package api

import (
	"log/slog"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// Handlers are the mounted route handlers; main wires the implementations.
type Handlers struct {
	Detector gin.HandlerFunc
	Beacons  gin.HandlerFunc
	Alerts   gin.HandlerFunc
}

// NewRouter wires middleware and routes. Dependencies are passed in;
// there are no package-level globals.
func NewRouter(logger *slog.Logger, h Handlers) *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(requestLogger(logger))

	r.GET("/", DashboardHandler())
	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})
	r.GET("/ws/detector", h.Detector)
	r.GET("/ws/beacons", h.Beacons)
	r.GET("/ws/alerts", h.Alerts)

	return r
}

// requestLogger is a structured access log via log/slog.
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
