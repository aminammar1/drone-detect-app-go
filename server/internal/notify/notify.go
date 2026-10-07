// Package notify sends alerts to operators via the log (console).
// It is best-effort and must never block the detection pipeline.
// Google Sheets export is separate (server/internal/export).
package notify

import (
	"context"
	"fmt"
	"log/slog"

	"drone-detect-app/server/internal/model"
)

// Notifier sends one alert to one sink. Implementations honor ctx
// cancellation and never panic on a nil drone.
type Notifier interface {
	Notify(ctx context.Context, alert *model.Alert) error
}

// Format is the shared one-line text for console output.
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

// ConsoleNotifier logs alerts via slog. It never fails.
type ConsoleNotifier struct {
	Logger *slog.Logger
}

// Notify logs the alert with event_id for correlation.
func (n *ConsoleNotifier) Notify(_ context.Context, alert *model.Alert) error {
	log := slog.Default()
	if n.Logger != nil {
		log = n.Logger
	}
	log.Info("alert", "event_id", alert.EventID, "decision", alert.Decision,
		"zone", alert.ZoneID, "reason", alert.Reason, "text", Format(alert))
	return nil
}

// MultiNotifier fans out to several notifiers. It tries all of them and
// returns the first error (if any); a failing sink never skips the rest.
type MultiNotifier struct {
	Notifiers []Notifier
	Logger    *slog.Logger
}

// Notify delivers to every child notifier.
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
