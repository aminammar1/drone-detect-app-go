// Sheets export (DESCRIPTION.md section 7): append rows to the `detections`
// tab with valueInputOption=USER_ENTERED so dates and numbers land typed.
package export

import (
	"context"
	"errors"
	"fmt"

	"google.golang.org/api/option"
	sheets "google.golang.org/api/sheets/v4"
)

// SheetsExporter appends rows to a Google Sheet. It holds only the API
// client and the sheet ID; credentials are never logged.
type SheetsExporter struct {
	service *sheets.Service
	sheetID string
}

// detectionsRange is the append target in A1 notation: the `detections` tab,
// columns A:T (the 20 Columns in export.go order). A bare sheet name fails
// with "Unable to parse range" on some spreadsheets; the explicit tab plus
// column span is robust. The tab must exist (the API never creates tabs).
const detectionsRange = "detections!A:T"

// NewSheetsExporter builds a Sheets client in one of two modes:
//
//   - Keyless (GOOGLE_CREDENTIALS_FILE empty, the recommended mode): uses
//     Application Default Credentials, i.e. whatever
//     `gcloud auth application-default login
//     --impersonate-service-account=<SA_EMAIL>` provisioned locally, or the
//     attached service account on Google Cloud.
//   - Key file: GOOGLE_CREDENTIALS_FILE points to a service account JSON key.
//
// A missing GOOGLE_SHEET_ID fails fast so a bad config never silently drops
// exports.
func NewSheetsExporter(ctx context.Context, credsFile, sheetID string) (*SheetsExporter, error) {
	if sheetID == "" {
		return nil, errors.New("GOOGLE_SHEET_ID is required when EXPORT_BACKEND=sheets")
	}
	opts := []option.ClientOption{option.WithScopes(sheets.SpreadsheetsScope)}
	if credsFile != "" {
		opts = append(opts, option.WithAuthCredentialsFile(option.ServiceAccount, credsFile))
	}
	svc, err := sheets.NewService(ctx, opts...)
	if err != nil {
		if credsFile == "" {
			return nil, fmt.Errorf("sheets client with application default credentials: %w", err)
		}
		return nil, fmt.Errorf("sheets client with credentials file: %w", err)
	}
	return &SheetsExporter{service: svc, sheetID: sheetID}, nil
}

// Append adds rows to the end of the `detections` tab.
func (e *SheetsExporter) Append(ctx context.Context, rows [][]any) error {
	if len(rows) == 0 {
		return nil
	}
	values := make([][]interface{}, len(rows))
	for i, r := range rows {
		values[i] = r // []any and []interface{} are the same type
	}
	_, err := e.service.Spreadsheets.Values.
		Append(e.sheetID, detectionsRange, &sheets.ValueRange{Values: values}).
		ValueInputOption("USER_ENTERED").
		InsertDataOption("INSERT_ROWS").
		Context(ctx).
		Do()
	if err != nil {
		return fmt.Errorf("sheets append %d rows: %w", len(rows), err)
	}
	return nil
}
