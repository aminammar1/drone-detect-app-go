---
name: gin-server
description: Go Gin server work in server/cmd and server/internal (api, ws, identity, store, config). Use ONLY when editing, testing, or debugging the Go server, MongoDB repos, or WebSocket endpoints.
---

# Gin Server

Server lives in `server/`: `cmd/server/main.go` wires everything; `internal/...` holds the packages. There are no package-level globals.

## Conventions

- Router in `internal/api`: `gin.New()` with `gin.Recovery()` and a `log/slog` request-logging middleware. Never `gin.Default()`.
- WebSocket endpoints are Gin handlers upgraded with `gorilla/websocket`. One goroutine owns all writes per connection (send channel); never write concurrently.
- `context.Context` is the first parameter for DB and network calls; honor cancellation.
- Wrap errors with `fmt.Errorf("...: %w", err)`; structured logs carry `event_id`.
- MongoDB driver uses the `/v2` module path.
- Graceful shutdown: stop accepting connections, flush the export queue, then close MongoDB.

## Logic order (source of truth: DESCRIPTION.md sections 4-5)

1. Resolver (`internal/identity`): explicit identifier first, else beacons in the same zone within `BEACON_WINDOW_S` of `detected_at`, narrowed by visual attributes. Outcomes: identified, none, ambiguous, mismatch.
2. Decision engine: unidentified (none, ambiguous, mismatch, unregistered) before unauthorized (stolen/revoked, no-fly, no active authorization) before authorized. First match wins, evaluated on `detected_at`.

## Commands (PowerShell)

```powershell
cd server; go run .\cmd\server
cd server; go test ./...
cd server; go vet ./...; gofmt -l .
```
