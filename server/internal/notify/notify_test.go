package notify

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/require"

	"drone-detect-app/server/internal/model"
)

func testAlert() *model.Alert {
	return &model.Alert{
		Type: model.MsgAlert, EventID: "e1",
		Decision: model.DecisionUnauthorized, Reason: "no active authorization",
		ZoneID: "north-gate", Confidence: 0.91,
		Identity: model.Identity{Method: model.MethodBeacon, Result: model.IdentityIdentified},
		Drone:    &model.DroneInfo{SerialNumber: "SN1", Model: "Mavic 3"},
	}
}

func TestFormat(t *testing.T) {
	s := Format(testAlert())
	require.Contains(t, s, "unauthorized")
	require.Contains(t, s, "north-gate")
	require.Contains(t, s, "SN1")
	require.Contains(t, s, "e1")
	// Nil-drone safe.
	bare := &model.Alert{Type: model.MsgAlert, EventID: "e2", Decision: model.DecisionUnidentified}
	require.Contains(t, Format(bare), "unidentified")
}

func TestConsoleNeverFails(t *testing.T) {
	n := &ConsoleNotifier{Logger: slog.New(slog.NewTextHandler(io.Discard, nil))}
	require.NoError(t, n.Notify(context.Background(), testAlert()))
	// Nil logger uses default.
	require.NoError(t, (&ConsoleNotifier{}).Notify(context.Background(), testAlert()))
}

type failer struct{ err error }

func (f *failer) Notify(_ context.Context, _ *model.Alert) error { return f.err }

func TestMultiTriesAll(t *testing.T) {
	boom := errors.New("boom")
	ok := &ConsoleNotifier{Logger: slog.New(slog.NewTextHandler(io.Discard, nil))}
	m := &MultiNotifier{Notifiers: []Notifier{&failer{boom}, ok, nil}}
	err := m.Notify(context.Background(), testAlert())
	require.ErrorIs(t, err, boom)
	m2 := &MultiNotifier{Notifiers: []Notifier{ok}}
	require.NoError(t, m2.Notify(context.Background(), testAlert()))
}
