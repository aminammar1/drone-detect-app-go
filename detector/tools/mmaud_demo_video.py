"""Offline end-to-end demo on a selected MMAUD test bag.

Reads test frames + GT boxes (ignored, local-only), runs YOLO drone.pt,
matches boxes (IoU>=0.3), labels matches with the MMAUD candidate @0.5 and
marks YOLO misses with a dashed GT box, and adds a zoom inset for inspection.
Writes an MP4 plus available outcome stills under data/training/demo/mmaud/.
No server, no preview windows.

Usage (from detector/):  uv run python tools\\mmaud_demo_video.py --bag b5
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import cv2

from detector.attributes import ModelFamilyClassifier, crop_box
from detector.detect import Detector
from detector.sources import find_repo_root

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "data" / "training" / "mmaud-2d" / "extracted" / "MMAUD_2D"
DST = REPO / "data" / "training" / "demo" / "mmaud"
BAG_TO_FAMILY = {
    "b1": "mavic2",
    "b2": "mavic3",
    "b3": "phantom4",
    "b4": "avata",
    "b5": "m300",
}
THR = 0.5
IOU_MATCH = 0.3
DISPLAY = {
    "mavic2": "Mavic 2",
    "mavic3": "Mavic 3",
    "phantom4": "Phantom 4",
    "avata": "Avata",
    "m300": "M300",
}


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def draw_text(frame: Any, x: int, y: int, text: str, color: tuple[int, int, int]) -> None:
    height, width = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness, padding = 0.6, 2, 4
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    label_x = min(max(x, 0), max(0, width - text_width - padding * 2))
    label_y = y - 8 if y > text_height + padding else y + text_height + baseline + padding * 2
    label_y = min(max(label_y, text_height + padding), height - baseline - padding)
    top = label_y - text_height - padding
    cv2.rectangle(
        frame,
        (label_x, top),
        (label_x + text_width + padding * 2, label_y + baseline + padding),
        (0, 0, 0),
        -1,
    )
    cv2.putText(
        frame,
        text,
        (label_x + padding, label_y),
        font,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def add_zoom_inset(
    frame: Any,
    source: Any,
    bbox: tuple[float, float, float, float],
    box_color: tuple[int, int, int],
) -> None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = (int(value) for value in bbox)
    box_width, box_height = max(1, x2 - x1), max(1, y2 - y1)
    padding = max(32, max(box_width, box_height))
    left = max(0, int(x1 - padding))
    top = max(0, int(y1 - padding))
    right = min(width, int(x2 + padding))
    bottom = min(height, int(y2 + padding))
    crop = source[top:bottom, left:right]
    if crop.size == 0:
        return

    inset_width, inset_height = 360, 270
    scale = min(inset_width / crop.shape[1], inset_height / crop.shape[0])
    resized = cv2.resize(
        crop,
        (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))),
        interpolation=cv2.INTER_CUBIC,
    )
    inset_x, inset_y = width - inset_width - 20, height - inset_height - 20
    panel = frame[inset_y : inset_y + inset_height, inset_x : inset_x + inset_width]
    panel[:] = (18, 24, 34)
    offset_x = (inset_width - resized.shape[1]) // 2
    offset_y = (inset_height - resized.shape[0]) // 2
    panel[
        offset_y : offset_y + resized.shape[0],
        offset_x : offset_x + resized.shape[1],
    ] = resized
    scaled_x1 = inset_x + offset_x + int((x1 - left) * scale)
    scaled_y1 = inset_y + offset_y + int((y1 - top) * scale)
    scaled_x2 = inset_x + offset_x + int((x2 - left) * scale)
    scaled_y2 = inset_y + offset_y + int((y2 - top) * scale)
    cv2.rectangle(
        frame,
        (scaled_x1, scaled_y1),
        (scaled_x2, scaled_y2),
        box_color,
        2,
    )
    cv2.rectangle(
        frame,
        (inset_x, inset_y),
        (inset_x + inset_width, inset_y + inset_height),
        (255, 255, 255),
        2,
    )
    cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an MMAUD held-out video demo.")
    parser.add_argument("--bag", choices=tuple(BAG_TO_FAMILY), default="b3")
    bag = parser.parse_args().bag
    expected_family = BAG_TO_FAMILY[bag]
    repo_root = find_repo_root(Path("tools/render_family_showcase.py").resolve())
    if not (repo_root / "detector").is_dir():
        repo_root = REPO
    detector = Detector(
        weights=Path("models/drone.pt"),
        conf=0.35,
        imgsz=640,
        target_classes={"drone"},
        repo_root=repo_root,
    )
    family = ModelFamilyClassifier(
        weights=REPO / "data" / "training" / "mmaud-family-candidate.pt",
        repo_root=REPO,
        min_conf=0.0,
    )
    frames = sorted(
        (SRC / "test" / "images").glob(f"{bag}_*.png"), key=lambda p: int(p.stem.split("_")[1])
    )
    DST.mkdir(parents=True, exist_ok=True)
    writer = None
    saved: dict[str, bool] = {}
    best_correct: tuple[int, Any] | None = None
    for img_path in frames:
        parts = (SRC / "test" / "labels" / f"{img_path.stem}.txt").read_text().split()
        _, xc, yc, bw, bh = parts[:5]
        frame = cv2.imread(str(img_path))
        zoom_source = frame.copy()
        h, w = frame.shape[:2]
        box = (
            (float(xc) - float(bw) / 2) * w,
            (float(yc) - float(bh) / 2) * h,
            (float(xc) + float(bw) / 2) * w,
            (float(yc) + float(bh) / 2) * h,
        )
        if writer is None:
            writer = cv2.VideoWriter(
                str(DST / f"{bag}-endtoend.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h)
            )
        dets = detector.predict(frame)
        best = max(((iou(d.bbox, box), d) for d in dets), default=(0.0, None))
        state = "correct"
        if best[0] >= IOU_MATCH and best[1] is not None:
            focus_box = best[1].bbox
            x1, y1, x2, y2 = (int(v) for v in best[1].bbox)
            res = family.predict_crop(crop_box(frame, best[1].bbox))
            if res and res[1] >= THR:
                label, color = f"{DISPLAY.get(res[0], res[0])} {res[1]:.2f}", (0, 255, 0)
                state = "correct" if res[0] == expected_family else "incorrect"
            else:
                conf = res[1] if res else 0.0
                label, color = f"Unknown {conf:.2f}", (0, 165, 255)
                state = "unknown"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            draw_text(frame, x1, y1, label, color)
        else:
            focus_box = box
            color = (0, 0, 255)
            x1, y1, x2, y2 = (int(v) for v in box)
            for i in range(0, max(x2 - x1, y2 - y1), 12):  # dashed GT = detector miss
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 1)
            draw_text(frame, x1, y1, "missed by detector", (0, 0, 255))
            state = "miss"
        key = state if state != "correct" else "correct"
        add_zoom_inset(frame, zoom_source, focus_box, color)
        if key == "correct":
            x1, y1, x2, y2 = (int(value) for value in focus_box)
            area = max(0, x2 - x1) * max(0, y2 - y1)
            if best_correct is None or area > best_correct[0]:
                best_correct = (area, frame.copy())
        elif key not in saved:
            cv2.imwrite(str(DST / f"{bag}-{key}.jpg"), frame)
            saved[key] = True
        writer.write(frame)
    if writer is not None:
        writer.release()
    if best_correct is not None:
        cv2.imwrite(str(DST / f"{bag}-correct.jpg"), best_correct[1])
        saved["correct"] = True
    print(f"wrote {len(frames)} {bag} frames -> {DST}; stills: {sorted(saved)}")


if __name__ == "__main__":
    main()
