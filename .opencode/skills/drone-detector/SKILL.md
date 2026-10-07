---
name: drone-detector
description: YOLO detector work in detector/, sources.py, tracking.py, events.py. Use ONLY when editing or running the Python detector, its tests, or tools/fake_detector.py and tools/remote_id_sim.py.
---

# Drone Detector

Python detector lives in `detector/src/detector/`. Input folders `videos/` and `images/` at the repo root are read-only: list at runtime, filter by extension, sort by name, never modify or commit their content.

## Conventions

- Type hints everywhere; `pydantic` models for events and config (`pydantic-settings`); `pathlib.Path` for paths.
- No work at import time; CLI via `typer` in `main.py`.
- Async only for the WebSocket client; run YOLO inference in an executor so it never blocks the event loop.
- No hard-coded paths or URLs; everything comes from env/config (see `DESCRIPTION.md` section 8).
- Event time (`detected_at`, beacon `timestamp`) drives all matching, never arrival time.
- `track_id` is temporary dedupe state only; it is never a drone identity. Identity comes from an explicit identifier or a beacon; visual attributes only verify or disambiguate.

## Key files

- `sources.py`: image/video/stream discovery (`resolve_media_sources`, `resolve_image_sources`).
- `detect.py`: YOLO wrapper (`Detector`, `TrackedDetection`, `annotate`, `airframe_from_class`).
- `tracking.py`: `TrackDeduplicator` with cooldown, tested with a fake clock.
- `events.py`: `DetectionEvent` wire model, must match `DESCRIPTION.md` section 3.1.
- `main.py`: CLI entrypoint, per-file processing, snapshot + emit flow.
- `ws_client.py`: reconnecting sender with bounded queue.
- `tools/fake_detector.py`, `tools/remote_id_sim.py`: scripted events and beacons from `scenarios/*.json`.

## Commands (PowerShell, repo root)

```powershell
cd detector; uv sync
cd detector; uv run python -m detector.main --source ..\videos\test1.mp4 --clock video
uv run tools\fake_detector.py --scenario scenarios\demo1.json
uv run tools\remote_id_sim.py --scenario scenarios\demo1.json --mode preload
uv run pytest
uv run ruff check . ; uv run ruff format .
```
