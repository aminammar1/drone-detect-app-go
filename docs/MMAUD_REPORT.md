# MMAUD real-world family-classifier experiment — report (2026-10-10)

Local, non-commercial experiment. Attribution + license:
[MMAUD_ATTRIBUTION.md](MMAUD_ATTRIBUTION.md) (CC BY-NC-SA 4.0, Yuan et al.,
ICRA 2024). Runtime detector/server behavior, contracts, and
`detector/models/family.pt` are **unchanged**. The training/evaluation tools
are tracked under `detector/tools/`; raw data, crops, checkpoints, and demo
videos remain local under ignored `data/training/`. The 80% real-world target
was **not met**.

## 1. Data used (verified, not assumed)

- `MMAUD_2D.zip` (4.47 GB on disk): 4,427 RGB 1280×960 PNG frames (wide-angle/
  fisheye look) with YOLO-format single-class GT boxes, split by the authors
  into temporally contiguous per-bag segments:
  train 2,655 / val 887 / test 886 (bags b1..b5 = Mavic 2, Mavic 3, Phantom 4,
  Avata, M300 per the authors' README).
- MMAUD platform cameras are monochrome/fisheye (per authors' sensor docs), so
  this is **real wide-angle footage, not clean RGB close-ups**. GT is 3D Leica
  position; 2D boxes come with this export; **type labels are sequence-level**
  (one drone per bag) — no per-frame type annotation exists.
- Derived crops (`mmaud-crops/`, `manifest.csv`, 2,987 kept): 1.5× GT boxes
  (min 24 px side); boxes <8 px skipped (103); 30-frame margins dropped at every
  split boundary against near-duplicate leakage; train balanced by even spacing
  (≤400/bag): train 1,852 (398/364/396/344/350), val 551, test 584.
- Conditions: V1 rooftop, drones mostly small/far (typical GT box ~14–20 px;
  e.g. b3_1000 = 20×18 px). V1 flies below ~30 m; V2/V3 (different scenes,
  same drones) were not downloaded — Google Drive listing only, sizes unknown.

## 2. Training (candidate only; `family.pt` never overwritten)

```powershell
cd detector
uv run tools\train_family_classifier.py --data ..\data\training\mmaud-crops --fraction 1.0 --epochs 30 --output ..\data\training\mmaud-family-candidate.pt
```

Base `yolo26n-cls.pt`, imgsz 224, batch 32, CPU-only torch 2.14.1
(CUDA unavailable despite GTX 1650). Early stopping (patience 5): 10 epochs,
best epoch 5, val top1 **0.699**. Checkpoint:
`data/training/mmaud-family-candidate.pt` (3.2 MB). Run dir:
`data/training/runs/family26n-cls-mmaud/`. No new project dependencies
(`gdown 6.4.2` used ephemerally via `uv run --with` for the download only).

## 3. Held-out REAL test metrics (official test segment, threshold 0.5 calibrated on val)

`cd detector; uv run python tools\mmaud_eval.py` → `data\training\mmaud-eval.json`.
The checked-in metrics are in [MMAUD_EVALUATION.json](MMAUD_EVALUATION.json).

**Classifier-only, candidate (584 GT crops): acc 0.514, macro-F1 0.548,
unknown-rate 0.093.** Per class F1: m300 0.920, mavic3 0.636, phantom4 0.658,
mavic2 0.506, avata **0.020** (Avata test frames collapse into Mavic/Phantom).
Merging Mavic 2+3 into one "Mavic" family (the honest taxonomy at this
distance) gives **343/584 = 0.587** across Mavic, Phantom, Avata, and M300 —
still far from 0.80. On only the shared Mavic/Phantom families (338 crops), the
candidate scores **0.787** and the old `family.pt` scores **0.201** at the
same threshold. This subset excludes Avata and M300, and all test clips come
from flights also represented in training; it is not cross-scene evidence.

**Existing `family.pt` on the same split (mapped: Mavic 2/3→Mavic,
Phantom 4→Phantom, Avata/M300→unsupported): acc 0.118, unknown-rate 0.055**
— wrong taxonomy plus synthetic→fisheye gap, and overconfident (rarely
abstains out-of-distribution). Candidate beats it, but that bar is on the floor.

**End-to-end (YOLO `drone.pt` @0.35 → IoU≥0.3 match → candidate): 128/584
matched, miss rate 0.781; on matched crops acc 0.492, macro-F1 0.194.** Once
misses are included in the 584-object denominator, only **63/584 (0.108)** get
the correct family label. The matched-only score is conditional on the
detector finding the target and must not be presented as overall accuracy.
Per-bag match rate (all 885 test frames): b1 0.000, b2 0.014, b3 0.000,
b4 0.253, b5 0.765. The detector only sees large/close drones — this, not the
classifier, is the dominant end-to-end failure.

Threshold sweep on val: kept-accuracy rises only 0.699→0.747 while unknown-rate
explodes 0→0.354, so 0.5 was kept (unknown 3.6% val / 9.3% test).

## 4. Demo (offline, stoppable — plain MP4, no preview windows)

- `uv run python tools\mmaud_demo_video.py --bag b3` renders the Phantom 4 test
  segment (164 frames @10 fps). It contains only detector misses.
- `uv run python tools\mmaud_demo_video.py --bag b5` renders the M300 segment
  (136 frames @10 fps), including correct, incorrect, unknown, and missed
  examples. Output is under ignored `data/training/demo/mmaud/`.
- The LinkedIn examples in `screenshots/` show one correct M300 result and one
  Phantom detector miss. The zoom inset is for visibility; it does not change
  the model input or the evaluation.
- Track-vote aggregation (majority of confident crops per track, id for display
  only) is prototyped in the earlier synthetic demo script, not production.

## 5. Reproduce

```powershell
cd detector
uv run python tools\mmaud_build_crops.py   # needs MMAUD_2D extracted under data\training\mmaud-2d\
uv run tools\train_family_classifier.py --data ..\data\training\mmaud-crops --fraction 1.0 --epochs 30 --output ..\data\training\mmaud-family-candidate.pt
uv run python tools\mmaud_eval.py
uv run python tools\mmaud_demo_video.py --bag b5
uv run pytest            # 63 passed
uv run ruff check . ; uv run ruff format --check .
```

## 6. Limitations → what is actually needed

1. **Detector range**: 78% miss on 10–20 px fisheye targets. Fine-tune the
   detector on MMAUD or evaluate tiled/high-resolution inference before any
   end-to-end family claim.
2. **Avata collapse + Mavic2/3 confusion**: need more Avata flight regimes and
   closer-range crops; consider merging Mavic 2/3 into one supported family.
3. **Same-flight segments**: test is temporally held out but same flights —
   V2/V3 carpark sequences (different scenes, same 4 drones) are the right
   cross-scene test; not downloaded (Drive-only, sizes unknown).
4. Visual predictions remain soft evidence only: no identity/authorization
   impact, no contract changes — hence **no DESCRIPTION.md/PROJECT.md updates**.
