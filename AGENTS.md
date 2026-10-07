# AGENTS.md — Instructions for AI coding assistants

(If your tool expects another filename, copy this file to `CLAUDE.md`, `.cursorrules`, etc.)

## Project in one paragraph

Drone Detect App detects drones with YOLO (Python, `uv`) and streams detection events over WebSocket to a Go server
built with **Gin**. The server resolves the drone's identity (explicit identifier, or simulated Remote ID beacons
correlated by zone and time, cross-checked with visual attributes), checks MongoDB, decides
**authorized / unauthorized / unidentified**, notifies alert clients, and logs every detection to Google Sheets
(CSV fallback). Read `PROJECT.md` (architecture, **pipeline diagrams**, versions, roadmap) and `DESCRIPTION.md`
(requirements, schemas, protocol, resolver and decision logic) **before writing any code**.

## Dependency policy: always the latest stable

- **Never invent or recall a version number.** Before adding a dependency, verify its latest stable version
  (web search, PyPI, `go list -m -u`, or the project's releases page).
- Go: `go get <module>@latest` then `go mod tidy`. Python: `uv add <package>`; refresh with `uv lock --upgrade`.
- The version table in `PROJECT.md` section 2 is a dated snapshot. If you find newer stable versions, use them and update that table (with the date).
- Do not use pre-release (alpha, beta, rc) versions unless I ask.
- If the newest Python/Go cannot be used because a dependency lacks support, use the newest compatible one and tell me why.
- Do not add dependencies silently: list each new dependency and its purpose first.

## Environment

- OS: **Windows 10/11**, shell: **PowerShell**. Do not assume bash, `rm -rf`, `export`, or `/` path separators in commands you give me.
- Python managed with **`uv`** (not pip, poetry, or conda). Install the latest stable Python with `uv python install`.
- Go: latest stable toolchain.
- MongoDB Community Server running locally at `mongodb://localhost:27017` (Windows service).
- Line endings normalized via `.gitattributes` (`* text=auto`).

## Commands

```powershell
# Detector
cd detector
uv sync
uv run python -m detector.main --source ..\videos\test1.mp4 --clock video
uv run python -m detector.main --source ..\images                       # all images in the folder
uv run pytest
uv run ruff check . ; uv run ruff format .

# Tools
uv run tools\seed_db.py                                   # wipes and re-creates mock data
uv run tools\seed_db.py --keep                            # adds without wiping
uv run tools\fake_detector.py --scenario scenarios\demo1.json
uv run tools\remote_id_sim.py --scenario scenarios\demo1.json --mode preload

# Server (Gin)
cd server
go run .\cmd\server
go test ./...
go vet ./...
gofmt -l .
```

## Input data (already provided by me)

- **`videos/`** — my test videos. Use them as detector **video sources** and in scenario files.
- **`images/`** — my test images. Use them as detector **image sources**.
- Treat both folders as **read-only inputs**: never modify, rename, move, or delete files there, and never commit them.
- **List the folders at runtime** (filter by extension, sort by name) instead of hard-coding file names. When you need example file names for a command or a scenario file, list the folder first and use real ones.
- If a folder is empty or missing, tell me where to put files; do not invent test data.
- Details: `DESCRIPTION.md` section 12.

## Source of truth

- **Schemas, WebSocket messages, resolver algorithm, decision order, Sheets columns, scenario format:** `DESCRIPTION.md`. Do not invent fields.
  If a change is needed, update `DESCRIPTION.md` in the same change and say so.
- **Pipeline, architecture, milestone order, versions:** `PROJECT.md`. Keep the Mermaid diagrams in sync with the code when the flow changes.

## How to work

1. **One milestone at a time** (M0, M1, ... in `PROJECT.md` section 8). Do only what I ask.
2. **Plan first:** 3–6 lines, then implement. Ask me only if a decision truly blocks you; otherwise state your assumption and continue.
3. **Small, runnable steps.** After each step, give the exact PowerShell command and the expected output.
4. **Tests with the code**, especially:
   - Go: table-driven tests for the **identity resolver** and the **decision engine**, covering every branch and every required test case in `DESCRIPTION.md` section 6.
   - Python: tracking/dedupe/cooldown logic (fake clock, fake detections) and event validation.
5. **No placeholder code** that pretends to work. If something is not built yet, fail loudly or leave it out.
6. Small functions, clear names; comment the *why*, not the *what*.

## Code conventions

**Go (Gin)**
- Layout: `cmd/server/main.go` + `internal/...`. Wire dependencies in `main`; no globals.
- Router in `internal/api`: `gin.New()` with `gin.Recovery()` and a `log/slog` request-logging middleware. No `gin.Default()`.
- WebSocket endpoints are Gin handlers that upgrade with `gorilla/websocket` (`upgrader.Upgrade(c.Writer, c.Request, nil)`).
  One goroutine owns all writes per connection (send channel); never write concurrently.
- `context.Context` is the first parameter for DB and network calls; honor cancellation.
- Wrap errors: `fmt.Errorf("...: %w", err)`. Structured logs with `event_id`.
- MongoDB driver: use the `/v2` module path.
- Graceful shutdown (flush export queue, close MongoDB).

**Python**
- Type hints everywhere; `pydantic` models for events and config (`pydantic-settings`); `pathlib.Path` for paths.
- No work at import time; CLI via `typer`.
- Async only where needed (WebSocket). Run YOLO inference in an executor so it never blocks the event loop.
- No hard-coded paths or URLs; use env/config.

## Boundaries — never do these

- Never commit secrets or large artifacts: `.env`, `secrets/`, Google credentials, `*.pt` weights, `videos/` and `images/` content, snapshots, `data/`.
- Never modify, rename, move, or delete anything inside `videos/` or `images/`.
- Never run commands that delete data outside this repository. The seed tool may drop only the `drone_detect_app` database.
- Never change database/collection names, the WebSocket contract, or the decision order without updating `DESCRIPTION.md`.
- **Never use `track_id` as a drone identity.** It is temporary and only for dedupe.
- **Never claim the system identifies a drone from pixels alone.** Identity comes from an explicit identifier or a beacon; visual attributes only verify or disambiguate.
- Use **event time** (`detected_at`, beacon `timestamp`) for all matching, never arrival time.
- Do not call real Google APIs in unit tests; use an interface and a fake.

## Definition of done (per task)

- [ ] Runs on Windows PowerShell with the commands above
- [ ] Tests added or updated and passing (`go test ./...`, `uv run pytest`)
- [ ] `gofmt`, `go vet`, `ruff` clean
- [ ] Dependencies are the latest stable; table in `PROJECT.md` updated if anything changed
- [ ] `DESCRIPTION.md` / `PROJECT.md` (including diagrams) updated if contracts, flow, or structure changed
- [ ] Short summary: what changed, how to run it, what is next

## When you are unsure

Prefer the simplest approach that satisfies `DESCRIPTION.md`, state the trade-off in one or two sentences, and keep going.
Ask a question only when the answer changes the data model or the protocol.
