"""Detector configuration loaded from env / .env (pydantic-settings).

Source of truth for variable names: DESCRIPTION.md section 8.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All detector settings. No hard-coded paths or URLs elsewhere in the code."""

    model_config = SettingsConfigDict(
        # Works when the process runs from detector/ (repo .env one level up)
        # or from the repo root.
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    ws_url: str = Field(default="ws://localhost:8080/ws/detector")
    ws_queue_size: int = Field(default=100, gt=0)
    yolo_weights: str = Field(default="./detector/models/drone.pt")
    yolo_target_classes: str = Field(default="drone")
    yolo_conf: float = Field(default=0.35, ge=0.0, le=1.0)
    yolo_imgsz: int = Field(default=640, gt=0)
    zone_id: str = Field(default="north-gate")
    source_id: str = Field(default="cam-01")
    track_cooldown_seconds: float = Field(default=30.0, ge=0.0)
    snapshot_dir: Path = Field(default=Path("./data/snapshots"))
    videos_dir: Path = Field(default=Path("./videos"))
    images_dir: Path = Field(default=Path("./images"))
    detector_clock: str = Field(default="video", pattern="^(video|wall)$")
    scenario_start: str = Field(default="2026-06-09T14:00:00Z")
    # Stage C (optional, M8): crop classifier for visual.model_family.
    # Off by default; enable once detector/models/family.pt is trained.
    attr_family_enabled: bool = Field(default=False)
    attr_family_weights: str = Field(default="./detector/models/family.pt")
    attr_family_conf: float = Field(default=0.5, ge=0.0, le=1.0)


def get_settings() -> Settings:
    """Build settings from environment / .env. Called by the CLI, never at import time."""
    return Settings()
