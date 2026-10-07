package ws

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"drone-detect-app/server/internal/model"
)

func testAlert() *model.Alert {
	return &model.Alert{Type: model.MsgAlert, EventID: "e1", Decision: model.DecisionUnauthorized, Reason: "r"}
}

func drain(t *testing.T, c *alertClient) string {
	t.Helper()
	select {
	case raw := <-c.send:
		return string(raw)
	default:
		t.Fatal("expected a message")
		return ""
	}
}

func TestHubBroadcast(t *testing.T) {
	hub := NewHub()
	a := &alertClient{send: make(chan []byte, 16)}
	b := &alertClient{send: make(chan []byte, 16)}
	hub.Add(a)
	hub.Add(b)
	assert.Equal(t, 2, hub.Count())

	hub.Broadcast(testAlert())
	assert.Contains(t, drain(t, a), `"event_id":"e1"`)
	assert.Contains(t, drain(t, b), `"event_id":"e1"`)
	assert.Equal(t, 2, hub.Count())
}

func TestHubDropsSlowClient(t *testing.T) {
	hub := NewHub()
	slow := &alertClient{send: make(chan []byte, 1)} // tiny buffer, never drained
	fast := &alertClient{send: make(chan []byte, 16)}
	hub.Add(slow)
	hub.Add(fast)

	hub.Broadcast(testAlert()) // fills slow's buffer
	require.Equal(t, 2, hub.Count())
	hub.Broadcast(testAlert()) // slow is full: evicted, fast still served
	assert.Equal(t, 1, hub.Count())
	assert.Contains(t, drain(t, fast), `"event_id":"e1"`)
}

func TestHubDisconnect(t *testing.T) {
	hub := NewHub()
	a := &alertClient{send: make(chan []byte, 16)}
	hub.Add(a)
	require.Equal(t, 1, hub.Count())

	hub.Remove(a)
	assert.Equal(t, 0, hub.Count())
	// Send channel is closed so the client's pump exits.
	select {
	case _, ok := <-a.send:
		assert.False(t, ok, "send channel must be closed after Remove")
	default:
		t.Fatal("expected closed channel after Remove")
	}

	// Double remove is safe; broadcast to nobody is a no-op.
	hub.Remove(a)
	assert.Equal(t, 0, hub.Count())
	hub.Broadcast(testAlert())
}

func TestHubBroadcastAfterRemoveGetsNothing(t *testing.T) {
	hub := NewHub()
	a := &alertClient{send: make(chan []byte, 16)}
	b := &alertClient{send: make(chan []byte, 16)}
	hub.Add(a)
	hub.Add(b)
	hub.Remove(a)

	hub.Broadcast(testAlert())
	assert.Equal(t, 1, hub.Count())
	// a.send is closed by Remove: a receive succeeds with ok=false, never
	// with a live message.
	select {
	case msg, ok := <-a.send:
		require.False(t, ok, "removed client channel must be closed, got %q", string(msg))
	default:
		// Also acceptable: nothing queued (if Remove had not closed, which
		// it does — this branch guards against implementation changes).
	}
	assert.Contains(t, drain(t, b), `"event_id":"e1"`)
}
