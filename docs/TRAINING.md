# Training drone weights (M8)

Fine-tune the latest Ultralytics YOLO model (YOLO26) for drones on Windows,
with and without an NVIDIA GPU. Result lands in `detector/models/`.

## 0. Current weights — no training needed (verified 2026-10-09)

`detector/models/drone.pt` is **not** locally trained. It is a copy of
`yolo11n_drone.pt` from `marie-kjelberg/drone-detector` on Hugging Face Hub
(YOLO11n nano, single class `drone`, ~5 MB, AGPL-3.0 like Ultralytics itself):

```powershell
cd detector
$p = .\.venv\Scripts\python.exe -c "from huggingface_hub import hf_hub_download; print(hf_hub_download(repo_id='marie-kjelberg/drone-detector', filename='yolo11n_drone.pt'))"
Copy-Item $p.Trim() models\drone.pt
```

Why this one: no public YOLO26 drone weights exist yet, and YOLO11 `.pt`
loads fine under Ultralytics 8.4.174. Two candidates were tried on our own
`images/` at conf 0.35 — `QuincySorrentino/AeroYOLO` (`best.pt`, 3 classes)
saw **nothing** even at 0.05, while `yolo11n_drone.pt` gives `drone 0.87` on
`image.png` and six `drone` boxes (0.87–0.92) on
`hexacopter-drones-flying.webp`. End to end (`make yolo-images
IDENT=SEED000158Q100000`): 7 events, `class=drone`, all acked `authorized`
as `DJI Mavic 3`. No published precision/recall is known for these weights;
the local fine-tune path below (M8) stays the route to measured metrics.
Re-check the Hub for YOLO26 drone weights before spending GPU time.

> Versions seen here: Ultralytics 8.4.174, Torch 2.14.1, `yolo26n.pt` base.
> If `uv lock --upgrade` moves these, re-check the Ultralytics docs — the
> CLI below (`YOLO(...).train(...)`) is stable across YOLO26 patches.

## 1. Assemble the dataset

Layout (YOLO detection format):

```
datasets/drone/
  images/train/  images/val/
  labels/train/  labels/val/
  drone.yaml
```

`drone.yaml`:

```yaml
path: datasets/drone
train: images/train
val: images/val
names:
  0: drone
```

Stage B (multi-class airframes, PROJECT.md 5.4) uses one class per airframe
instead — names must be a subset of the server enum
(`quadcopter, hexacopter, octocopter, fixed_wing, vtol, helicopter`):

```yaml
names:
  0: quadcopter
  1: fixed_wing
  2: helicopter
```

Rules:

- Recommended base (verified 2026-10-07): `lgrzybowski/seraphim-drone-detection-dataset`
  on Hugging Face — 75k train / 8k test, YOLO format, single `drone` class,
  CC BY 4.0 (attribute the source datasets). It aggregates 23 open sets, so
  you skip format conversion. For hard negatives and Stage B airframes, add a
  subset of `Drones Comprehensive Merged` (Roboflow Universe, 101k, includes
  bird/airplane/helicopter + Fixed-Wing/Multi-Rotor labels) — clean its 9
  overlapping names down to our enum first.
- Sources: public drone sets (Roboflow Universe, Kaggle drone sets). Keep the
  license note from PROJECT.md 2 (AGPL-3.0 for Ultralytics).
- Drones are small: keep high-res frames, prefer `imgsz` 960–1280 or tiling
  at inference (DESCRIPTION.md 10).
- **Hard negatives are mandatory.** Add background images (empty `.txt` label
  files) containing birds, planes, kites, helicopters — the exact confusers
  COCO-pretrained YOLO fires on (DESCRIPTION.md 10). Aim for 10–20% of the
  training set as negatives. For Stage B, label a helicopter as `helicopter`
  (a real class); a distant bird stays background (empty label).
- Split: 80/10/10 or 80/20 train/val at minimum; never validate on training
  frames from the same video clip (leaks via near-duplicates).
- Keep a short **drone-free video** in `videos/` — it is the false-positive
  probe for `tools/evaluate.py` (FP/min must drop after fine-tuning).

Stage C (family classifier prototype): the public
[`cranfield-synthetic-drone-classification`](https://huggingface.co/datasets/mazqtpopx/cranfield-synthetic-drone-classification)
dataset is CC BY 4.0 and has synthetic DJI Mavic, Phantom, Inspire, and No
Drone classes. It demonstrates family-level recognition; it cannot recognize
exact SKUs such as Mavic 3. The synthetic-to-real gap means you must validate
on held-out real camera crops before presenting accuracy claims.

```powershell
New-Item -ItemType Directory -Force data\training | Out-Null
curl.exe --location --fail --output data\training\cranfield-synthetic-drone-classification.zip `
  'https://huggingface.co/datasets/mazqtpopx/cranfield-synthetic-drone-classification/resolve/main/cranfield-synthetic-drone-classification.zip?download=true'
Expand-Archive -Path data\training\cranfield-synthetic-drone-classification.zip `
  -DestinationPath data\training\cranfield-synthetic-drone-classification -Force
cd detector
uv run tools\train_family_classifier.py --epochs 8 --fraction 0.15
$env:ATTR_FAMILY_ENABLED = "true"
$env:ATTR_FAMILY_CONF = "0.75"
uv run python -m detector.main --source ..\images --clock video
uv run tools\render_family_showcase.py --source ..\images --output-dir ..\screenshots
```

The quick command uses a deterministic 15% subset of the stratified training
split and the complete validation split. Set `--fraction 1.0` for full training;
on CPU this takes substantially longer.

For a real product-family classifier, replace the synthetic images with
properly licensed real images grouped by family, use separate train/validation
sources, and retain attribution. At least 200 varied crops per family is a
starting point, not a performance guarantee. Do not label a family prediction
as a registered exact model.

## 2. Train (Windows PowerShell)

GPU check first:

```powershell
cd detector
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

- `True` → CUDA build, training uses the GPU automatically.
- `False` → CPU-only build. Training works but is ~10–50x slower; use fewer
  epochs for smoke tests, or install the CUDA PyTorch build per the official
  PyTorch selector, then continue.

Detection model (Stage A single-class, or Stage B multi-class — same command,
different `drone.yaml`):

```powershell
cd detector
.\.venv\Scripts\python.exe -c "
from ultralytics import YOLO
m = YOLO('yolo26n.pt')
m.train(data='../datasets/drone/drone.yaml', epochs=100, imgsz=960, batch=-1, patience=20, name='drone26n')
"
```

Family classifier (Stage C, optional):

```powershell
.\.venv\Scripts\python.exe -c "
from ultralytics import YOLO
m = YOLO('yolo26n-cls.pt')
m.train(data='../datasets/family', epochs=50, imgsz=224, name='family26n-cls')
"
```

Notes:

- `batch=-1` lets Ultralytics pick what fits your VRAM/RAM. On a 4 GB card
  (e.g. GTX 1650 Max-Q) use `batch=8`, `imgsz=640` for the smoke run; `imgsz=960`
  may OOM — stay at 640 if so, or train the full run on Colab (A100/L4).
- Small data? Start `epochs=20` as a smoke test, then 100+.
- Resume: `YOLO('runs/detect/drone26n/weights/last.pt').train(resume=True)`.

## 3. Evaluate (precision, recall, mAP50)

```powershell
.\.venv\Scripts\python.exe -c "
from ultralytics import YOLO
m = YOLO('runs/detect/drone26n/weights/best.pt')
print(m.val(data='../datasets/drone/drone.yaml', imgsz=960))
"
```

Report on the held-out val set: **precision, recall, mAP50** (and mAP50-95
for context). Ship only when precision/recall beat the pretrained baseline
on your val clips. Then the FP probe:

```powershell
.\.venv\Scripts\python.exe tools/evaluate.py --source ..\videos --weights runs/detect/drone26n/weights/best.pt --target-classes drone
.\.venv\Scripts\python.exe tools/evaluate.py --source ..\videos --weights runs/detect/drone26n/weights/best.pt --target-classes quadcopter,fixed_wing,helicopter
```

On the drone-free video every box is a false positive — FP/min must be near
zero after fine-tuning.

## 4. Install the weights

```powershell
Copy-Item runs/detect/drone26n/weights/best.pt detector/models/drone.pt
# Stage B: same file, but set YOLO_TARGET_CLASSES to your airframe list:
#   $env:YOLO_TARGET_CLASSES = "quadcopter,fixed_wing,helicopter"
# Stage C (optional):
Copy-Item runs/classify/family26n-cls/weights/best.pt detector/models/family.pt
#   $env:ATTR_FAMILY_ENABLED = "true"
```

`detector/models/*.pt` is gitignored — never commit weights. Restart the
detector; `detect.py` logs the weights path, `attributes.py` logs the family
model. With airframe classes, events carry `visual.airframe_type` (Stage B);
with the classifier on, they also carry `visual.model_family` (Stage C).

## 5. Hugging Face fallback (Stage D, only if justified)

Stay with YOLO-cls unless it clearly fails: val accuracy on your crops stays
low (< ~85% top-1 on held-out families) after more crops and longer training,
or families are visually near-identical at your camera distance. Then — and
only then — consider a Hugging Face backbone (e.g. a DINOv2-style vision
model via `transformers`, PROJECT.md 5.4) with a small classification head.
It costs a new dependency, more VRAM, and a custom training loop for what is
still only soft evidence (never identity). Treat it as an experiment, not the
default path.
