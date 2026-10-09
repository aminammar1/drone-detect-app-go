"""Env/.env config. Variable names per DESCRIPTION.md section 8."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All detector settings; nothing else hard-codes paths or URLs."""

    model_config = SettingsConfigDict(
        # Runnable from detector/ or repo root.
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    ws_url: str = Field(default="ws://localhost:8080/ws/detector")
    ws_queue_size: int = Field(default=100, gt=0)
    # Shared secret for the server's X-Detector-Token check (DESCRIPTION.md
    # section 9). Empty disables the check; must match the server's
    # DETECTOR_TOKEN or the handshake is rejected with HTTP 403.
    detector_token: str = Field(default="")
    yolo_weights: str = Field(default="./detector/models/drone.pt")
    yolo_target_classes: str = Field(default="drone")
    yolo_conf: float = Field(default=0.35, ge=0.0, le=1.0)
    yolo_imgsz: int = Field(default=640, gt=0)
    zone_id: str = Field(default="north-gate")
    source_id: str = Field(default="cam-01")
    track_cooldown_seconds: float = Field(default=30.0, ge=0.0)
    # File sources emit one summary per confirmed track at end of footage.
    track_min_frames: int = Field(default=3, ge=1)
    # Inference stride for video: run YOLO every Nth frame (1 = every frame).
    yolo_stride: int = Field(default=1, ge=1)
    snapshot_dir: Path = Field(default=Path("./data/snapshots"))
    videos_dir: Path = Field(default=Path("./videos"))
    images_dir: Path = Field(default=Path("./images"))
    detector_clock: str = Field(default="video", pattern="^(video|wall)$")
    scenario_start: str = Field(default="2026-06-09T14:00:00Z")
    # Crop classifier for visual.model_family; off until family.pt is trained.
    attr_family_enabled: bool = Field(default=False)
    attr_family_weights: str = Field(default="./detector/models/family.pt")
    attr_family_conf: float = Field(default=0.75, ge=0.0, le=1.0)


def get_settings() -> Settings:
    """Build from env/.env. Never called at import time."""
    return Settings()
