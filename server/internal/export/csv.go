// CSV is the csv backend and the Sheets fallback; one file per day.
package export

import (
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// CSVExporter appends to daily files, creating with header on first use.
type CSVExporter struct {
	// Dir is the export directory.
	Dir string
	// Now is injectable for day-rotation tests.
	Now func() time.Time
}

// NewCSVExporter ensures dir exists; needs no Google setup.
func NewCSVExporter(dir string) (*CSVExporter, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("csv export dir %q: %w", dir, err)
	}
	return &CSVExporter{Dir: dir, Now: time.Now}, nil
}

// Append adds rows to today's file, writing the header once.
func (e *CSVExporter) Append(ctx context.Context, rows [][]any) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if len(rows) == 0 {
		return nil
	}
	path, writeHeader, err := e.dailyPath()
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o644)
	if err != nil {
		return fmt.Errorf("csv open %q: %w", path, err)
	}
	defer func() {
		_ = f.Close()
	}()
	w := csv.NewWriter(f)
	if writeHeader {
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

// dailyPath keeps old-schema exports intact and starts a versioned file when
// the column contract changes, instead of mixing row widths in one CSV.
func (e *CSVExporter) dailyPath() (string, bool, error) {
	base := "detections-" + e.Now().Format("2006-01-02")
	for version := 1; ; version++ {
		name := base + ".csv"
		if version > 1 {
			name = fmt.Sprintf("%s-v%d.csv", base, version)
		}
		path := filepath.Join(e.Dir, name)
		header, exists, err := readCSVHeader(path)
		if err != nil {
			return "", false, fmt.Errorf("csv header %q: %w", path, err)
		}
		if !exists || len(header) == 0 || equalHeader(header, Columns) {
			return path, !exists || len(header) == 0, nil
		}
	}
}

func readCSVHeader(path string) ([]string, bool, error) {
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = f.Close() }()
	header, err := csv.NewReader(f).Read()
	if errors.Is(err, io.EOF) {
		return nil, true, nil
	}
	return header, true, err
}

func equalHeader(got, want []string) bool {
	if len(got) != len(want) {
		return false
	}
	for i := range want {
		if got[i] != want[i] {
			return false
		}
	}
	return true
}

// cell stringifies for CSV; times are RFC3339 UTC.
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
