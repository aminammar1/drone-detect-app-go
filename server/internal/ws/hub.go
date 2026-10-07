// Package ws holds the WebSocket handlers: /ws/detector and /ws/alerts
// (M2). /ws/beacons arrives in M5. See DESCRIPTION.md section 3.
package ws

import (
	"sync"

	"drone-detect-app/server/internal/model"
)

// Hub broadcasts alerts to /ws/alerts clients. Slow clients are dropped
// instead of blocking the pipeline (stage 10 failure behavior).
type Hub struct {
	mu      sync.Mutex
	clients map[*alertClient]struct{}
}

// alertClient is one subscriber. Only the client's own write goroutine
// sends on conn; the hub only appends to send (never writes concurrently).
type alertClient struct {
	send chan []byte
}

// NewHub returns an empty hub. It needs no goroutine: broadcast never
// blocks, so there is nothing to pump.
func NewHub() *Hub {
	return &Hub{clients: make(map[*alertClient]struct{})}
}

// Add registers a client; Remove unregisters it. Clients must call Remove
// (or Close) when their connection ends.
func (h *Hub) Add(c *alertClient) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[c] = struct{}{}
}

// Remove unregisters a client and closes its send channel.
func (h *Hub) Remove(c *alertClient) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, ok := h.clients[c]; ok {
		delete(h.clients, c)
		close(c.send)
	}
}

// Count reports registered clients (for tests and logs).
func (h *Hub) Count() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return len(h.clients)
}

// Broadcast sends an alert to every client. A client whose buffer is full
// is evicted so one slow reader can never stall the pipeline.
func (h *Hub) Broadcast(alert *model.Alert) {
	h.mu.Lock()
	defer h.mu.Unlock()
	// Marshal is infallible for our struct; errors are handled by callers.
	for c := range h.clients {
		select {
		case c.send <- marshalAlert(alert):
		default:
			delete(h.clients, c)
			close(c.send)
		}
	}
}
