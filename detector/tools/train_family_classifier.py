"""Fine-tune a YOLO classification model for drone-family predictions.

The dataset is synthetic and only supports family-level labels. The output is
soft visual evidence, never a unique drone identity or exact SKU claim.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data" / "training" / "cranfield-synthetic-drone-classification"
DEFAULT_OUTPUT = ROOT / "detector" / "models" / "family.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument(
        "--fraction",
        type=float,
        default=0.15,
        help="fraction of the stratified training split to use (validation stays complete)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def find_imagefolder_root(path: Path) -> Path:
    """Find the nested ImageFolder root with per-class train and val splits."""
    image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    for train_dir in path.rglob("train"):
        candidate = train_dir.parent
        val_dir = candidate / "val"
        if not val_dir.is_dir():
            continue
        train_classes = {child.name for child in train_dir.iterdir() if child.is_dir()}
        val_classes = {child.name for child in val_dir.iterdir() if child.is_dir()}
        labels = {name.casefold().replace("_", " ") for name in train_classes}
        if (
            len(train_classes) >= 4
            and train_classes == val_classes
            and any("mavic" in name for name in labels)
        ):
            return candidate
    for candidate in (path, *path.rglob("*")):
        if not candidate.is_dir():
            continue
        populated = [
            child
            for child in candidate.iterdir()
            if child.is_dir()
            and any(file.suffix.lower() in image_extensions for file in child.rglob("*"))
        ]
        labels = {child.name.casefold().replace("_", " ") for child in populated}
        if len(populated) >= 4 and any("mavic" in name for name in labels):
            return candidate
    raise FileNotFoundError(
        f"could not find four labeled image folders beneath {path}; "
        "extract the Hugging Face archive into data/training first"
    )


def main() -> None:
    args = parse_args()
    if args.epochs < 1 or args.batch < 1 or not 0.0 < args.fraction <= 1.0:
        raise SystemExit("--epochs and --batch must be positive; --fraction must be in (0, 1]")
    data = find_imagefolder_root(args.data)
    runs = ROOT / "data" / "training" / "runs"
    model = YOLO("yolo26n-cls.pt")
    model.train(
        data=str(data),
        epochs=args.epochs,
        imgsz=224,
        batch=args.batch,
        fraction=args.fraction,
        workers=0,
        patience=5,
        project=str(runs),
        name="family26n-cls",
        exist_ok=True,
    )
    best = Path(model.trainer.best)
    if not best.is_file():
        raise FileNotFoundError(f"training completed without best weights: {best}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, args.output)
    print(f"saved family classifier: {args.output}")
    print("Labels are DJI Mavic, DJI Phantom, DJI Inspire, and No Drone family classes.")
    print("Validate on real camera crops before treating predictions as reliable.")


if __name__ == "__main__":
    main()
