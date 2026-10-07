// Background export worker: batches detections, appends them via the primary
// exporter, falls back to CSV on Sheets failures, and retries with
// exponential backoff. One goroutine owns the loop; Enqueue never blocks the
// detector ack path.
package export

import (
	"context"
	"log/slog"
	"time"

	"drone-detect-app/server/internal/model"
)

// Deps wires the worker. No globals.
type Deps struct {
	Logger        *slog.Logger
	Primary       Exporter
	Fallback      *CSVExporter // nil when the backend itself is csv
	Detections    ExportStore
	Drones        DroneLookup
	Owners        OwnerLookup
	BatchSize     int           // flush when this many rows pile up (default 50)
	FlushInterval time.Duration // flush partial batches this often (default 5s)
	RetryInitial  time.Duration // first retry delay (default 2s)
	RetryMax      time.Duration // backoff cap (default 5m)
	QueueSize     int           // export queue buffer (default 1024)
	RequeuePage   int           // startup requeue page size (default 500)
}

type retryItem struct {
	docs     []*model.StoredDetection
	attempts int
	next     time.Time
}

// Worker consumes stored detections and exports them in batches.
type Worker struct {
	deps    Deps
	queue   chan *model.StoredDetection
	done    chan struct{}
	pending []*model.StoredDetection
	retries []retryItem
}

// NewWorker fills defaults and returns a worker. Run it in a goroutine.
func NewWorker(deps Deps) *Worker {
	if deps.Logger == nil {
		deps.Logger = slog.Default()
	}
	if deps.BatchSize <= 0 {
		deps.BatchSize = 50
	}
	if deps.FlushInterval <= 0 {
		deps.FlushInterval = 5 * time.Second
	}
	if deps.RetryInitial <= 0 {
		deps.RetryInitial = 2 * time.Second
	}
	if deps.RetryMax <= 0 {
		deps.RetryMax = 5 * time.Minute
	}
	if deps.QueueSize <= 0 {
		deps.QueueSize = 1024
	}
	if deps.RequeuePage <= 0 {
		deps.RequeuePage = 500
	}
	return &Worker{deps: deps, queue: make(chan *model.StoredDetection, deps.QueueSize), done: make(chan struct{})}
}

// Enqueue schedules a stored detection for export. It never blocks: when the
// queue is full the detection is dropped with an error log and stays
// "pending" in MongoDB for the next startup requeue.
func (w *Worker) Enqueue(doc *model.StoredDetection) {
	if doc == nil {
		return
	}
	select {
	case w.queue <- doc:
	default:
		w.deps.Logger.Error("export queue full, detection stays pending", "event_id", doc.EventID)
	}
}

// Done closes when Run returns (after the final flush).
func (w *Worker) Done() <-chan struct{} {
	return w.done
}

// Run requeues unfinished exports, then batches queue arrivals until ctx is
// cancelled, when it flushes everything once more and returns.
func (w *Worker) Run(ctx context.Context) {
	defer close(w.done)
	w.requeue(ctx)

	flushT := time.NewTimer(w.deps.FlushInterval)
	defer flushT.Stop()
	var retryT *time.Timer
	var retryCh <-chan time.Time
	armRetry := func() {
		if retryT != nil {
			retryT.Stop()
			retryT, retryCh = nil, nil
		}
		if len(w.retries) == 0 {
			return
		}
		earliest := w.retries[0].next
		for _, r := range w.retries[1:] {
			if r.next.Before(earliest) {
				earliest = r.next
			}
		}
		wait := time.Until(earliest)
		if wait < 0 {
			wait = 0
		}
		retryT = time.NewTimer(wait)
		retryCh = retryT.C
	}
	resetFlush := func() {
		if !flushT.Stop() {
			select {
			case <-flushT.C:
			default:
			}
		}
		flushT.Reset(w.deps.FlushInterval)
	}

	for {
		select {
		case <-ctx.Done():
			if retryT != nil {
				retryT.Stop()
			}
			// Final flush with a fresh budget: the parent ctx is already
			// cancelled, but shutdown gave us time (main passes ~10s via
			// WithoutCancel below through Stop semantics; here we just cap).
			fctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
			w.flush(fctx, w.pending, 0)
			w.pending = nil
			for _, r := range w.retries {
				w.flush(fctx, r.docs, r.attempts)
			}
			w.retries = nil
			cancel()
			return
		case doc := <-w.queue:
			w.pending = append(w.pending, doc)
			if len(w.pending) >= w.deps.BatchSize {
				w.flush(ctx, w.pending, 0)
				w.pending = nil
				resetFlush()
				armRetry()
			}
		case <-flushT.C:
			w.flush(ctx, w.pending, 0)
			w.pending = nil
			flushT.Reset(w.deps.FlushInterval)
			armRetry()
		case <-retryCh:
			now := time.Now()
			var due []*model.StoredDetection
			var dueAttempts []int
			rest := w.retries[:0]
			for _, r := range w.retries {
				if !r.next.After(now) {
					// Re-flush each due batch with its own attempt count so
					// backoff keeps growing per batch instead of resetting.
					due = append(due, r.docs...)
					for range r.docs {
						dueAttempts = append(dueAttempts, r.attempts)
					}
				} else {
					rest = append(rest, r)
				}
			}
			w.retries = rest
			flushDue(ctx, w, due, dueAttempts)
			armRetry()
		}
	}
}

// flushDue re-flushes docs grouped by their attempt counts.
func flushDue(ctx context.Context, w *Worker, docs []*model.StoredDetection, attempts []int) {
	start := 0
	for start < len(docs) {
		a := attempts[start]
		end := start + 1
		for end < len(docs) && attempts[end] == a {
			end++
		}
		w.flush(ctx, docs[start:end], a)
		start = end
	}
}

// flush exports one batch: build rows (enriched with registration data),
// append via the primary exporter, and record per-detection progress.
func (w *Worker) flush(ctx context.Context, docs []*model.StoredDetection, attempts int) {
	if len(docs) == 0 {
		return
	}
	rows := make([][]any, 0, len(docs))
	for _, doc := range docs {
		rows = append(rows, w.row(ctx, doc))
	}
	if err := w.deps.Primary.Append(ctx, rows); err != nil {
		w.deps.Logger.Error("export failed, rows kept in CSV fallback, retry scheduled",
			"count", len(docs), "first_event_id", docs[0].EventID, "err", err)
		if w.deps.Fallback != nil {
			// Best effort: the rows must survive even if Sheets is down.
			// WithoutCancel so a cancelled flush still lands on disk.
			if ferr := w.deps.Fallback.Append(context.WithoutCancel(ctx), rows); ferr != nil {
				w.deps.Logger.Error("csv fallback write failed", "err", ferr)
			}
		}
		for _, doc := range docs {
			// WithoutCancel: progress must be recorded even during shutdown.
			if serr := w.deps.Detections.SetExportStatus(context.WithoutCancel(ctx), doc.EventID, StatusFailed); serr != nil {
				w.deps.Logger.Error("export status update failed", "event_id", doc.EventID, "err", serr)
			}
		}
		delay := w.deps.RetryInitial << attempts
		if delay <= 0 || delay > w.deps.RetryMax {
			delay = w.deps.RetryMax
		}
		w.retries = append(w.retries, retryItem{docs: docs, attempts: attempts + 1, next: time.Now().Add(delay)})
		return
	}
	// Success: prefer at-most-once sheet rows over at-least-once progress.
	// A status write that fails here is logged but not retried, because the
	// rows are already in the sink and re-exporting would duplicate them.
	for _, doc := range docs {
		if serr := w.deps.Detections.SetExportStatus(ctx, doc.EventID, StatusExported); serr != nil {
			w.deps.Logger.Error("export status update failed", "event_id", doc.EventID, "err", serr)
		}
	}
	w.deps.Logger.Info("exported batch", "count", len(docs))
}

// row builds one enriched row. Registration lookups are best effort: a
// missing or unreachable drone/owner yields empty fields, never a failed
// export.
func (w *Worker) row(ctx context.Context, doc *model.StoredDetection) []any {
	var drone *model.Drone
	if doc.Drone != nil && w.deps.Drones != nil {
		var err error
		drone, err = w.deps.Drones.FindBySerial(ctx, doc.Drone.SerialNumber)
		if err != nil {
			w.deps.Logger.Warn("export drone lookup failed", "event_id", doc.EventID, "err", err)
		}
	}
	ownerName := ""
	if drone != nil && w.deps.Owners != nil {
		if owner, err := w.deps.Owners.FindByID(ctx, drone.OwnerID); err != nil {
			w.deps.Logger.Warn("export owner lookup failed", "event_id", doc.EventID, "err", err)
		} else if owner != nil {
			ownerName = owner.Name
		}
	}
	return Row(doc, drone, ownerName)
}

// requeue loads detections left pending or failed by an earlier run, oldest
// first, so nothing is lost across restarts.
func (w *Worker) requeue(ctx context.Context) {
	for {
		if err := ctx.Err(); err != nil {
			return
		}
		docs, err := w.deps.Detections.FindUnexported(ctx, w.deps.RequeuePage)
		if err != nil {
			w.deps.Logger.Error("export requeue failed", "err", err)
			return
		}
		if len(docs) == 0 {
			return
		}
		w.deps.Logger.Info("export requeue", "count", len(docs))
		w.pending = append(w.pending, docs...)
		if len(docs) < w.deps.RequeuePage {
			return
		}
	}
}
