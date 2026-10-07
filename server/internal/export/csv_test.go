package export

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestCSVHeaderAndRows(t *testing.T) {
	dir := t.TempDir()
	exp, err := NewCSVExporter(dir)
	require.NoError(t, err)
	fixed := time.Date(2026, 6, 9, 10, 0, 0, 0, time.UTC)
	exp.Now = func() time.Time { return fixed }

	rows := [][]any{
		Row(testDoc("e1"), testDrone(), "Amira Haddad"),
		Row(testDoc("e2"), nil, ""),
	}
	require.NoError(t, exp.Append(context.Background(), rows))
	// Header must not repeat.
	require.NoError(t, exp.Append(context.Background(), rows[:1]))
	require.NoError(t, exp.Append(context.Background(), nil))

	raw, err := os.ReadFile(filepath.Join(dir, "detections-2026-06-09.csv"))
	require.NoError(t, err)
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	require.Len(t, lines, 4, "header + 3 rows, got:\n%s", raw)
	require.Equal(t, strings.Join(Columns, ","), lines[0])
	require.Contains(t, lines[1], "e1,north-gate,cam-01,17,0.91,unauthorized")
	require.Contains(t, lines[1], "Amira Haddad")
	require.Contains(t, lines[2], "e2,")
}

func TestCSVDayRotation(t *testing.T) {
	dir := t.TempDir()
	exp, err := NewCSVExporter(dir)
	require.NoError(t, err)
	day1 := time.Date(2026, 6, 9, 23, 59, 0, 0, time.UTC)
	day2 := time.Date(2026, 6, 10, 0, 1, 0, 0, time.UTC)
	exp.Now = func() time.Time { return day1 }
	require.NoError(t, exp.Append(context.Background(), [][]any{Row(testDoc("e1"), nil, "")}))
	exp.Now = func() time.Time { return day2 }
	require.NoError(t, exp.Append(context.Background(), [][]any{Row(testDoc("e2"), nil, "")}))

	for _, name := range []string{"detections-2026-06-09.csv", "detections-2026-06-10.csv"} {
		raw, err := os.ReadFile(filepath.Join(dir, name))
		require.NoError(t, err, name)
		lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
		require.Len(t, lines, 2, "%s must have header + 1 row", name)
		require.Equal(t, strings.Join(Columns, ","), lines[0])
	}
}

func TestCSVBadDir(t *testing.T) {
	// A file path cannot become a directory.
	f := filepath.Join(t.TempDir(), "file")
	require.NoError(t, os.WriteFile(f, []byte("x"), 0o644))
	_, err := NewCSVExporter(filepath.Join(f, "exports"))
	require.Error(t, err)
}
