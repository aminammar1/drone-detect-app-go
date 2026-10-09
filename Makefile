# Drone Detect App — easy commands (Windows, macOS, Linux).
#
# Install `make` on Windows first (pick one):
#   choco install make            # Chocolatey (then use `make`)
#   winget install GnuWin32.Make   # Winget (then use `make`)
# Everything runs through make; there are no script wrappers.
#
# Copy-paste demo (two terminals, repo root):
#   make seed                       # wipe + re-create mock data (once)
#   make server                     # terminal 1: Go server, leave running
#   make yolo                       # terminal 2: real YOLO on videos\, leave running
#
# Full list: `make help`.

PORT ?= 8000
SCENARIO ?= scenarios/showcase.json
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
# Stand-in conf is 0.15, not 0.35: COCO scores real drones weakly (0.15-0.20 on
# our test images), so 0.35 silently misses them. Raise per run with CONF=...
# once drone.pt exists (then this whole block no longer applies).
ifeq ($(wildcard detector/models/drone.pt),)
export YOLO_WEIGHTS := yolo26n.pt
export YOLO_TARGET_CLASSES := airplane
export YOLO_CONF := 0.15
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
# MAXFPS throttles live streams (webcam) only; video/image files always run
# full speed (file pacing was removed: an 11 s clip must not take 30 s+).
# Explicit identity for testing the identified path on your own media
# (beacons only correlate with scenario timelines, not arbitrary files):
#   make yolo-pick IDENT=SEED000158Q100000
IDENT ?=
ifneq ($(strip $(IDENT)),)
IDENT_FLAG := --identifier-serial $(IDENT)
else
IDENT_FLAG :=
endif
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

.PHONY: help check gpu-check seed clean-db server dashboard sim fake yolo yolo-images yolo-pick yolo-pick-images yolo-list yolo-list-images webcam evaluate test

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
	@echo   make webcam          live YOLO on webcam 0 (q quits the window)
	@echo   make dashboard       open the live alerts page in a browser
	@echo   make gpu-check       show torch device (CUDA expected on NVIDIA GPUs)
	@echo   make evaluate        FP-min probe on videos folder
	@echo   make test            go test + pytest
	@echo   make check           verify every prerequisite (run this first)
	@echo Options: PORT=8080 SCENARIO=scenarios/demo1.json VIDEO=clip.mp4 IMAGE=shot.png SOURCE=videos/test1.mp4 PICK=1 CONF=0.2 IMGSZ=480 MAXFPS=15 STRIDE=2 MINFRAMES=5 IDENT=serial

check: ## Verify every prerequisite (run this first).
	$(PYTHON) scripts/check_env.py

gpu-check: ## Show the torch device (expect cuda=True on NVIDIA GPUs).
	$(PYTHON) -c "import torch; print('cuda=', torch.cuda.is_available())"

seed: ## Wipe + re-create mock data (uv run: standalone script, own deps).
	$(UV) run tools/seed_db.py

clean-db: ## Drop the drone_detect_app database (clean slate, no re-seed).
	$(UV) run tools/seed_db.py --drop-only

server: ## Go server (leave running).
	cd server && go run ./cmd/server

dashboard: ## Open the live alerts page in a browser.
	$(PYTHON) -m webbrowser http://localhost:$(PORT)/

sim: ## Preload Remote ID beacons from the scenario (no YOLO needed).
	$(UV) run tools/remote_id_sim.py --scenario $(SCENARIO) --mode preload

fake: ## Scripted detections from the scenario (no YOLO needed).
	$(UV) run tools/fake_detector.py --scenario $(SCENARIO)

yolo: ## Real YOLO detector on videos\ (summary per track at end).
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_SRC)" --clock video --display --max-fps $(MAXFPS) $(PICK_FLAG) $(PERF_FLAGS) $(IDENT_FLAG)

yolo-images: ## Real YOLO detector on images\ (one pass, then exits).
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_IMG_SRC)" --clock video $(PICK_FLAG) $(PERF_FLAGS) $(IDENT_FLAG)

yolo-pick: ## Interactive picker: choose which video/image to run.
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_PICK_SRC)" --clock video --display --max-fps $(MAXFPS) --pick $(PERF_FLAGS) $(IDENT_FLAG)

yolo-pick-images: ## Interactive picker over images folder only.
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_IMG_SRC)" --clock video --pick $(PERF_FLAGS) $(IDENT_FLAG)

yolo-list: ## List video sources without running YOLO.
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_SRC)" --list-sources

yolo-list-images: ## List image sources without running YOLO.
	cd detector && $(DETECTOR_PY) -m detector.main --source "$(YOLO_IMG_SRC)" --list-sources

webcam: ## Live YOLO on webcam 0 (leave running, q quits the window).
	cd detector && $(DETECTOR_PY) -m detector.main --source 0 --clock wall --display --max-fps $(MAXFPS) $(PERF_FLAGS)

# Probe weights/classes mirror the YOLO_* fallback above: COCO weights know no
# 'drone' class, so scoring 'drone' on yolo26n.pt is a silent zero.
EVAL_WEIGHTS := $(if $(wildcard detector/models/drone.pt),detector/models/drone.pt,yolo26n.pt)
EVAL_CLASSES := $(if $(wildcard detector/models/drone.pt),drone,airplane)

evaluate: ## FP/min probe on videos\.
	cd detector && $(DETECTOR_PY) tools/evaluate.py --source $(VIDEOS) --weights $(EVAL_WEIGHTS) --target-classes $(EVAL_CLASSES)

test: ## Backend + detector tests.
	cd server && go test ./...
	cd detector && $(DETECTOR_PY) -m pytest -q
