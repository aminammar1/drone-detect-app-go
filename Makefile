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
# Source selection for YOLO runs (all optional, quoted: names may contain spaces):
#   make yolo VIDEO="my clip.mp4"        single video file (bare name ok, searched in videos)
#   make yolo IMAGE="shot.png"           single image file (bare name ok, searched in images)
#   make yolo SOURCE="videos/test1.mp4"  any file, folder, webcam index, or URL
#   make yolo-pick                       picker over videos AND images (or pass VIDEO/IMAGE/SOURCE)
#   make yolo-pick-images                picker over images folder only
# Precedence: SOURCE > VIDEO > IMAGE > default folder (yolo-pick default is both folders).
SOURCE ?=
VIDEO ?=
IMAGE ?=
PICK ?= 0
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

# No fine-tuned drone.pt yet (needs a labeled dataset, see docs/TRAINING.md):
# fall back to the pretrained stand-in so the live YOLO demo still runs.
ifeq ($(wildcard detector/models/drone.pt),)
export YOLO_WEIGHTS := yolo26n.pt
export YOLO_TARGET_CLASSES := airplane
export YOLO_CONF := 0.1
endif

# Resolve which source the yolo targets run on (SOURCE > VIDEO > IMAGE > folder).
ifneq ($(strip $(SOURCE)),)
YOLO_SRC := $(SOURCE)
else
ifneq ($(strip $(VIDEO)),)
YOLO_SRC := $(VIDEO)
else
ifneq ($(strip $(IMAGE)),)
YOLO_SRC := $(IMAGE)
else
YOLO_SRC := $(VIDEOS)
endif
endif
endif

ifneq ($(strip $(SOURCE)),)
YOLO_IMG_SRC := $(SOURCE)
else
ifneq ($(strip $(IMAGE)),)
YOLO_IMG_SRC := $(IMAGE)
else
ifneq ($(strip $(VIDEO)),)
YOLO_IMG_SRC := $(VIDEO)
else
YOLO_IMG_SRC := $(IMAGES)
endif
endif
endif

# Picker source: explicit SOURCE/VIDEO/IMAGE win, else both folders (media).
ifneq ($(strip $(SOURCE)),)
YOLO_PICK_SRC := $(SOURCE)
else
ifneq ($(strip $(VIDEO)),)
YOLO_PICK_SRC := $(VIDEO)
else
ifneq ($(strip $(IMAGE)),)
YOLO_PICK_SRC := $(IMAGE)
else
YOLO_PICK_SRC := media
endif
endif
endif

ifeq ($(PICK),1)
PICK_FLAG := --pick
else
PICK_FLAG :=
endif

# Latency tuning overrides (empty = use YOLO_CONF / YOLO_IMGSZ from env).
#   make yolo CONF=0.2 IMGSZ=480 MAXFPS=15   # faster, more boxes
#   make yolo CONF=0.4 IMGSZ=960             # slower, better small drones
#   make yolo STRIDE=2 MINFRAMES=5           # fewer inferences, stricter tracks
CONF ?=
IMGSZ ?=
MAXFPS ?= 10
STRIDE ?=
MINFRAMES ?=
ifneq ($(strip $(CONF)),)
CONF_FLAG := --conf $(CONF)
else
CONF_FLAG :=
endif
ifneq ($(strip $(IMGSZ)),)
IMGSZ_FLAG := --imgsz $(IMGSZ)
else
IMGSZ_FLAG :=
endif
ifneq ($(strip $(STRIDE)),)
STRIDE_FLAG := --stride $(STRIDE)
else
STRIDE_FLAG :=
endif
ifneq ($(strip $(MINFRAMES)),)
MINFRAMES_FLAG := --min-frames $(MINFRAMES)
else
MINFRAMES_FLAG :=
endif
PERF_FLAGS := $(CONF_FLAG) $(IMGSZ_FLAG) $(STRIDE_FLAG) $(MINFRAMES_FLAG)

.PHONY: help check seed clean-db server sim fake yolo yolo-images yolo-pick yolo-pick-images yolo-list yolo-list-images evaluate test

help: ## Show this list.
	@echo Targets (PORT=$(PORT), SCENARIO=$(SCENARIO)):
	@echo   make seed            wipe + re-create mock data
	@echo   make clean-db        drop the database (clean slate, no re-seed)
	@echo   make server          Go server, leave running (dashboard on PORT)
	@echo   make yolo            real YOLO on videos folder, leave running
	@echo   make yolo-images     real YOLO on images folder (one pass, then exits)
	@echo   make yolo-pick       picker over videos AND images (default media)
	@echo   make yolo-pick-images  picker over images folder only
	@echo   make yolo-list       list video sources without running YOLO
	@echo   make yolo-list-images  list image sources without running YOLO
	@echo   make sim             preload Remote ID beacons from SCENARIO
	@echo   make fake            scripted detections from SCENARIO (no YOLO needed)
	@echo   make evaluate        FP-min probe on videos folder
	@echo   make test            go test + pytest
	@echo   make check           verify every prerequisite (run this first)
	@echo Options: PORT=8080 SCENARIO=scenarios/demo1.json VIDEO=clip.mp4 IMAGE=shot.png SOURCE=videos/test1.mp4 PICK=1 CONF=0.2 IMGSZ=480 MAXFPS=15 STRIDE=2 MINFRAMES=5

check: ## Verify every prerequisite (run this first).
	$(PYTHON) scripts/check_env.py

seed: ## Wipe + re-create mock data (uv run: standalone script, own deps).
	$(UV) run tools/seed_db.py

clean-db: ## Drop the drone_detect_app database (clean slate, no re-seed).
	$(UV) run tools/seed_db.py --drop-only

server: ## Go server (leave running).
	cd server && go run ./cmd/server

sim: ## Preload Remote ID beacons from the scenario (no YOLO needed).
	$(UV) run tools/remote_id_sim.py --scenario $(SCENARIO) --mode preload

fake: ## Scripted detections from the scenario (no YOLO needed).
	$(UV) run tools/fake_detector.py --scenario $(SCENARIO)

yolo: ## Real YOLO detector on videos\ (summary per track at end).
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_SRC)" --clock video --display --max-fps $(MAXFPS) $(PICK_FLAG) $(PERF_FLAGS)

yolo-images: ## Real YOLO detector on images\ (one pass, then exits).
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_IMG_SRC)" --clock video $(PICK_FLAG) $(PERF_FLAGS)

yolo-pick: ## Interactive picker: choose which video/image to run.
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_PICK_SRC)" --clock video --display --max-fps $(MAXFPS) --pick $(PERF_FLAGS)

yolo-pick-images: ## Interactive picker over images folder only.
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_IMG_SRC)" --clock video --pick $(PERF_FLAGS)

yolo-list: ## List video sources without running YOLO.
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_SRC)" --list-sources

yolo-list-images: ## List image sources without running YOLO.
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_IMG_SRC)" --list-sources

evaluate: ## FP/min probe on videos\.
	cd detector && $(DETECTOR_PY) tools/evaluate.py --source $(VIDEOS) --weights yolo26n.pt --target-classes drone

test: ## Backend + detector tests.
	cd server && go test ./...
	cd detector && $(DETECTOR_PY) -m pytest -q
