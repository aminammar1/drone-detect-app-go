"""Stage C crop classifier for `visual.model_family` (PROJECT.md 5.4, optional).

Ultralytics YOLO-cls (e.g. `yolo26n-cls.pt` fine-tuned on cropped drone boxes)
predicts the model family (Mavic, Mini, Anafi, ...). It never identifies a
unique drone: the family only disambiguates beacons or flags spoofing
(DESCRIPTION.md section 4). Disabled by default; enable with
ATTR_FAMILY_ENABLED=true once `detector/models/family.pt` exists.

What labeled crops are needed is documented in `docs/TRAINING.md` (Stage C).
A Hugging Face backbone is only a fallback — see that doc for when it is
justified (YOLO-cls accuracy insufficient on your crops).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)


class ClsModel(Protocol):
    """Minimal YOLO-cls surface used by the classifier (real or fake in tests)."""

    names: dict[int, str]

    def predict(self, crop: np.ndarray, verbose: bool = False): ...


class ModelFamilyClassifier:
    """Wraps a YOLO-cls family model. Load once, call per emitted crop."""

    def __init__(
        self,
        weights: Path,
        repo_root: Path,
        min_conf: float = 0.5,
        _model: ClsModel | None = None,
    ) -> None:
        if not 0.0 <= min_conf <= 1.0:
            raise ValueError("ATTR_FAMILY_CONF must be within [0, 1]")
        if _model is not None:
            self._model = _model
            self._min_conf = min_conf
            return
        resolved = self._resolve(weights, repo_root)
        from ultralytics import YOLO  # lazy: no cost when Stage C is off

        logger.info("loading family classifier weights from %s", resolved)
        self._model = YOLO(str(resolved))
        self._min_conf = min_conf

    @staticmethod
    def _resolve(weights: Path, repo_root: Path) -> Path:
        if weights.is_file():
            return weights
        under_root = repo_root / weights
        if under_root.is_file():
            return under_root
        raise FileNotFoundError(
            f"family classifier weights not found: {weights}. Train one "
            "(docs/TRAINING.md Stage C) or leave ATTR_FAMILY_ENABLED=false."
        )

    def predict_crop(self, crop_bgr: np.ndarray) -> tuple[str, float] | None:
        """Classify one BGR crop. Returns (family, conf) or None.

        None means "no opinion": empty/tiny crop, low confidence, or model
        error. Callers then omit `model_family` but keep the airframe.
        """
        if crop_bgr is None or crop_bgr.size == 0:
            return None
        h, w = crop_bgr.shape[:2]
        if h < 8 or w < 8:
            return None
        try:
            results = self._model.predict(crop_bgr, verbose=False)
        except Exception as exc:  # noqa: BLE001 — best effort, never crash emit
            logger.warning("family classifier failed: %s", exc)
            return None
        best: tuple[str, float] | None = None
        for result in results:
            probs = getattr(result, "probs", None)
            if probs is None:
                continue
            top = int(getattr(probs, "top1", -1))
            conf = float(getattr(probs, "top1conf", 0.0))
            if top < 0:
                continue
            names = getattr(self._model, "names", {})
            family = str(names.get(top, top)).strip()
            if conf >= self._min_conf and family and (best is None or conf > best[1]):
                best = (family, conf)
        return best


def crop_box(frame_bgr: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
    """Crop and clamp a box to the frame. Returns an empty array when invalid."""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    return frame_bgr[y1:y2, x1:x2].copy()
