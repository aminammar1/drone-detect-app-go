---
name: sheets-export
description: Google Sheets and CSV export work in server/internal/export (Columns, Row, SheetsExporter, CSVExporter, Worker). Use ONLY when editing export columns, sheet formatting, batching, fallback, or export tests.
---

# Sheets Export

One spreadsheet, one `detections` worksheet, one appended row per detection. Column order is defined in `DESCRIPTION.md` section 7 and `server/internal/export/export.go` (`Columns` + `Row`); change code and docs together, never one side alone.

## Behavior

- `EXPORT_BACKEND=csv|sheets` selects the sink. Default `csv` works with no Google setup.
- Sheets auth: service account, either keyless ADC (`GOOGLE_CREDENTIALS_FILE` empty) or a key file. Never log credentials.
- Appends use `valueInputOption=USER_ENTERED`, batched up to `EXPORT_BATCH_SIZE` rows or every `EXPORT_FLUSH_SECONDS`.
- On failure: write rows to `data/exports/detections-YYYY-MM-DD.csv`, mark `export_status=failed`, retry with backoff; on success mark `exported`.
- On startup: re-queue detections still `pending` or `failed`.
- The `detections` tab must exist; the API never creates tabs.

## Tests

Unit tests use a fake `Exporter`; never call real Google APIs in tests. Touch `row_test.go`, `csv_test.go`, `sheets_test.go`, and `worker_test.go` together when columns or ranges change.
