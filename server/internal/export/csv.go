// CSV export: the EXPORT_BACKEND=csv sink and the Sheets failure fallback.
// One file per day: <dir>/detections-YYYY-MM-DD.csv with a header row.
package export

import (
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// CSVExporter appends rows to daily CSV files, creating them (with header)
// on first use. It is also the fallback sink when Sheets appends fail.
type CSVExporter struct {
	// Dir is data/exports (relative to the server working directory).
	Dir string
	// Now reports the current time; tests inject a fixed clock to check
	// day rotation.
	Now func() time.Time
}

// NewCSVExporter creates the export directory if needed. It needs no Google
// setup, so EXPORT_BACKEND=csv always works.
func NewCSVExporter(dir string) (*CSVExporter, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("csv export dir %q: %w", dir, err)
	}
	return &CSVExporter{Dir: dir, Now: time.Now}, nil
}

// Append adds rows to today's file, writing the header for a new file.
func (e *CSVExporter) Append(ctx context.Context, rows [][]any) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if len(rows) == 0 {
		return nil
	}
	path := filepath.Join(e.Dir, "detections-"+e.Now().Format("2006-01-02")+".csv")
	_, statErr := os.Stat(path)
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o644)
	if err != nil {
		return fmt.Errorf("csv open %q: %w", path, err)
	}
	defer func() {
		_ = f.Close()
	}()
	w := csv.NewWriter(f)
	if errors.Is(statErr, os.ErrNotExist) {
		if err := w.Write(Columns); err != nil {
			return fmt.Errorf("csv header %q: %w", path, err)
		}
	}
	for _, r := range rows {
		cells := make([]string, len(r))
		for i, v := range r {
			cells[i] = cell(v)
		}
		if err := w.Write(cells); err != nil {
			return fmt.Errorf("csv write %q: %w", path, err)
		}
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return fmt.Errorf("csv flush %q: %w", path, err)
	}
	return nil
}

// cell stringifies one row value for CSV. Numbers stay plain (no quotes
// unless the csv package needs them); times are RFC 3339 UTC.
func cell(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	case bool:
		return strconv.FormatBool(t)
	case int:
		return strconv.Itoa(t)
	case int64:
		return strconv.FormatInt(t, 10)
	case float64:
		return strconv.FormatFloat(t, 'f', -1, 64)
	case time.Time:
		return t.UTC().Format(time.RFC3339)
	default:
		return fmt.Sprint(t)
	}
}
