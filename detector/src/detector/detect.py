"""Ultralytics YOLO wrapper (FR-D2).

Latest model family is YOLO26 (e.g. `yolo26n.pt`); weights come from
YOLO_WEIGHTS. COCO-pretrained weights have no `drone` class, so until the
fine-tuned drone model (M8) exists, YOLO_TARGET_CLASSES may name stand-ins
(e.g. `airplane`); that mode logs a warning on every start.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    """One kept box: model class name, confidence, xyxy pixels."""

    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class TrackedDetection(Detection):
    """A detection with the tracker's stable id (`None` before association)."""

    track_id: int | None


#: Built-in tracker (ships with ultralytics, no extra config needed).
TRACKER_CONFIG = "bytetrack.yaml"

#: Airframe types the server understands (DESCRIPTION.md section 2, `drones`
#: collection). Stage B (PROJECT.md 5.4): when the YOLO model is trained with
#: airframe classes, the predicted class maps to `visual.airframe_type`.
#: Generic labels (`drone`, `airplane`, ...) carry no airframe info and
#: produce no `visual` (stage A behavior).
AIRFRAME_TYPES = frozenset(
    {"quadcopter", "hexacopter", "octocopter", "fixed_wing", "vtol", "helicopter"}
)

#: Detector-side aliases normalized to AIRFRAME_TYPES. `multirotor_heavy` is
#: a training-time grouping (PROJECT.md 5.4 example) with no DB counterpart,
#: so it maps to None (no visual) rather than a wrong exact match.
AIRFRAME_ALIASES: dict[str, str | None] = {
    "quadcopter": "quadcopter",
    "quad": "quadcopter",
    "hexacopter": "hexacopter",
    "hexa": "hexacopter",
    "octocopter": "octocopter",
    "octo": "octocopter",
    "fixed_wing": "fixed_wing",
    "fixed-wing": "fixed_wing",
    "fixedwing": "fixed_wing",
    "fixed wing": "fixed_wing",
    "vtol": "vtol",
    "helicopter": "helicopter",
    "heli": "helicopter",
    "multirotor_heavy": None,
    "drone": None,
    "airplane": None,
    "bird": None,
}


def airframe_from_class(class_name: str) -> str | None:
    """Map a YOLO class name to `visual.airframe_type` (Stage B).

    Normalizes case/separators, then looks up AIRFRAME_ALIASES. Returns None
    when the class carries no airframe info (generic `drone`, stand-ins,
    or groupings like `multirotor_heavy`). The server treats a missing
    `visual` as "skip the cross-check" (DESCRIPTION.md section 4).
    """
    key = class_name.strip().lower().replace("-", "_").replace(" ", "_")
    key = "_".join(part for part in key.split("_") if part)
    if key in AIRFRAME_TYPES:
        return key
    return AIRFRAME_ALIASES.get(key)


def parse_target_classes(raw: str) -> set[str]:
    """Split YOLO_TARGET_CLASSES ("airplane, bird") into a name set."""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


class Detector:
    """Loads YOLO once, filters predictions to the configured target classes."""

    def __init__(
        self,
        weights: Path,
        conf: float,
        imgsz: int,
        target_classes: set[str],
        repo_root: Path,
    ) -> None:
        if not target_classes:
            raise ValueError("YOLO_TARGET_CLASSES is empty; set e.g. 'drone'.")
        if target_classes != {"drone"}:
            names = ", ".join(sorted(target_classes))
            logger.warning(
                "target classes are stand-ins (%s), not 'drone': fine-tuned "
                "drone weights are not trained yet (see M8). Detections are "
                "proxies, not real drone detections.",
                names,
            )
        from ultralytics import YOLO  # lazy: keeps imports light for CLI/tests

        resolved = self._resolve_weights(weights, repo_root)
        logger.info("loading YOLO weights from %s", resolved)
        self._model = YOLO(str(resolved))
        self._conf = conf
        self._imgsz = imgsz
        self._targets = target_classes
        names = getattr(self._model, "names", {})
        self._names: dict[int, str] = {int(k): str(v).lower() for k, v in dict(names).items()}

    @staticmethod
    def _resolve_weights(weights: Path, repo_root: Path) -> Path:
        """Accept an existing file or a pretrained model name (auto-download)."""
        if weights.is_file():
            return weights
        under_root = repo_root / weights
        if under_root.is_file():
            return under_root
        if weights.parent == Path("."):
            # Bare name like `yolo26n.pt`: Ultralytics downloads it on first use.
            return weights
        raise FileNotFoundError(
            f"YOLO weights not found: {weights}. Set YOLO_WEIGHTS to a model "
            "file or a pretrained name such as 'yolo26n.pt' (downloaded "
            "automatically), or train the fine-tuned drone model (M8)."
        )

    def predict(self, frame_bgr: np.ndarray) -> list[Detection]:
        """Run inference on one BGR frame; return kept detections only."""
        results = self._model.predict(frame_bgr, conf=self._conf, imgsz=self._imgsz, verbose=False)
        kept: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for cls_id, conf, xyxy in zip(
                boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxy.tolist()
            ):
                det = self._kept(cls_id, conf, xyxy)
                if det is not None:
                    kept.append(det)
        return kept

    def track(self, frame_bgr: np.ndarray) -> list[TrackedDetection]:
        """Track across frames (`persist=True`); ids are stable per run only."""
        results = self._model.track(
            frame_bgr,
            persist=True,
            tracker=TRACKER_CONFIG,
            conf=self._conf,
            imgsz=self._imgsz,
            verbose=False,
        )
        tracked: list[TrackedDetection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            ids = boxes.id.tolist() if boxes.id is not None else [None] * len(boxes)
            for cls_id, conf, xyxy, track_id in zip(
                boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxy.tolist(), ids
            ):
                det = self._kept(cls_id, conf, xyxy)
                if det is None:
                    continue
                tracked.append(
                    TrackedDetection(
                        class_name=det.class_name,
                        confidence=det.confidence,
                        bbox=det.bbox,
                        track_id=int(track_id) if track_id is not None else None,
                    )
                )
        return tracked

    def reset_tracker(self) -> None:
        """Drop tracker state between video files (ids restart per source)."""
        predictor = getattr(self._model, "predictor", None)
        trackers = getattr(predictor, "trackers", None)
        if trackers:
            trackers.clear()
            logger.debug("tracker state reset")

    def _kept(self, cls_id: float, conf: float, xyxy: list[float]) -> Detection | None:
        """Build a Detection when the class is a configured target, else None."""
        name = self._names.get(int(cls_id), str(int(cls_id)))
        if name not in self._targets:
            return None
        x1, y1, x2, y2 = (float(v) for v in xyxy)
        return Detection(class_name=name, confidence=float(conf), bbox=(x1, y1, x2, y2))


def annotate(frame_bgr: np.ndarray, detections: list[Detection]) -> np.ndarray:
    """Draw boxes + labels; returns a new image, input untouched."""
    annotated = frame_bgr.copy()
    for det in detections:
        x1, y1, x2, y2 = (int(v) for v in det.bbox)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{det.class_name} {det.confidence:.2f}"
        track_id = getattr(det, "track_id", None)
        if track_id is not None:
            label += f" id={track_id}"
        cv2.putText(
            annotated,
            label,
            (x1, max(0, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    return annotated
