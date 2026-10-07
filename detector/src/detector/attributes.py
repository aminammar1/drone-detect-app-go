"""Crop classifier for visual.model_family (DESCRIPTION.md section 4).

Family disambiguates beacons or flags spoofing, never identity. Gated by
ATTR_FAMILY_ENABLED; needs detector/models/family.pt (docs/TRAINING.md).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)


class ClsModel(Protocol):
    """YOLO-cls surface; faked in tests."""

    names: dict[int, str]

    def predict(self, crop: np.ndarray, verbose: bool = False): ...


class ModelFamilyClassifier:
    """YOLO-cls family model; load once, call per emitted crop."""

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
        from ultralytics import YOLO  # lazy: no cost when disabled

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
        """(family, conf) or None; None means omit model_family, keep airframe."""
        if crop_bgr is None or crop_bgr.size == 0:
            return None
        h, w = crop_bgr.shape[:2]
        if h < 8 or w < 8:
            return None
        try:
            results = self._model.predict(crop_bgr, verbose=False)
        except Exception as exc:  # noqa: BLE001 — best effort, never fail emit
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
    """Clamped crop; empty array when invalid."""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    return frame_bgr[y1:y2, x1:x2].copy()
