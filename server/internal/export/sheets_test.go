package export

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
)

// Only constructor failure paths are tested here: building the client is
// lazy, but a missing sheet ID or an unreadable key file must fail fast
// without any network call.
func TestSheetsRequiresSheetID(t *testing.T) {
	_, err := NewSheetsExporter(context.Background(), "", "")
	require.ErrorContains(t, err, "GOOGLE_SHEET_ID")
}

func TestSheetsBadCredentialsFile(t *testing.T) {
	_, err := NewSheetsExporter(context.Background(), `C:\nonexistent\key.json`, "sheet-id")
	require.Error(t, err)
}

// The append range must stay valid A1 notation (tab + columns) and span
// exactly len(Columns). A bare sheet name failed live with
// "Unable to parse range: detections" (400); this test locks the fix.
func TestSheetsRangeCoversColumns(t *testing.T) {
	require.Contains(t, detectionsRange, "!")
	require.True(t, len(detectionsRange) > 3)
	require.True(t, len(Columns) <= 26, "wider than A:Z needs a two-letter range update")
	last := string(rune('A' + len(Columns) - 1))
	require.Contains(t, detectionsRange, "detections!A:"+last)
}
