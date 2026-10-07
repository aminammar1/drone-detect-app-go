package ws

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"

	"drone-detect-app/server/internal/identity"
	"drone-detect-app/server/internal/model"
)

// BeaconDeps injects /ws/beacons; beacons are fire-and-forget.
type BeaconDeps struct {
	Logger *slog.Logger
	Buffer *identity.Buffer
}

// BeaconsHandler serves one source; single writer, ping/pong.
func BeaconsHandler(deps BeaconDeps) gin.HandlerFunc {
	return func(c *gin.Context) {
		conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
		if err != nil {
			deps.Logger.Warn("beacon upgrade failed", "err", err)
			return
		}
		s := &beaconSession{deps: deps, conn: conn, send: make(chan []byte, 4)}
		go s.writePump()
		s.readPump()
		close(s.send)
	}
}

type beaconSession struct {
	deps BeaconDeps
	conn *websocket.Conn
	send chan []byte
}

func (s *beaconSession) readPump() {
	defer s.conn.Close()
	s.conn.SetReadLimit(1 << 20)
	_ = s.conn.SetReadDeadline(time.Now().Add(pongWait))
	s.conn.SetPongHandler(func(string) error {
		return s.conn.SetReadDeadline(time.Now().Add(pongWait))
	})
	for {
		_, raw, err := s.conn.ReadMessage()
		if err != nil {
			return
		}
		s.handle(raw)
	}
}

func (s *beaconSession) writePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		s.conn.Close()
	}()
	for {
		select {
		case msg, ok := <-s.send:
			_ = s.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				_ = s.conn.WriteMessage(websocket.CloseMessage, nil)
				return
			}
			if err := s.conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		case <-ticker.C:
			_ = s.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := s.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

// handle buffers valid beacons; invalid input gets error, never drops the conn.
func (s *beaconSession) handle(raw []byte) {
	var env model.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		s.sendError("invalid_json", "message is not valid JSON")
		return
	}
	if env.Type != model.MsgBeacon {
		s.sendError("unknown_type", fmt.Sprintf("type must be %q", model.MsgBeacon))
		return
	}
	var beacon model.Beacon
	if err := json.Unmarshal(raw, &beacon); err != nil {
		s.sendError("invalid_event", "beacon is not valid JSON")
		return
	}
	if err := validateBeacon(&beacon); err != nil {
		s.deps.Logger.Info("invalid beacon", "err", err)
		s.sendError("invalid_event", err.Error())
		return
	}
	s.deps.Buffer.Add(beacon, time.Now())
	s.deps.Logger.Debug("beacon buffered",
		"serial", beacon.SerialNumber, "zone", beacon.ZoneID, "at", beacon.Timestamp)
}

func (s *beaconSession) sendError(code, msg string) {
	raw, err := json.Marshal(model.ErrorMsg{Type: model.MsgError, Code: code, Message: msg})
	if err != nil {
		return
	}
	select {
	case s.send <- raw:
	default:
	}
}

// validateBeacon enforces DESCRIPTION.md section 3.2.
func validateBeacon(b *model.Beacon) error {
	if b.Type != model.MsgBeacon {
		return fmt.Errorf("type must be %q", model.MsgBeacon)
	}
	if b.SerialNumber == "" {
		return fmt.Errorf("serial_number is required")
	}
	if b.ZoneID == "" {
		return fmt.Errorf("zone_id is required")
	}
	if b.Timestamp.IsZero() {
		return fmt.Errorf("timestamp is required")
	}
	return nil
}
