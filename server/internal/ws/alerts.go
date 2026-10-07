package ws

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"

	"drone-detect-app/server/internal/model"
)

func marshalAlert(alert *model.Alert) []byte {
	raw, err := json.Marshal(alert)
	if err != nil {
		return []byte(`{"type":"alert"}`)
	}
	return raw
}

// AlertsDeps wires /ws/alerts. No globals.
//
// Token, when non-empty, requires alert clients to authenticate. Browsers
// cannot set headers on a WebSocket handshake, so ?token= is accepted; bots
// may also use X-Alert-Token or Authorization: Bearer. Empty disables auth.
//
// QueueSize bounds each client's send buffer. Broadcast never blocks: a
// client whose buffer is full is evicted, so a slow reader cannot stall the
// pipeline or other clients.
type AlertsDeps struct {
	Hub       *Hub
	Logger    *slog.Logger
	Token     string
	QueueSize int
}

// DefaultAlertQueueSize is used when Deps.QueueSize <= 0.
const DefaultAlertQueueSize = 64

// AlertsHandler upgrades alert subscribers and registers them on the hub.
// It is stateless and reconnect-friendly: a client may reconnect at any time
// with backoff; no resume token is needed because alerts are ephemeral
// (persisted detections remain queryable in MongoDB).
func AlertsHandler(hub *Hub, logger *slog.Logger) gin.HandlerFunc {
	return AlertsHandlerWithDeps(AlertsDeps{Hub: hub, Logger: logger})
}

// AlertsHandlerWithDeps is the production handler with auth + queue options.
func AlertsHandlerWithDeps(deps AlertsDeps) gin.HandlerFunc {
	if deps.Logger == nil {
		deps.Logger = slog.Default()
	}
	queue := deps.QueueSize
	if queue <= 0 {
		queue = DefaultAlertQueueSize
	}
	return func(c *gin.Context) {
		if deps.Token != "" && !checkAlertToken(c, deps.Token) {
			c.JSON(http.StatusForbidden, gin.H{"error": "bad alert token"})
			return
		}
		conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
		if err != nil {
			deps.Logger.Warn("alerts upgrade failed", "err", err)
			return
		}
		client := &alertClient{send: make(chan []byte, queue)}
		deps.Hub.Add(client)
		defer deps.Hub.Remove(client)
		pumpAlerts(conn, client, deps.Logger)
	}
}

// checkAlertToken accepts ?token=, X-Alert-Token, or Authorization: Bearer.
func checkAlertToken(c *gin.Context, want string) bool {
	if got := c.Query("token"); got != "" && got == want {
		return true
	}
	if got := c.GetHeader("X-Alert-Token"); got != "" && got == want {
		return true
	}
	if auth := c.GetHeader("Authorization"); strings.HasPrefix(auth, "Bearer ") {
		return strings.TrimSpace(strings.TrimPrefix(auth, "Bearer ")) == want
	}
	return false
}

func pumpAlerts(conn *websocket.Conn, client *alertClient, logger *slog.Logger) {
	defer conn.Close()
	conn.SetReadLimit(64 << 10)
	_ = conn.SetReadDeadline(time.Now().Add(pongWait))
	conn.SetPongHandler(func(string) error {
		return conn.SetReadDeadline(time.Now().Add(pongWait))
	})
	ticker := time.NewTicker(pingPeriod)
	defer ticker.Stop()
	// done closes when the peer goes away; the write loop must exit
	// immediately (not on the next 30s ping) so hub.Count drops and the
	// client can reconnect right away.
	done := make(chan struct{})
	go func() {
		// Drain inbound frames (close/pong) so the peer's close is noticed.
		defer close(done)
		defer conn.Close()
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}()
	for {
		select {
		case <-done:
			return
		case msg, ok := <-client.send:
			_ = conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				_ = conn.WriteMessage(websocket.CloseMessage, nil)
				return
			}
			if err := conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		case <-ticker.C:
			_ = conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}
