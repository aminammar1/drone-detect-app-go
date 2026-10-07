package ws

import (
	"sync"

	"drone-detect-app/server/internal/model"
)

// Hub fans out alerts; slow clients are evicted, never block.
type Hub struct {
	mu      sync.Mutex
	clients map[*alertClient]struct{}
}

// alertClient owns one send queue; only its goroutine writes the conn.
type alertClient struct {
	send chan []byte
}

// NewHub needs no goroutine; broadcast never blocks.
func NewHub() *Hub {
	return &Hub{clients: make(map[*alertClient]struct{})}
}

// Add registers a client.
func (h *Hub) Add(c *alertClient) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[c] = struct{}{}
}

// Remove unregisters and closes send.
func (h *Hub) Remove(c *alertClient) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, ok := h.clients[c]; ok {
		delete(h.clients, c)
		close(c.send)
	}
}

// Count reports clients.
func (h *Hub) Count() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return len(h.clients)
}

// Broadcast fans out; full buffers are evicted.
func (h *Hub) Broadcast(alert *model.Alert) {
	h.mu.Lock()
	defer h.mu.Unlock()
	// Alert always marshals.
	for c := range h.clients {
		select {
		case c.send <- marshalAlert(alert):
		default:
			delete(h.clients, c)
			close(c.send)
		}
	}
}
