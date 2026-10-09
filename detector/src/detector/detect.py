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

    @property
    def model_names(self) -> set[str]:
        """Lowercased class names the loaded weights actually predict."""
        return set(self._names.values())

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
            # Ultralytics skips tracker initialization for persist=True when the
            # list already exists, so clearing it makes the next video fail.
            for tracker in trackers:
                tracker.reset()
            logger.debug("tracker state reset")

    def _kept(self, cls_id: float, conf: float, xyxy: list[float]) -> Detection | None:
        name = self._names.get(int(cls_id), str(int(cls_id)))
        if name not in self._targets:
            return None
        x1, y1, x2, y2 = (float(v) for v in xyxy)
        # Stand-in weights (e.g. COCO airplane) are drone proxies: the box
        # and the wire event must say "drone", never "airplane". After
        # training, targets == {"drone"} and this is a no-op.
        label = "drone" if self._targets != {"drone"} else name
        return Detection(class_name=label, confidence=float(conf), bbox=(x1, y1, x2, y2))


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


def annotate(
    frame_bgr: np.ndarray,
    detections: list[Detection],
    labels: dict[int, str] | None = None,
    visual_labels: dict[int, tuple[str, float]] | None = None,
) -> np.ndarray:
    """Annotate a copy; input untouched.

    `labels` maps track_id to a registered model from the server. `visual_labels`
    maps it to a classifier prediction; the word "visual" keeps that prediction
    distinct from a registered identity.
    """
    annotated = frame_bgr.copy()
    occupied: list[tuple[int, int, int, int]] = []
    font = cv2.FONT_HERSHEY_DUPLEX
    height, width = annotated.shape[:2]
    scale = min(1.0, max(0.72, min(width, height) / 720))
    font_scale = 0.48 * scale
    thickness = max(1, round(scale))
    pad_x = round(10 * scale)
    pad_y = round(7 * scale)
    line_gap = round(5 * scale)

    for det in detections:
        x1, y1, x2, y2 = (int(v) for v in det.bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(width - 1, x2), min(height - 1, y2)
        track_id = getattr(det, "track_id", None)
        color = track_color(track_id if isinstance(track_id, int) else None)
        box_thickness = max(1, round(min(width, height) / 520))
        cv2.rectangle(
            annotated,
            (x1, y1),
            (x2, y2),
            color,
            box_thickness,
            cv2.LINE_AA,
        )
        corner = max(8, min(20, round(min(x2 - x1, y2 - y1) * 0.18)))
        for start, end in (
            ((x1, y1), (x1 + corner, y1)),
            ((x1, y1), (x1, y1 + corner)),
            ((x2, y1), (x2 - corner, y1)),
            ((x2, y1), (x2, y1 + corner)),
            ((x1, y2), (x1 + corner, y2)),
            ((x1, y2), (x1, y2 - corner)),
            ((x2, y2), (x2 - corner, y2)),
            ((x2, y2), (x2, y2 - corner)),
        ):
            cv2.line(annotated, start, end, color, box_thickness + 1, cv2.LINE_AA)

        identified = labels.get(track_id) if labels and isinstance(track_id, int) else None
        visual = (
            visual_labels.get(track_id) if visual_labels and isinstance(track_id, int) else None
        )
        track_label = f"track #{track_id}" if isinstance(track_id, int) else "drone"
        lines = [f"drone  ·  {det.confidence:.2f}  ·  {track_label}"]
        if identified:
            lines.append(f"registered  ·  {identified}")
        if visual:
            family = visual[0]
            family_key = family.casefold().replace("_", " ")
            if family_key == "no drone":
                visual_name = "no family match"
            else:
                prefix = "" if family.casefold().startswith("dji ") else "DJI "
                visual_name = f"{prefix}{family}"
            lines.append(f"visual guess  ·  {visual_name}  {visual[1]:.2f}")
        elif not identified:
            lines.append("visual family  ·  pending")

        max_text_width = max(40, width - 2 * pad_x - 8)
        while font_scale > 0.28:
            measured = [cv2.getTextSize(line, font, font_scale, thickness)[0][0] for line in lines]
            if max(measured) <= max_text_width:
                break
            font_scale -= 0.025
        if max(measured) > max_text_width:
            shortened: list[str] = []
            for line in lines:
                while (
                    line
                    and cv2.getTextSize(line + "…", font, font_scale, thickness)[0][0]
                    > max_text_width
                ):
                    line = line[:-1]
                shortened.append((line + "…") if line else "…")
            lines = shortened
            measured = [cv2.getTextSize(line, font, font_scale, thickness)[0][0] for line in lines]

        line_height = cv2.getTextSize("Ag", font, font_scale, thickness)[0][1]
        baseline = cv2.getTextSize("Ag", font, font_scale, thickness)[1]
        panel_width = max(measured) + 2 * pad_x + 4
        panel_height = len(lines) * (line_height + line_gap) - line_gap + 2 * pad_y + baseline
        panel_width = min(width, panel_width)
        max_x = max(0, width - panel_width)
        max_y = max(0, height - panel_height)
        candidates = [
            (x1, y1 - panel_height - 4),
            (x1, y2 + 4),
            (x2 - panel_width, y1 - panel_height - 4),
            (x2 - panel_width, y2 + 4),
            (x1, y1),
        ]
        candidates = [(min(max(0, x), max_x), min(max(0, y), max_y)) for x, y in candidates]

        def overlap_area(
            pos: tuple[int, int],
            panel_width: int = panel_width,
            panel_height: int = panel_height,
        ) -> int:
            px, py = pos
            rect = (px, py, px + panel_width, py + panel_height)
            return sum(
                max(0, min(rect[2], other[2]) - max(rect[0], other[0]))
                * max(0, min(rect[3], other[3]) - max(rect[1], other[1]))
                for other in occupied
            )

        panel_x, panel_y = min(candidates, key=overlap_area)
        occupied.append((panel_x, panel_y, panel_x + panel_width, panel_y + panel_height))
        panel = annotated.copy()
        cv2.rectangle(
            panel,
            (panel_x, panel_y),
            (panel_x + panel_width, panel_y + panel_height),
            (18, 27, 40),
            -1,
        )
        cv2.addWeighted(panel, 0.92, annotated, 0.08, 0, annotated)
        cv2.rectangle(
            annotated,
            (panel_x, panel_y),
            (panel_x + panel_width, panel_y + panel_height),
            color,
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(
            annotated,
            (panel_x, panel_y),
            (panel_x + max(3, round(4 * scale)), panel_y + panel_height),
            color,
            -1,
        )
        text_y = panel_y + pad_y + line_height
        for index, line in enumerate(lines):
            text_color = (232, 240, 247) if index < len(lines) - 1 else (150, 230, 255)
            if visual and line.startswith("visual guess"):
                text_color = (120, 235, 255)
            cv2.putText(
                annotated,
                line,
                (panel_x + pad_x + 2, text_y),
                font,
                font_scale,
                text_color,
                thickness,
                cv2.LINE_AA,
            )
            text_y += line_height + line_gap
    return annotated
