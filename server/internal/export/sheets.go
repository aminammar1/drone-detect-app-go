// Sheets appends to the detections tab; USER_ENTERED keeps types (DESCRIPTION.md section 7).
package export

import (
	"context"
	"errors"
	"fmt"

	"google.golang.org/api/option"
	sheets "google.golang.org/api/sheets/v4"
)

// SheetsExporter appends rows; never logs credentials.
type SheetsExporter struct {
	service *sheets.Service
	sheetID string
	// headerEnsured skips repeat checks; single-goroutine use only.
	headerEnsured bool
}

// detectionsRange needs explicit tab+span; bare names 400, and the API never creates tabs.
const detectionsRange = "detections!A:T"

// NewSheetsExporter uses ADC when credsFile is empty, else a key file; missing sheet ID fails fast.
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

// Append adds rows to the detections tab.
func (e *SheetsExporter) Append(ctx context.Context, rows [][]any) error {
	if len(rows) == 0 {
		return nil
	}
	if !e.headerEnsured {
		if err := e.ensureHeader(ctx); err != nil {
			return fmt.Errorf("sheets header: %w", err)
		}
		e.headerEnsured = true
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

// headerRange is row 1 of the detections tab.
const headerRange = "detections!A1:T1"

// ensureHeader writes/formats row 1 once; matching sheets untouched.
func (e *SheetsExporter) ensureHeader(ctx context.Context) error {
	got, err := e.service.Spreadsheets.Values.Get(e.sheetID, headerRange).Context(ctx).Do()
	if err != nil {
		return fmt.Errorf("read header: %w", err)
	}
	if len(got.Values) > 0 && len(got.Values[0]) == len(Columns) {
		match := true
		for i, want := range Columns {
			if i >= len(got.Values[0]) || fmt.Sprint(got.Values[0][i]) != want {
				match = false
				break
			}
		}
		if match {
			return nil
		}
	}
	header := make([]interface{}, len(Columns))
	for i, h := range Columns {
		header[i] = h
	}
	if _, err := e.service.Spreadsheets.Values.
		Update(e.sheetID, headerRange, &sheets.ValueRange{Values: [][]interface{}{header}}).
		ValueInputOption("USER_ENTERED").Context(ctx).Do(); err != nil {
		return fmt.Errorf("write header: %w", err)
	}
	// Styling is best-effort; data already landed.
	_ = e.formatHeader(ctx)
	return nil
}

// formatHeader freezes/bolds row 1 with filter.
func (e *SheetsExporter) formatHeader(ctx context.Context) error {
	meta, err := e.service.Spreadsheets.Get(e.sheetID).
		Fields("sheets.properties").Context(ctx).Do()
	if err != nil {
		return err
	}
	var tabID int64 = -1
	for _, sh := range meta.Sheets {
		if sh.Properties != nil && sh.Properties.Title == "detections" {
			tabID = sh.Properties.SheetId
			break
		}
	}
	if tabID < 0 {
		return errors.New("detections tab not found")
	}
	_, err = e.service.Spreadsheets.BatchUpdate(e.sheetID, &sheets.BatchUpdateSpreadsheetRequest{
		Requests: []*sheets.Request{
			{
				RepeatCell: &sheets.RepeatCellRequest{
					Range:  &sheets.GridRange{SheetId: tabID, StartRowIndex: 0, EndRowIndex: 1, StartColumnIndex: 0, EndColumnIndex: int64(len(Columns))},
					Cell:   &sheets.CellData{UserEnteredFormat: &sheets.CellFormat{TextFormat: &sheets.TextFormat{Bold: true}}},
					Fields: "userEnteredFormat.textFormat.bold",
				},
			},
			{
				UpdateSheetProperties: &sheets.UpdateSheetPropertiesRequest{
					Properties: &sheets.SheetProperties{SheetId: tabID, GridProperties: &sheets.GridProperties{FrozenRowCount: 1}},
					Fields:     "gridProperties.frozenRowCount",
				},
			},
			{
				SetBasicFilter: &sheets.SetBasicFilterRequest{
					Filter: &sheets.BasicFilter{Range: &sheets.GridRange{SheetId: tabID, StartRowIndex: 0, EndRowIndex: 1, StartColumnIndex: 0, EndColumnIndex: int64(len(Columns))}},
				},
			},
		},
	}).Context(ctx).Do()
	return err
}
