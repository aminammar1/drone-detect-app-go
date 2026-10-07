"""Evaluate detector weights on `images/` and `videos/` (M8).

Reports detections per image and false positives per minute on video. On a
drone-free video every box is a false positive, so FP/min measures how noisy
the weights are before fine-tuning (DESCRIPTION.md section 10).

Run from `detector/`::

    .\\.venv\\Scripts\\python.exe tools\\evaluate.py --source ..\\videos --weights yolo26n.pt
    .\\.venv\\Scripts\\python.exe tools\\evaluate.py --source ..\\images --target-classes drone

Inputs are read-only; nothing is written to `images/` or `videos/`.
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

import typer

# Allow `python tools/evaluate.py` from detector/ without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2

from detector.detect import Detector, parse_target_classes
from detector.sources import SourceError, find_repo_root, resolve_media_sources

logger = logging.getLogger("evaluate")
app = typer.Typer(help="Evaluate YOLO weights on images/ and videos/.")


def fp_per_minute(total_boxes: int, duration_s: float) -> float:
    """False positives per minute. Zero duration yields 0.0 (no crash)."""
    if duration_s <= 0:
        return 0.0
    return total_boxes / (duration_s / 60.0)


def scaled_total(counted: int, stride: int) -> int:
    """Extrapolate a strided sample to the full frame count."""
    if stride <= 1:
        return counted
    return counted * stride


@app.command()
def main(
    source: str = typer.Option(
        "../videos",
        "--source",
        help="Image/video file or folder (relative to repo root ok).",
    ),
    weights: str = typer.Option("yolo26n.pt", "--weights", help="YOLO weights file or name."),
    target_classes: str = typer.Option(
        "drone", "--target-classes", help="Comma-separated YOLO classes to count."
    ),
    conf: float = typer.Option(0.35, "--conf", min=0.0, max=1.0),
    imgsz: int = typer.Option(640, "--imgsz", min=32),
    stride: int = typer.Option(1, "--stride", min=1, help="Score every Nth video frame."),
    max_frames: int = typer.Option(
        0, "--max-frames", min=0, help="Cap frames per video (0 = all)."
    ),
) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    repo_root = find_repo_root(Path(__file__).resolve())
    try:
        media = resolve_media_sources(source, repo_root / "images", repo_root / "videos", repo_root)
    except SourceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2)
    if stride < 1:
        typer.echo("error: --stride must be >= 1.", err=True)
        raise typer.Exit(code=2)

    try:
        detector = Detector(
            weights=Path(weights),
            conf=conf,
            imgsz=imgsz,
            target_classes=parse_target_classes(target_classes),
            repo_root=repo_root,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2)

    typer.echo(
        f"source: {source} ({len(media)} item(s)) weights={weights} classes={target_classes}"
    )
    for item in media:
        if item.kind == "image":
            _eval_image(detector, item)
        else:
            _eval_video(detector, item, stride, max_frames)


def _eval_image(detector: Detector, item) -> None:
    frame = cv2.imread(str(item.path) if item.path else str(item.ref))
    if frame is None:
        logger.warning("skipping unreadable image: %s", item.uri)
        return
    dets = detector.predict(frame)
    typer.echo(f"{item.uri}: {len(dets)} box(es)")
    for det in dets:
        typer.echo(f"  - {det.class_name} conf={det.confidence:.2f} bbox={det.bbox}")


def _eval_video(detector: Detector, item, stride: int, max_frames: int) -> None:
    cap = cv2.VideoCapture(item.ref)
    if not cap.isOpened():
        logger.warning("could not open video: %s", item.uri)
        return
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or math.isnan(fps):
        fps = 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_s = (total_frames / fps) if total_frames > 0 else 0.0

    counted = 0
    scored = 0
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % stride == 0:
            scored += 1
            counted += len(detector.predict(frame))
        idx += 1
        if max_frames > 0 and idx >= max_frames:
            break
    cap.release()

    if max_frames > 0 and total_frames > max_frames:
        duration_s = min(duration_s, max_frames / fps) if duration_s else max_frames / fps
    estimate = scaled_total(counted, stride)
    rate = fp_per_minute(estimate, duration_s)
    typer.echo(
        f"{item.uri}: {counted} box(es) on {scored}/{idx} scored/read frames, "
        f"fps={fps:.1f} duration={duration_s:.1f}s stride={stride} "
        f"estimated_total={estimate} FP/min={rate:.2f} (drone-free video: all boxes are FP)"
    )


if __name__ == "__main__":
    app()
