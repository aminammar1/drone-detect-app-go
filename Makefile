# Drone Detect App — easy commands (Windows, macOS, Linux).
#
# Install `make` on Windows first (pick one):
#   choco install make            # Chocolatey (then use `make`)
#   winget install GnuWin32.Make   # Winget (then use `make`)
# ...or skip make entirely and use the same shortcuts without installing
# anything: .\scripts\run-server.ps1  and  .\scripts\run-yolo.ps1
#
# Copy-paste demo (two terminals, repo root):
#   make seed                       # wipe + re-create mock data (once)
#   make server                     # terminal 1: Go server, leave running
#   make yolo                       # terminal 2: real YOLO on videos\, leave running
#
# Full list: `make help`.

PORT ?= 8000
SCENARIO ?= scenarios/demo1.json
# `uv` must be on PATH (one-time: setx PATH "%USERPROFILE%\.local\bin;%PATH%",
# then restart the terminal). Override with `make seed UV=C:\path\to\uv.exe`.
UV ?= uv
# Detector venv python (has YOLO + all detector deps; used for yolo/test).
# NOTE: Chocolatey `make` runs recipes with cmd.exe, not PowerShell/sh, so
# executables must use backslashes on Windows (`detector\.venv\...`).
# A leading `./` (`./.venv/...`) fails with "'.' is not recognized".
ifeq ($(OS),Windows_NT)
PYTHON ?= detector\.venv\Scripts\python.exe
# Relative python once `cd detector` has run (no leading ./ — cmd breaks on it).
DETECTOR_PY := .venv\Scripts\python.exe
VIDEOS := ..\videos
IMAGES := ..\images
else
PYTHON ?= detector/.venv/bin/python
DETECTOR_PY := ./.venv/bin/python
VIDEOS := ../videos
IMAGES := ../images
endif

# One port everywhere: server listens here, detector + simulator dial here.
# Default 8000 because a local Apache/XAMPP already answers on 8080.
export SERVER_ADDR := :$(PORT)
export WS_URL := ws://localhost:$(PORT)/ws/detector
export BEACON_WS_URL := ws://localhost:$(PORT)/ws/beacons

# No fine-tuned drone.pt yet (M8 needs a labeled dataset): fall back to the
# pretrained stand-in so the live YOLO demo still runs.
ifeq ($(wildcard detector/models/drone.pt),)
export YOLO_WEIGHTS := yolo26n.pt
export YOLO_TARGET_CLASSES := airplane
export YOLO_CONF := 0.1
endif

.PHONY: help check seed server sim fake yolo yolo-images evaluate test

help: ## Show this list.
	@echo "Targets (PORT=$(PORT), SCENARIO=$(SCENARIO)):"
	@echo "  make seed          wipe + re-create mock data"
	@echo "  make server        Go server, leave running (dashboard: http://localhost:$(PORT)/)"
	@echo "  make yolo          real YOLO on videos\, leave running"
	@echo "  make yolo-images   real YOLO on images\ (one pass, then exits)"
	@echo "  make sim           preload Remote ID beacons from \$$(SCENARIO)"
	@echo "  make fake          scripted detections from \$$(SCENARIO) (no YOLO needed)"
	@echo "  make evaluate      FP/min probe on videos\"
	@echo "  make test          go test + pytest"
	@echo "  make check         verify every prerequisite (run this first)"
	@echo "Options: make server PORT=8080 | make yolo SCENARIO=scenarios/demo1.json"

check: ## Verify every prerequisite (run this first).
	$(PYTHON) scripts/check_env.py

seed: ## Wipe + re-create mock data (uv run: standalone script, own deps).
	$(UV) run tools/seed_db.py

server: ## Go server (leave running).
	cd server && go run ./cmd/server

sim: ## Preload Remote ID beacons from the scenario (no YOLO needed).
	$(UV) run tools/remote_id_sim.py --scenario $(SCENARIO) --mode preload

fake: ## Scripted detections from the scenario (no YOLO needed).
	$(UV) run tools/fake_detector.py --scenario $(SCENARIO)

yolo: ## Real YOLO detector on videos\ (leave running).
	cd detector && $(DETECTOR_PY) -m detector.main --source $(VIDEOS) --clock video --display --max-fps 10

yolo-images: ## Real YOLO detector on images\ (one pass, then exits).
	cd detector && $(DETECTOR_PY) -m detector.main --source $(IMAGES) --clock video

evaluate: ## FP/min probe on videos\.
	cd detector && $(DETECTOR_PY) tools/evaluate.py --source $(VIDEOS) --weights yolo26n.pt --target-classes drone

test: ## Backend + detector tests.
	cd server && go test ./...
	cd detector && $(DETECTOR_PY) -m pytest -q
