package ws

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"

	"drone-detect-app/server/internal/authz"
	"drone-detect-app/server/internal/identity"
	"drone-detect-app/server/internal/model"
	"drone-detect-app/server/internal/notify"
	"drone-detect-app/server/internal/store"
)

// Wire timing (DESCRIPTION.md section 3.6): ping every 30 s, dead after
// 60 s without a pong (read deadline refreshed on every pong).
const (
	writeWait  = 10 * time.Second
	pongWait   = 60 * time.Second
	pingPeriod = 30 * time.Second
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	// Python clients send no Origin; browsers must be same-host.
	CheckOrigin: func(r *http.Request) bool {
		origin := r.Header.Get("Origin")
		return origin == "" || r.Host == stripScheme(origin)
	},
}

func stripScheme(origin string) string {
	for _, prefix := range []string{"https://", "http://"} {
		if len(origin) > len(prefix) && origin[:len(prefix)] == prefix {
			rest := origin[len(prefix):]
			for i, c := range rest {
				if c == '/' {
					return rest[:i]
				}
			}
			return rest
		}
	}
	return origin
}

// DetectorDeps wires the /ws/detector pipeline. No globals.
type DetectorDeps struct {
	Logger            *slog.Logger
	Detections        store.Detections
	Owners            store.Owners
	Resolver          identity.Resolver
	Decider           *authz.Decider
	Hub               *Hub
	DetectorToken     string
	AlertOnAuthorized bool
	// Notifier, when set, receives every broadcast alert (console, Telegram).
	// It runs in a goroutine and must never block the ack path.
	Notifier notify.Notifier
	// OnStored, when set, receives each newly stored detection (e.g. the
	// export worker's Enqueue). It must not block; resends do not trigger it.
	OnStored func(*model.StoredDetection)
}

// DetectorHandler upgrades the connection and serves one detector.
// Exactly one writer goroutine owns all conn writes via send.
func DetectorHandler(deps DetectorDeps) gin.HandlerFunc {
	return func(c *gin.Context) {
		if deps.DetectorToken != "" && c.GetHeader("X-Detector-Token") != deps.DetectorToken {
			c.JSON(http.StatusForbidden, gin.H{"error": "bad detector token"})
			return
		}
		conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
		if err != nil {
			deps.Logger.Warn("detector upgrade failed", "err", err)
			return
		}
		s := &detectorSession{deps: deps, conn: conn, send: make(chan []byte, 16)}
		go s.writePump()
		s.readPump()
		// readPump returned (peer gone): unblock writePump immediately so
		// the goroutine does not linger until the next ping.
		close(s.send)
	}
}

type detectorSession struct {
	deps DetectorDeps
	conn *websocket.Conn
	send chan []byte
}

func (s *detectorSession) readPump() {
	defer s.conn.Close()
	s.conn.SetReadLimit(1 << 20) // 1 MiB per frame is plenty for an event
	_ = s.conn.SetReadDeadline(time.Now().Add(pongWait))
	s.conn.SetPongHandler(func(string) error {
		return s.conn.SetReadDeadline(time.Now().Add(pongWait))
	})
	for {
		_, raw, err := s.conn.ReadMessage()
		if err != nil {
			return // idle timeout, protocol error, or client gone
		}
		s.handle(raw)
	}
}

func (s *detectorSession) writePump() {
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

func (s *detectorSession) sendJSON(v interface{}) {
	raw, err := json.Marshal(v)
	if err != nil {
		s.deps.Logger.Error("marshal reply failed", "err", err)
		return
	}
	select {
	case s.send <- raw:
	default:
		// Detector is not reading; drop the reply rather than block.
		s.deps.Logger.Warn("detector send buffer full, dropping reply")
	}
}

func (s *detectorSession) sendError(eventID, code, msg string) {
	s.sendJSON(model.ErrorMsg{Type: model.MsgError, EventID: eventID, Code: code, Message: msg})
}

// handle processes one inbound frame. It never crashes the connection:
// invalid input gets an "error" reply and the loop continues (FR-S5).
func (s *detectorSession) handle(raw []byte) {
	var env model.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		s.sendError("", "invalid_json", "message is not valid JSON")
		return
	}
	if env.Type != model.MsgDetection {
		s.sendError(env.EventID, "unknown_type", fmt.Sprintf("type must be %q", model.MsgDetection))
		return
	}
	var det model.Detection
	if err := json.Unmarshal(raw, &det); err != nil {
		s.sendError(env.EventID, "invalid_event", "detection is not valid JSON")
		return
	}
	det.Normalize()
	if err := det.Validate(); err != nil {
		s.deps.Logger.Info("invalid detection", "event_id", det.EventID, "err", err)
		s.sendError(det.EventID, "invalid_event", err.Error())
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	s.process(ctx, &det)
}

// process runs resolve -> decide -> persist -> ack -> alert for one event.
func (s *detectorSession) process(ctx context.Context, det *model.Detection) {
	log := s.deps.Logger.With("event_id", det.EventID)

	// Idempotency: a resent event returns the stored decision, no duplicate.
	if prev, err := s.deps.Detections.FindByEventID(ctx, det.EventID); err == nil {
		s.sendJSON(ackFromStored(prev))
		return
	} else if !errors.Is(err, store.ErrNotFound) {
		log.Error("detection lookup failed", "err", err)
		s.sendError(det.EventID, "store_error", "internal error")
		return
	}

	id, err := s.deps.Resolver.Resolve(ctx, det)
	if err != nil {
		log.Error("identity resolution failed", "err", err)
		s.sendError(det.EventID, "store_error", "internal error")
		return
	}
	out, err := s.deps.Decider.Decide(ctx, det, id)
	if err != nil {
		log.Error("decision failed", "err", err)
		s.sendError(det.EventID, "store_error", "internal error")
		return
	}

	droneInfo := owneredDrone(ctx, s.deps.Owners, out.Drone, log)
	ack := model.Ack{
		Type: model.MsgAck, EventID: det.EventID,
		Decision: out.Decision, Reason: out.Reason,
		Identity: model.Identity{
			Method: id.Method, Result: id.Outcome,
			Candidates: id.Candidates, Confidence: id.Confidence,
		},
		Drone: droneInfo,
	}
	stored := &model.StoredDetection{
		EventID: det.EventID, DetectedAt: det.DetectedAt, ReceivedAt: time.Now().UTC(),
		Source: det.Source, ZoneID: det.ZoneID, TrackID: det.TrackID,
		Class: det.Class, Confidence: det.Confidence, BBox: det.BBox,
		FrameIndex: det.FrameIndex, SnapshotPath: det.SnapshotPath,
		Visual: det.Visual, Identifier: det.Identifier,
		Identity: ack.Identity, Decision: ack.Decision, Reason: ack.Reason,
		Drone: droneInfo, ExportStatus: "pending",
	}
	if out.Drone != nil {
		stored.DroneID = &out.Drone.ID
	}
	if err := s.deps.Detections.Insert(ctx, stored); err != nil {
		if isDuplicateKey(err) {
			// Lost a concurrent insert race: answer from the winner.
			if prev, ferr := s.deps.Detections.FindByEventID(ctx, det.EventID); ferr == nil {
				s.sendJSON(ackFromStored(prev))
				return
			}
		}
		log.Error("detection persist failed", "err", fmt.Errorf("insert: %w", err))
		s.sendError(det.EventID, "store_error", "internal error")
		return
	}

	s.sendJSON(ack)
	if s.deps.OnStored != nil {
		s.deps.OnStored(stored)
	}
	if ack.Decision != model.DecisionAuthorized || s.deps.AlertOnAuthorized {
		alert := &model.Alert{
			Type: model.MsgAlert, EventID: det.EventID,
			DetectedAt: det.DetectedAt, ZoneID: det.ZoneID,
			Confidence: det.Confidence, SnapshotPath: det.SnapshotPath,
			Decision: ack.Decision, Reason: ack.Reason,
			Identity: ack.Identity, Drone: droneInfo,
		}
		s.deps.Hub.Broadcast(alert)
		if s.deps.Notifier != nil {
			// Best-effort: never block the ack path on a slow sink.
			go func(a *model.Alert) {
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				if err := s.deps.Notifier.Notify(ctx, a); err != nil {
					log.Warn("notifier failed", "err", err)
				}
			}(alert)
		}
	}
}

// owneredDrone attaches the owner name for ack/alert display.
func owneredDrone(ctx context.Context, owners store.Owners, drone *model.Drone, log *slog.Logger) *model.DroneInfo {
	if drone == nil {
		return nil
	}
	info := &model.DroneInfo{
		SerialNumber: drone.SerialNumber, Manufacturer: drone.Manufacturer,
		Model: drone.Model, AirframeType: drone.AirframeType,
	}
	owner, err := owners.FindByID(ctx, drone.OwnerID)
	if err != nil {
		if !errors.Is(err, store.ErrNotFound) {
			log.Warn("owner lookup failed", "err", err)
		}
		return info
	}
	info.OwnerName = owner.Name
	return info
}

// ackFromStored rebuilds the ack for a resent event_id.
func ackFromStored(prev *model.StoredDetection) model.Ack {
	return model.Ack{
		Type: model.MsgAck, EventID: prev.EventID,
		Decision: prev.Decision, Reason: prev.Reason,
		Identity: prev.Identity, Drone: prev.Drone,
	}
}

// isDuplicateKey reports a unique-index violation (event_id resend race).
func isDuplicateKey(err error) bool {
	var wex interface{ HasErrorLabel(string) bool }
	if errors.As(err, &wex) {
		return wex.HasErrorLabel("DuplicateKey")
	}
	return false
}
