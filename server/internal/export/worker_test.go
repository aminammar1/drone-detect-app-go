package export

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"go.mongodb.org/mongo-driver/v2/bson"

	"drone-detect-app/server/internal/model"
)

// scriptExporter fails the first failLeft Appends; no network.
type scriptExporter struct {
	mu       sync.Mutex
	batches  []int
	total    int
	failLeft int
}

func (f *scriptExporter) Append(_ context.Context, rows [][]any) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.batches = append(f.batches, len(rows))
	f.total += len(rows)
	if f.failLeft > 0 {
		f.failLeft--
		return errors.New("sheets down")
	}
	return nil
}

func (f *scriptExporter) snapshot() (batches []int, total int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]int(nil), f.batches...), f.total
}

// fakeStore is an in-memory ExportStore/DroneLookup/OwnerLookup.
type fakeStore struct {
	mu       sync.Mutex
	statuses map[string]string
	requeue  []*model.StoredDetection
	drone    *model.Drone
	owner    *model.Owner
}

func (f *fakeStore) FindUnexported(_ context.Context, _ int) ([]*model.StoredDetection, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := f.requeue
	f.requeue = nil
	return out, nil
}

func (f *fakeStore) SetExportStatus(_ context.Context, eventID, status string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.statuses == nil {
		f.statuses = map[string]string{}
	}
	f.statuses[eventID] = status
	return nil
}

func (f *fakeStore) FindBySerial(_ context.Context, _ string) (*model.Drone, error) {
	return f.drone, nil
}

func (f *fakeStore) FindByID(_ context.Context, _ bson.ObjectID) (*model.Owner, error) {
	return f.owner, nil
}

func (f *fakeStore) status(eventID string) string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.statuses[eventID]
}

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func runWorker(t *testing.T, deps Deps) (*Worker, context.CancelFunc) {
	t.Helper()
	w := NewWorker(deps)
	ctx, cancel := context.WithCancel(context.Background())
	go w.Run(ctx)
	t.Cleanup(func() {
		cancel()
		<-w.Done()
	})
	return w, cancel
}

func TestWorkerSuccessAndEnrichment(t *testing.T) {
	primary := &scriptExporter{}
	st := &fakeStore{drone: testDrone(), owner: &model.Owner{Name: "Amira Haddad"}}
	w, _ := runWorker(t, Deps{
		Logger: testLogger(), Primary: primary,
		Detections: st, Drones: st, Owners: st,
		BatchSize: 10, FlushInterval: 20 * time.Millisecond,
	})

	w.Enqueue(testDoc("e1"))
	require.Eventually(t, func() bool { return st.status("e1") == StatusExported },
		3*time.Second, 10*time.Millisecond)
	_, total := primary.snapshot()
	require.Equal(t, 1, total)
}

func TestWorkerBatchesBySize(t *testing.T) {
	primary := &scriptExporter{}
	st := &fakeStore{}
	w, cancel := runWorker(t, Deps{
		Logger: testLogger(), Primary: primary,
		Detections: st, Drones: st, Owners: st,
		BatchSize: 2, FlushInterval: time.Hour, // size-triggered only
	})

	for _, id := range []string{"e1", "e2", "e3", "e4", "e5"} {
		w.Enqueue(testDoc(id))
	}
	// Leftovers flush on shutdown.
	require.Eventually(t, func() bool {
		_, total := primary.snapshot()
		return total == 4
	}, 3*time.Second, 10*time.Millisecond)
	cancel()
	<-w.Done()
	batches, total := primary.snapshot()
	require.Equal(t, 5, total)
	for _, n := range batches {
		require.LessOrEqual(t, n, 2)
	}
}

func TestWorkerFailureFallbackRetry(t *testing.T) {
	primary := &scriptExporter{failLeft: 1} // first append fails
	fallback, err := NewCSVExporter(t.TempDir())
	require.NoError(t, err)
	st := &fakeStore{}
	w, _ := runWorker(t, Deps{
		Logger: testLogger(), Primary: primary, Fallback: fallback,
		Detections: st, Drones: st, Owners: st,
		BatchSize: 10, FlushInterval: 20 * time.Millisecond,
		RetryInitial: 20 * time.Millisecond, RetryMax: 100 * time.Millisecond,
	})

	w.Enqueue(testDoc("e1"))
	// Failure writes CSV fallback and marks failed...
	require.Eventually(t, func() bool { return st.status("e1") == StatusFailed },
		3*time.Second, 10*time.Millisecond)
	entries, err := os.ReadDir(fallback.Dir)
	require.NoError(t, err)
	require.Len(t, entries, 1)
	raw, err := os.ReadFile(filepath.Join(fallback.Dir, entries[0].Name()))
	require.NoError(t, err)
	require.Contains(t, string(raw), "e1")
	// ...retry then marks exported.
	require.Eventually(t, func() bool { return st.status("e1") == StatusExported },
		3*time.Second, 10*time.Millisecond)
	_, total := primary.snapshot()
	require.GreaterOrEqual(t, total, 2, "initial attempt plus retry")
}

func TestWorkerRequeueOnStartup(t *testing.T) {
	primary := &scriptExporter{}
	stale := testDoc("stale-pending")
	stale.ExportStatus = StatusPending
	old := testDoc("old-failed")
	old.ExportStatus = StatusFailed
	st := &fakeStore{requeue: []*model.StoredDetection{stale, old}}
	w, _ := runWorker(t, Deps{
		Logger: testLogger(), Primary: primary,
		Detections: st, Drones: st, Owners: st,
		BatchSize: 10, FlushInterval: 20 * time.Millisecond,
	})
	_ = w
	for _, id := range []string{"stale-pending", "old-failed"} {
		require.Eventually(t, func() bool { return st.status(id) == StatusExported },
			3*time.Second, 10*time.Millisecond, id)
	}
	_, total := primary.snapshot()
	require.Equal(t, 2, total)
}

func TestWorkerRequeueRespectsIdentifiedOnly(t *testing.T) {
	primary := &scriptExporter{}
	identified := testDoc("is-identified")
	unidentified := testDoc("is-unidentified")
	unidentified.Identity = model.Identity{Method: model.MethodBeacon, Result: model.IdentityNone}
	st := &fakeStore{requeue: []*model.StoredDetection{identified, unidentified}}
	w, _ := runWorker(t, Deps{
		Logger: testLogger(), Primary: primary,
		Detections: st, Drones: st, Owners: st,
		BatchSize: 10, FlushInterval: 20 * time.Millisecond,
		ExportIdentifiedOnly: true,
	})
	_ = w
	require.Eventually(t, func() bool { return st.status("is-identified") == StatusExported },
		3*time.Second, 10*time.Millisecond)
	// The live enqueue gate must also hold across restarts: the unidentified
	// row is never queued, so it keeps no export status at all.
	require.Never(t, func() bool { return st.status("is-unidentified") != "" },
		500*time.Millisecond, 20*time.Millisecond)
	_, total := primary.snapshot()
	require.Equal(t, 1, total)
}

func TestWorkerEnrichmentFailureStillExports(t *testing.T) {
	primary := &scriptExporter{}
	st := &fakeStore{} // No drone/owner; lookups return nil.
	w, _ := runWorker(t, Deps{
		Logger: testLogger(), Primary: primary,
		Detections: st, Drones: st, Owners: st,
		BatchSize: 10, FlushInterval: 20 * time.Millisecond,
	})
	doc := testDoc("e1") // Claimed but unregistered.
	w.Enqueue(doc)
	require.Eventually(t, func() bool { return st.status("e1") == StatusExported },
		3*time.Second, 10*time.Millisecond)
}
