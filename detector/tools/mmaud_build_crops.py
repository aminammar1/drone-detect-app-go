"""Build balanced drone-crop dataset from extracted MMAUD_2D (V1 rooftop).

Reads (ignored, local-only):
    data/training/mmaud-2d/extracted/MMAUD_2D/{images,test}/{train2017,val2017,images}/
    .../labels/...  (YOLO single-class boxes) and .../test/labels/
Writes (ignored):
    data/training/mmaud-crops/{train,val,test}/{mavic2,mavic3,phantom4,avata,m300}/*.png
    data/training/mmaud-crops/manifest.csv

Verified label mapping (MMAUD_2D/README.md): b1=Mavic 2, b2=Mavic 3,
b3=Phantom 4, b4=Avata, b5=M300. Splits are temporal segments per bag;
a 30-frame margin is dropped at every train/val/test boundary to reduce
near-duplicate leakage. Train is balanced by even spacing (<=400/bag).
Crops are 1.5x GT boxes (min 24 px side); boxes <8 px are skipped and counted.
Empty label files (no drone visible) are counted and skipped.

Usage (from detector/):  uv run python tools\\mmaud_build_crops.py
"""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "data" / "training" / "mmaud-2d" / "extracted" / "MMAUD_2D"
DST = REPO / "data" / "training" / "mmaud-crops"

BAG_TO_FAMILY = {
    "b1": "mavic2",
    "b2": "mavic3",
    "b3": "phantom4",
    "b4": "avata",
    "b5": "m300",
}
SPLITS = {
    "train": ("images/train2017", "labels/train2017"),
    "val": ("images/val2017", "labels/val2017"),
    "test": ("test/images", "test/labels"),
}
MARGIN = 30
TRAIN_CAP_PER_BAG = 400
CROP_PAD = 1.5
MIN_CROP_SIDE = 24
MIN_BOX_PX = 8


def read_box(label_path: Path) -> tuple[float, float, float, float] | None:
    if not label_path.is_file():
        return None
    rows = [line.split() for line in label_path.read_text().splitlines() if line.strip()]
    if not rows:
        return None
    _, xc, yc, w, h = rows[0][:5]
    return float(xc), float(yc), float(w), float(h)


def main() -> None:
    rows_out: list[dict[str, str | int]] = []
    stats: dict[str, int] = {"skipped_tiny": 0, "skipped_empty": 0, "kept": 0}
    for split, (img_dir, lab_dir) in SPLITS.items():
        per_bag: dict[str, list[tuple[int, Path]]] = {}
        for img in sorted((SRC / img_dir).glob("*.png")):
            bag, num = img.stem.split("_")
            if bag not in BAG_TO_FAMILY:
                continue
            per_bag.setdefault(bag, []).append((int(num), img))
        for bag, items in per_bag.items():
            items.sort()
            lo, hi = items[0][0], items[-1][0]
            # Drop margin frames at segment edges (temporal leakage guard).
            items = [(n, p) for n, p in items if n - lo >= MARGIN and hi - n >= MARGIN]
            if split == "train" and len(items) > TRAIN_CAP_PER_BAG:
                step = len(items) / TRAIN_CAP_PER_BAG
                items = [items[int(i * step)] for i in range(TRAIN_CAP_PER_BAG)]
            family = BAG_TO_FAMILY[bag]
            out_dir = DST / split / family
            out_dir.mkdir(parents=True, exist_ok=True)
            for num, img_path in items:
                box = read_box(SRC / lab_dir / f"{img_path.stem}.txt")
                if box is None:
                    stats["skipped_empty"] += 1
                    continue
                with Image.open(img_path) as im:
                    w, h = im.size
                    xc, yc, bw, bh = box
                    x1, y1 = (xc - bw / 2) * w, (yc - bh / 2) * h
                    x2, y2 = (xc + bw / 2) * w, (yc + bh / 2) * h
                    if min(x2 - x1, y2 - y1) < MIN_BOX_PX:
                        stats["skipped_tiny"] += 1
                        continue
                    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                    side = max(x2 - x1, y2 - y1) * CROP_PAD
                    side = max(side, MIN_CROP_SIDE)
                    crop = im.crop(
                        (
                            int(max(0, cx - side / 2)),
                            int(max(0, cy - side / 2)),
                            int(min(w, cx + side / 2)),
                            int(min(h, cy + side / 2)),
                        )
                    )
                    dest = out_dir / f"{bag}_{num}.png"
                    crop.save(dest)
                rows_out.append(
                    {
                        "crop": dest.relative_to(REPO).as_posix(),
                        "split": split,
                        "family": family,
                        "bag": bag,
                        "frame": num,
                        "box_px": round(min(x2 - x1, y2 - y1), 1),
                    }
                )
                stats["kept"] += 1
    with (DST / "manifest.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["crop", "split", "family", "bag", "frame", "box_px"]
        )
        writer.writeheader()
        writer.writerows(rows_out)
    per_split: dict[str, dict[str, int]] = {}
    for row in rows_out:
        per_split.setdefault(str(row["split"]), {}).setdefault(str(row["family"]), 0)
        per_split[str(row["split"])][str(row["family"])] += 1
    print("per-split family counts:", per_split)
    print("stats:", stats, "manifest rows:", len(rows_out))


if __name__ == "__main__":
    main()
