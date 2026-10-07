"""YOLO wrapper (FR-D2). Weights come from YOLO_WEIGHTS.

COCO weights have no drone class; stand-ins via YOLO_TARGET_CLASSES log a
warning at startup until the fine-tuned drone model exists.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class TrackedDetection(Detection):
    """track_id is None before tracker association."""

    track_id: int | None


#: Built-in tracker; ships with ultralytics.
TRACKER_CONFIG = "bytetrack.yaml"

#: Server DB values (DESCRIPTION.md section 2, drones). Generic labels carry
#: no airframe and produce no visual; the server then skips the cross-check
#: (DESCRIPTION.md section 4).
AIRFRAME_TYPES = frozenset(
    {"quadcopter", "hexacopter", "octocopter", "fixed_wing", "vtol", "helicopter"}
)

#: Normalized aliases. Groupings without a DB value map to None, never a wrong match.
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
    """Map YOLO class to visual.airframe_type; None means omit visual (DESCRIPTION.md section 4)."""
    key = class_name.strip().lower().replace("-", "_").replace(" ", "_")
    key = "_".join(part for part in key.split("_") if part)
    if key in AIRFRAME_TYPES:
        return key
    return AIRFRAME_ALIASES.get(key)


def parse_target_classes(raw: str) -> set[str]:
    """Parse YOLO_TARGET_CLASSES."""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


class Detector:
    """Loads YOLO once, keeps only configured target classes."""

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
                "drone weights are not trained yet (see docs/TRAINING.md). Detections are "
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

    @property
    def imgsz(self) -> int:
        """Inference image size, for latency logs."""
        return self._imgsz

    @staticmethod
    def _resolve_weights(weights: Path, repo_root: Path) -> Path:
        """Existing file or pretrained name (auto-downloaded)."""
        if weights.is_file():
            return weights
        under_root = repo_root / weights
        if under_root.is_file():
            return under_root
        if weights.parent == Path("."):
            # Bare name (yolo26n.pt): downloaded on first use.
            return weights
        raise FileNotFoundError(
            f"YOLO weights not found: {weights}. Set YOLO_WEIGHTS to a model "
            "file or a pretrained name such as 'yolo26n.pt' (downloaded "
            "automatically), or train the fine-tuned drone model (docs/TRAINING.md)."
        )

    def predict(self, frame_bgr: np.ndarray) -> list[Detection]:
        """One BGR frame to kept detections."""
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
        """Ids are per-run only, never identity."""
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
        """Drop state between files; ids restart per source."""
        predictor = getattr(self._model, "predictor", None)
        trackers = getattr(predictor, "trackers", None)
        if trackers:
            trackers.clear()
            logger.debug("tracker state reset")

    def _kept(self, cls_id: float, conf: float, xyxy: list[float]) -> Detection | None:
        name = self._names.get(int(cls_id), str(int(cls_id)))
        if name not in self._targets:
            return None
        x1, y1, x2, y2 = (float(v) for v in xyxy)
        return Detection(class_name=name, confidence=float(conf), bbox=(x1, y1, x2, y2))


def track_color(track_id: int | None) -> tuple[int, int, int]:
    """Per-track display color; stable for the run."""
    if track_id is None:
        return (0, 255, 0)
    palette = (
        (0, 255, 0),  # green
        (255, 0, 0),  # blue
        (0, 0, 255),  # red
        (0, 255, 255),  # yellow
        (255, 0, 255),  # magenta
        (255, 255, 0),  # cyan
        (0, 165, 255),  # orange
        (180, 0, 180),  # purple
        (0, 128, 255),  # orange-red
        (255, 255, 255),  # white
    )
    return palette[int(track_id) % len(palette)]


def annotate(frame_bgr: np.ndarray, detections: list[Detection]) -> np.ndarray:
    """Annotate a copy; input untouched."""
    annotated = frame_bgr.copy()
    for det in detections:
        x1, y1, x2, y2 = (int(v) for v in det.bbox)
        track_id = getattr(det, "track_id", None)
        color = track_color(track_id if isinstance(track_id, int) else None)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"{det.class_name} {det.confidence:.2f}"
        if track_id is not None:
            label += f" id={track_id}"
        cv2.putText(
            annotated,
            label,
            (x1, max(0, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )
    return annotated
