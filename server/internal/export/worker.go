// Worker batches exports with retry; Enqueue never blocks acks.
package export

import (
	"context"
	"log/slog"
	"time"

	"drone-detect-app/server/internal/model"
)

// Deps are injected; no globals.
type Deps struct {
	Logger        *slog.Logger
	Primary       Exporter
	Fallback      *CSVExporter // nil when the backend itself is csv
	Detections    ExportStore
	Drones        DroneLookup
	Owners        OwnerLookup
	BatchSize     int           // flush threshold
	FlushInterval time.Duration // flush cadence for partial batches
	RetryInitial  time.Duration // first retry delay
	RetryMax      time.Duration // backoff cap
	QueueSize     int           // export queue buffer
	RequeuePage   int           // startup requeue page size
	// ExportIdentifiedOnly mirrors the live enqueue gate: startup requeue
	// skips non-identified rows so a restart cannot export what the live
	// path would filter. MongoDB still keeps every detection.
	ExportIdentifiedOnly bool
}

type retryItem struct {
	docs     []*model.StoredDetection
	attempts int
	next     time.Time
}

// Worker exports stored detections in batches.
type Worker struct {
	deps    Deps
	queue   chan *model.StoredDetection
	done    chan struct{}
	pending []*model.StoredDetection
	retries []retryItem
}

// NewWorker applies defaults; run the result in a goroutine.
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

// Enqueue never blocks; overflow stays pending for startup requeue.
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

// Done closes after the final flush.
func (w *Worker) Done() <-chan struct{} {
	return w.done
}

// Run requeues, batches until ctx ends, then final-flushes.
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
			// Parent ctx is done; use a fresh budget for the final flush.
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
					// Preserve per-batch attempts so backoff keeps growing.
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

// flush appends one batch and records progress.
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
			// Must survive shutdown; detached from cancelled ctx.
			if ferr := w.deps.Fallback.Append(context.WithoutCancel(ctx), rows); ferr != nil {
				w.deps.Logger.Error("csv fallback write failed", "err", ferr)
			}
		}
		for _, doc := range docs {
			// Progress must survive shutdown.
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
	// Already in sink: no re-export on status-write failure; duplicates are worse.
	for _, doc := range docs {
		if serr := w.deps.Detections.SetExportStatus(ctx, doc.EventID, StatusExported); serr != nil {
			w.deps.Logger.Error("export status update failed", "event_id", doc.EventID, "err", serr)
		}
	}
	w.deps.Logger.Info("exported batch", "count", len(docs))
}

// row enriches best-effort; lookup failure yields blanks, never blocks export.
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

// requeue restores pending/failed rows so restarts lose nothing.
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
		kept := 0
		for _, doc := range docs {
			if w.deps.ExportIdentifiedOnly && doc.Identity.Result != model.IdentityIdentified {
				continue
			}
			w.pending = append(w.pending, doc)
			kept++
		}
		w.deps.Logger.Info("export requeue", "found", len(docs), "queued", kept)
		if len(docs) < w.deps.RequeuePage {
			return
		}
	}
}
