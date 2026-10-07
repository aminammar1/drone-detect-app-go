# Detector

YOLO detector (Python, `uv`). See `PROJECT.md` and `DESCRIPTION.md` in the repo root.

M3 (images) usage — server running, DB seeded:

```powershell
cd detector
$env:YOLO_WEIGHTS = "yolo26n.pt"        # pretrained stand-in until M8 drone weights
$env:YOLO_TARGET_CLASSES = "airplane"
$env:YOLO_CONF = "0.1"                  # COCO sees the test drone faintly
uv run python -m detector.main --source images                 # whole folder
uv run python -m detector.main --source images\image.png --identifier-serial <serial>
```

M4 (video) usage — ByteTrack tracking, one event per track + cooldown:

```powershell
uv run python -m detector.main --source videos --clock video  # whole folder
uv run python -m detector.main --source videos\<file>.mp4 --clock wall --display --max-fps 10
uv run python -m detector.main --source 0                     # webcam index
uv run python -m detector.main --source rtsp://host:8554/live
```

`--clock video` stamps `detected_at = SCENARIO_START + frame/fps` (deterministic
replay); `--clock wall` uses the real clock (forced for live streams).
`--display` shows annotated frames (`q` quits); `--max-fps` caps the rate.

Visual attributes (M8):

- Stage B: train with airframe classes (`quadcopter`, `fixed_wing`, ...,
  see `docs/TRAINING.md`) and set `YOLO_TARGET_CLASSES` to that list.
  The class maps to `visual.airframe_type` automatically; generic `drone`
  or stand-ins omit `visual`.
- Stage C (optional): train `detector/models/family.pt` (YOLO-cls) and set
  `ATTR_FAMILY_ENABLED=true` (+ optional `ATTR_FAMILY_WEIGHTS`,
  `ATTR_FAMILY_CONF`). Adds `visual.model_family` per emitted crop.
