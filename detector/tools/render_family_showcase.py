"""Render visual-family labels on project images without contacting the server."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from detector.attributes import ModelFamilyClassifier, crop_box
from detector.config import get_settings
from detector.detect import Detector, TrackedDetection, annotate
from detector.sources import find_repo_root, resolve_under_root

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="image file or folder; defaults to IMAGES_DIR")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("screenshots"),
        help="where to write showcase copies; source images are read-only",
    )
    parser.add_argument(
        "--detection-only",
        action="store_true",
        help="render YOLO drone boxes without the experimental family classifier",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    repo_root = find_repo_root(Path(__file__).resolve())
    source = args.source or resolve_under_root(str(settings.images_dir), repo_root)
    if not source.is_absolute():
        from_cwd = Path.cwd() / source
        source = from_cwd if from_cwd.exists() else repo_root / source
    source = source.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if source.is_file():
        images = [source]
    elif source.is_dir():
        images = sorted(
            path
            for path in source.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
    else:
        raise SystemExit(f"image source does not exist: {source}")
    if not images:
        raise SystemExit(f"no supported images found in {source}")

    detector = Detector(
        weights=Path(settings.yolo_weights),
        conf=settings.yolo_conf,
        imgsz=settings.yolo_imgsz,
        target_classes={
            part.strip().lower() for part in settings.yolo_target_classes.split(",") if part.strip()
        },
        repo_root=repo_root,
    )
    classifier = None
    if not args.detection_only:
        classifier = ModelFamilyClassifier(
            weights=Path(settings.attr_family_weights),
            repo_root=repo_root,
            min_conf=settings.attr_family_conf,
        )

    for path in images:
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"skip unreadable image: {path.name}")
            continue
        detections = detector.predict(frame)
        tracked: list[TrackedDetection] = []
        visual_labels: dict[int, tuple[str, float]] = {}
        for track_id, det in enumerate(detections, start=1):
            tracked.append(
                TrackedDetection(
                    class_name=det.class_name,
                    confidence=det.confidence,
                    bbox=det.bbox,
                    track_id=track_id,
                )
            )
            prediction = (
                classifier.predict_crop(crop_box(frame, det.bbox))
                if classifier is not None
                else None
            )
            if prediction is not None:
                visual_labels[track_id] = prediction
        rendered = annotate(frame, tracked, visual_labels=visual_labels or None)
        prefix = "showcase-drone-" if args.detection_only else "visual-family-"
        output = output_dir / f"{prefix}{path.stem}.jpg"
        if not cv2.imwrite(str(output), rendered):
            raise OSError(f"could not write showcase image: {output}")
        print(
            f"{path.name}: {len(detections)} detection(s), "
            f"{len(visual_labels)} visual family prediction(s) -> {output}"
        )


if __name__ == "__main__":
    main()
