"""Held-out REAL evaluation: MMAUD official test segment (temporal, per-bag).

Two evaluations on test (never trained on, 30-frame boundary margin applied):
  1. classifier-only: GT crops -> candidate + family.pt (mapped) predictions.
  2. end-to-end: YOLO drone.pt boxes on full frames matched to GT (IoU>=0.3);
     unmatched GT = detector miss (counted separately, never hidden).

family.pt mapping (its taxonomy predates MMAUD): mavic2/mavic3->Mavic,
phantom4->Phantom, avata/m300->unsupported (correct answer = Unknown).
Candidate taxonomy: mavic2/mavic3/phantom4/avata/m300 + Unknown below threshold.

Threshold sweep is calibrated on the VAL segment, applied to TEST.
Writes data/training/mmaud-eval.json. Reads only; family.pt untouched.

Usage (from detector/):  uv run python tools\\mmaud_eval.py
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
from PIL import Image as PILImage

REPO = Path(__file__).resolve().parents[2]
CROPS = REPO / "data" / "training" / "mmaud-crops"
SRC = REPO / "data" / "training" / "mmaud-2d" / "extracted" / "MMAUD_2D"
CANDIDATE = REPO / "data" / "training" / "mmaud-family-candidate.pt"
BASELINE = REPO / "detector" / "models" / "family.pt"
CLASSES = ("mavic2", "mavic3", "phantom4", "avata", "m300")
BASELINE_MAP = {"mavic2": "Mavic", "mavic3": "Mavic", "phantom4": "Phantom"}
FAMILY_MAP = {
    "mavic2": "Mavic",
    "mavic3": "Mavic",
    "phantom4": "Phantom",
    "avata": "Avata",
    "m300": "M300",
}
FAMILY_CLASSES = ("Mavic", "Phantom", "Avata", "M300")
SHARED_FAMILIES = ("Mavic", "Phantom")
THRESHOLDS = (0.3, 0.5, 0.6, 0.75, 0.9)
IOU_MATCH = 0.3
UNKNOWN = "Unknown"


def normalize_baseline(label: str) -> str:
    key = " ".join(label.casefold().replace("_", " ").replace("-", " ").split())
    return {
        "dji mavic": "Mavic",
        "mavic": "Mavic",
        "dji phantom": "Phantom",
        "phantom": "Phantom",
        "dji inspire": "Inspire",
        "inspire": "Inspire",
        "no drone": "No Drone",
    }.get(key, label.strip())


def load_manifest(split: str) -> list[dict[str, str]]:
    with (CROPS / "manifest.csv").open() as fh:
        return [r for r in csv.DictReader(fh) if r["split"] == split]


def batch_predict(weights: Path, paths: list[str]) -> list[tuple[str, float]]:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    names = getattr(model, "names", {})
    out: list[tuple[str, float]] = []
    for i in range(0, len(paths), 32):
        for result in model.predict(source=paths[i : i + 32], verbose=False):
            probs = getattr(result, "probs", None)
            if probs is None:
                out.append(("", 0.0))
                continue
            out.append((str(names.get(int(probs.top1), "")), float(probs.top1conf)))
    return out


def with_unknown(
    label: str,
    conf: float,
    norm: Callable[[str], str],
    threshold: float,
) -> str:
    if conf < threshold:
        return UNKNOWN
    return norm(label)


def map_to_families(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(FAMILY_MAP[truth], FAMILY_MAP.get(pred, pred)) for truth, pred in rows]


def summarize(rows: list[tuple[str, str]], classes: tuple[str, ...]) -> dict[str, Any]:
    n = len(rows)
    per: dict[str, dict] = {}
    for cls in classes:
        tp = sum(1 for t, p in rows if t == cls and p == cls)
        fp = sum(1 for t, p in rows if t != cls and p == cls)
        fn = sum(1 for t, p in rows if t == cls and p != cls)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[cls] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": sum(1 for t, _ in rows if t == cls),
        }
    macro_f1 = round(sum(v["f1"] for v in per.values()) / len(per), 4)
    labels = list(classes) + [UNKNOWN]
    confusion = {
        t: {p: sum(1 for tt, pp in rows if tt == t and pp == p) for p in labels} for t in classes
    }
    unk = sum(1 for _, p in rows if p == UNKNOWN)
    kept = [(t, p) for t, p in rows if p != UNKNOWN]
    return {
        "n": n,
        "accuracy": round(sum(1 for t, p in rows if t == p) / n, 4) if n else 0.0,
        "macro_f1": macro_f1,
        "per_class": per,
        "confusion": confusion,
        "unknown_rate": round(unk / n, 4) if n else 0.0,
        "kept_accuracy": round(sum(1 for t, p in kept if t == p) / len(kept), 4) if kept else 0.0,
    }


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def gt_box(row: dict[str, str]) -> tuple[tuple[float, float, float, float], Path, str]:
    bag, frame = row["bag"], int(row["frame"])
    lab = SRC / "test" / "labels" / f"{bag}_{frame}.txt"
    parts = lab.read_text().split()
    img = SRC / "test" / "images" / f"{bag}_{frame}.png"
    with PILImage.open(img) as im:
        w, h = im.size
    _, xc, yc, bw, bh = parts[:5]
    xc, yc, bw, bh = float(xc) * w, float(yc) * h, float(bw) * w, float(bh) * h
    return (xc - bw / 2, yc - bh / 2, xc + bw / 2, yc + bh / 2), img, row["family"]


def main() -> None:
    from detector.attributes import crop_box
    from detector.detect import Detector
    from detector.sources import find_repo_root

    repo_root = find_repo_root(Path("tools/render_family_showcase.py").resolve())
    if not (repo_root / "detector").is_dir():
        repo_root = REPO
    val_rows = load_manifest("val")
    test_rows = load_manifest("test")
    print(f"val crops: {len(val_rows)}, test crops: {len(test_rows)}")

    val_paths = [(REPO / r["crop"]).as_posix() for r in val_rows]
    test_paths = [(REPO / r["crop"]).as_posix() for r in test_rows]
    cand_val = batch_predict(CANDIDATE, val_paths)
    cand_test = batch_predict(CANDIDATE, test_paths)
    base_test = batch_predict(BASELINE, test_paths)

    # Calibrate threshold on VAL (candidate): kept-accuracy vs unknown trade-off.
    print("threshold sweep on VAL (candidate):")
    for thr in THRESHOLDS:
        rows = [
            (r["family"], with_unknown(l, c, lambda s: s, thr))
            for r, (l, c) in zip(val_rows, cand_val)
        ]
        s = summarize(rows, CLASSES)
        print(
            f"  thr={thr}: acc={s['accuracy']} kept={s['kept_accuracy']} "
            f"unknown={s['unknown_rate']} macroF1={s['macro_f1']}"
        )
    thr = 0.5

    report: dict = {
        "note": "REAL held-out MMAUD V1 test segment (temporal split, 30-frame margins).",
        "threshold": thr,
        "classes": list(CLASSES),
    }
    cand_rows = [
        (r["family"], with_unknown(lbl, conf, lambda s: s, thr))
        for r, (lbl, conf) in zip(test_rows, cand_test)
    ]
    report["candidate_classifier_only"] = summarize(cand_rows, CLASSES)
    candidate_family_rows = map_to_families(cand_rows)
    report["candidate_family_level"] = summarize(candidate_family_rows, FAMILY_CLASSES)

    base_rows = []
    for r, (lbl, conf) in zip(test_rows, base_test):
        pred = with_unknown(lbl, conf, normalize_baseline, thr)
        expected = BASELINE_MAP.get(r["family"])  # None for avata/m300
        base_rows.append((expected if expected else UNKNOWN, pred))
    # Score: correct if exact match on supported, or Unknown on unsupported.
    n = len(base_rows)
    report["baseline_mapped"] = {
        "n": n,
        "accuracy": round(sum(1 for t, p in base_rows if t == p) / n, 4),
        "unknown_rate": round(sum(1 for _, p in base_rows if p == UNKNOWN) / n, 4),
        "note": "Not a like-for-like all-class score: Avata and M300 are unsupported by family.pt and counted as Unknown targets.",
        "confusion_true_mmaud_vs_pred_baseline": {
            t: {
                p: sum(
                    1
                    for tt, pp in [
                        (r["family"], with_unknown(l, c, normalize_baseline, thr))
                        for r, (l, c) in zip(test_rows, base_test)
                    ]
                    if tt == t and pp == p
                )
                for p in ("Mavic", "Phantom", "Inspire", "No Drone", UNKNOWN)
            }
            for t in CLASSES
        },
    }

    # The existing classifier has only Mavic and Phantom among these labels.
    shared_indices = [
        index for index, row in enumerate(test_rows) if FAMILY_MAP[row["family"]] in SHARED_FAMILIES
    ]
    candidate_shared_correct = 0
    baseline_shared_correct = 0
    for index in shared_indices:
        expected = FAMILY_MAP[test_rows[index]["family"]]
        candidate_label, candidate_conf = cand_test[index]
        candidate_family = FAMILY_MAP.get(candidate_label, candidate_label)
        if candidate_conf < thr:
            candidate_family = UNKNOWN
        baseline_label, baseline_conf = base_test[index]
        baseline_family = normalize_baseline(baseline_label)
        if baseline_conf < thr:
            baseline_family = UNKNOWN
        candidate_shared_correct += candidate_family == expected
        baseline_shared_correct += baseline_family == expected
    shared_count = len(shared_indices)
    report["shared_family_comparison"] = {
        "families": list(SHARED_FAMILIES),
        "n": shared_count,
        "threshold": thr,
        "candidate_accuracy": round(candidate_shared_correct / shared_count, 4)
        if shared_count
        else 0.0,
        "baseline_accuracy": round(baseline_shared_correct / shared_count, 4)
        if shared_count
        else 0.0,
        "note": "Like-for-like family labels only; Avata and M300 are excluded because family.pt cannot represent them.",
    }

    # End-to-end: YOLO drone.pt on test frames, IoU match, classify matches.
    detector = Detector(
        weights=Path("models/drone.pt"),
        conf=0.35,
        imgsz=640,
        target_classes={"drone"},
        repo_root=repo_root,
    )
    from detector.attributes import ModelFamilyClassifier

    candidate = ModelFamilyClassifier(weights=CANDIDATE, repo_root=REPO, min_conf=0.0)
    e2e_rows: list[tuple[str, str]] = []
    e2e_all_rows: list[tuple[str, str]] = []
    misses = 0
    for r in test_rows:
        box, img_path, family = gt_box(r)
        frame = cv2.imread(str(img_path))
        dets = detector.predict(frame)
        best = max((iou(d.bbox, box), d) for d in dets) if dets else (0.0, None)
        if best[0] < IOU_MATCH or best[1] is None:
            misses += 1
            e2e_all_rows.append((family, UNKNOWN))
            continue
        res = candidate.predict_crop(crop_box(frame, best[1].bbox))
        pred = res[0] if res and res[1] >= thr else UNKNOWN
        e2e_rows.append((family, pred))
        e2e_all_rows.append((family, pred))
    e2e_family_rows = map_to_families(e2e_all_rows)
    report["end_to_end"] = {
        "matched_only": summarize(e2e_rows, CLASSES),
        "all_ground_truth": summarize(e2e_all_rows, CLASSES),
        "family_level_all_ground_truth": summarize(e2e_family_rows, FAMILY_CLASSES),
        "detector_misses": misses,
        "gt_total": len(test_rows),
        "miss_rate": round(misses / len(test_rows), 4),
        "correct_family_predictions_all_ground_truth": sum(
            truth == pred for truth, pred in e2e_family_rows
        ),
    }
    print("classifier-only candidate:", report["candidate_classifier_only"])
    print(
        "baseline mapped:",
        {
            k: v
            for k, v in report["baseline_mapped"].items()
            if k != "confusion_true_mmaud_vs_pred_baseline"
        },
    )
    print("shared-family comparison:", report["shared_family_comparison"])
    print("end-to-end matched:", report["end_to_end"]["matched_only"])
    print("end-to-end all GT:", report["end_to_end"]["all_ground_truth"])
    dest = REPO / "data" / "training" / "mmaud-eval.json"
    dest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
