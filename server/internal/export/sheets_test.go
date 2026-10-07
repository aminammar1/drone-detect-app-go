package export

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
)

// Constructor must fail fast without network.
func TestSheetsRequiresSheetID(t *testing.T) {
	_, err := NewSheetsExporter(context.Background(), "", "")
	require.ErrorContains(t, err, "GOOGLE_SHEET_ID")
}

func TestSheetsBadCredentialsFile(t *testing.T) {
	_, err := NewSheetsExporter(context.Background(), `C:\nonexistent\key.json`, "sheet-id")
	require.Error(t, err)
}

// Bare sheet names 400; range must span len(Columns).
func TestSheetsRangeCoversColumns(t *testing.T) {
	require.Contains(t, detectionsRange, "!")
	require.True(t, len(detectionsRange) > 3)
	require.True(t, len(Columns) <= 26, "wider than A:Z needs a two-letter range update")
	last := string(rune('A' + len(Columns) - 1))
	require.Contains(t, detectionsRange, "detections!A:"+last)
}
