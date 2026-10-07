// Package notify logs alerts best-effort; never blocks the pipeline.
package notify

import (
	"context"
	"fmt"
	"log/slog"

	"drone-detect-app/server/internal/model"
)

// Notifier sends one alert; honors cancellation, nil-drone safe.
type Notifier interface {
	Notify(ctx context.Context, alert *model.Alert) error
}

// Format is the one-line console text.
func Format(a *model.Alert) string {
	serial := ""
	if a.Drone != nil {
		serial = a.Drone.SerialNumber
		if a.Drone.Model != "" {
			serial += " (" + a.Drone.Model + ")"
		}
	}
	method := ""
	if a.Identity.Method != "" {
		method = a.Identity.Method + "/" + a.Identity.Result
	}
	return fmt.Sprintf("[%s] zone=%s serial=%s identity=%s conf=%.2f reason=%s event=%s",
		a.Decision, a.ZoneID, serial, method, a.Confidence, a.Reason, a.EventID)
}

// ConsoleNotifier logs; never fails.
type ConsoleNotifier struct {
	Logger *slog.Logger
}

// Notify logs with event_id.
func (n *ConsoleNotifier) Notify(_ context.Context, alert *model.Alert) error {
	log := slog.Default()
	if n.Logger != nil {
		log = n.Logger
	}
	log.Info("alert", "event_id", alert.EventID, "decision", alert.Decision,
		"zone", alert.ZoneID, "reason", alert.Reason, "text", Format(alert))
	return nil
}

// MultiNotifier fans out; one failure never skips the rest.
type MultiNotifier struct {
	Notifiers []Notifier
	Logger    *slog.Logger
}

func (m *MultiNotifier) Notify(ctx context.Context, alert *model.Alert) error {
	var first error
	for _, n := range m.Notifiers {
		if n == nil {
			continue
		}
		if err := n.Notify(ctx, alert); err != nil {
			if first == nil {
				first = err
			}
			if m.Logger != nil {
				m.Logger.Warn("notify failed", "event_id", alert.EventID, "err", err)
			}
		}
	}
	return first
}
