# Drone Detect App

Detect drones with YOLO (Python) and authorize them against MongoDB via a Go
(Gin) server. Every detection is logged to Google Sheets (CSV fallback) and
pushed live to a dashboard.

Docs: `PROJECT.md` (architecture + roadmap), `DESCRIPTION.md` (contracts —
source of truth), `docs/TRAINING.md` (M8: dataset + fine-tuning),
`docs/ARCHITECTURE.md` (diagrams + repo map).

## Quick start (Windows PowerShell)

Prereqs: MongoDB Community Server at `mongodb://localhost:27017`,
repo-root `.env` copied from `.env.example`.

Easiest way — `make` (2 commands, 2 terminals, repo root):

```powershell
choco install make -y   # once, from an ADMIN PowerShell (or: winget install GnuWin32.Make)
make seed               # once: wipe + re-create mock data
make server             # terminal 1: Go server, leave running (http://localhost:8000/)
make yolo               # terminal 2: real YOLO on videos\, leave running
```

More: `make help` (`make yolo-images`, `make sim`, `make fake`, `make test`,
`make server PORT=8080`). No `make` / no install? Same thing without it:

```powershell
.\scripts\run-server.ps1   # terminal 1: Go server, leave running
.\scripts\run-yolo.ps1     # terminal 2: real YOLO on videos\, leave running
# .\scripts\run-yolo.ps1 -Source ..\images          # images instead
```

```powershell
# 1. Seed the DB
.\detector\.venv\Scripts\python.exe tools\seed_db.py

# 2. Run the server (new terminal, repo root)
cd server
go run .\cmd\server
# dashboard: http://localhost:8080/   health: http://localhost:8080/healthz

# 3. Run the detector (repo root, new terminal)
cd detector
.\.venv\Scripts\python.exe -m detector.main --source ..\images --clock video
.\.venv\Scripts\python.exe -m detector.main --source ..\videos --clock video
```

With pretrained weights (until M8 `drone.pt` is trained):

```powershell
$env:YOLO_WEIGHTS = "yolo26n.pt"
$env:YOLO_TARGET_CLASSES = "airplane"
$env:YOLO_CONF = "0.1"
.\.venv\Scripts\python.exe -m detector.main --source ..\images
```

Simulated Remote ID + fake detector (no YOLO needed):

```powershell
.\detector\.venv\Scripts\python.exe tools\remote_id_sim.py --scenario scenarios\demo1.json --mode preload
.\detector\.venv\Scripts\python.exe tools\fake_detector.py --scenario scenarios\demo1.json
```

Evaluate weights / FP probe:

```powershell
cd detector
.\.venv\Scripts\python.exe tools\evaluate.py --source ..\images --weights yolo26n.pt --target-classes airplane --conf 0.1
.\.venv\Scripts\python.exe tools\evaluate.py --source ..\videos --weights yolo26n.pt --target-classes drone
```

Sheets export: `EXPORT_BACKEND=sheets` + `GOOGLE_SHEET_ID` in `.env`
(keyless ADC default). Failures fall back to `server/data/exports/*.csv`.
Before the Sheets step, open the spreadsheet and add a tab named exactly:
`detections` (appends fail with 400 "Unable to parse range" until it exists).

## Demo script (`scripts\demo.ps1`)

One-command shortcuts for the full demo. Run from the **repo root**, each
task in its own terminal, in this order (default port is `8000` because a
local Apache/XAMPP already answers on `8080` — pass `-Port 8080` only if that
Apache is stopped):

```powershell
.\scripts\demo.ps1 check       # mongo ping, port free?, ADC present?, sheet-tab reminder
.\scripts\demo.ps1 seed        # wipe + re-create mock data
.\scripts\demo.ps1 server      # Go server (leave running) — dashboard: http://localhost:8000/
.\scripts\demo.ps1 sim         # preload Remote ID beacons from scenarios\demo1.json
.\scripts\demo.ps1 fake        # scripted detections, checks acks
.\scripts\demo.ps1 dashboard   # open live page in browser
.\scripts\demo.ps1 detect-video  # real YOLO on videos\ (leave running; falls back to yolo26n.pt + airplane class until detector\models\drone.pt is trained)
.\scripts\demo.ps1 evaluate    # FP/min probe on videos\
```

Other tasks / options:

```powershell
.\scripts\demo.ps1 detect-images                  # real YOLO on images\
.\scripts\demo.ps1 test                            # go test ./... + pytest
.\scripts\demo.ps1 fake -Scenario scenarios\demo1.json -Port 8080
.\scripts\demo.ps1 server -Port 8080
```

## Layout

- `detector/` YOLO + tracking + `visual` attributes (Stage B airframes always
  mapped; Stage C family classifier behind `ATTR_FAMILY_ENABLED`).
- `server/` Gin + WebSockets (`/ws/detector`, `/ws/beacons`, `/ws/alerts`),
  resolver, decision engine, Sheets/CSV export worker, console notifier.
- `tools/` seed, simulator, fake detector. `scenarios/` scenario JSON.
- `videos/`, `images/` read-only inputs (never committed). `data/` outputs.
- `docs/` training + architecture.

## Test

```powershell
cd server; go test ./...; go vet ./...
cd ..\detector; .\.venv\Scripts\python.exe -m pytest -q
```
