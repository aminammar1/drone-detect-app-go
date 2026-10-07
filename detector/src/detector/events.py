"""Pydantic models for the detector -> server `detection` message.

Field-for-field match with DESCRIPTION.md section 3.1. `visual` is omitted
entirely in M3 (stage A in PROJECT.md 5.4: no attribute model yet); it becomes
available when the airframe/model classifier lands.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceKind = Literal["image", "video"]
IdentifierKind = Literal["serial", "remote_id", "qr", "none"]


class BBox(BaseModel):
    """Pixel box, top-left (x1, y1) to bottom-right (x2, y2)."""

    model_config = ConfigDict(extra="forbid")

    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    x2: float = Field(ge=0)
    y2: float = Field(ge=0)


class EventSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: SourceKind
    uri: str = Field(min_length=1)


class Identifier(BaseModel):
    """Explicit identity. Absent identifier == {"kind": "none"} (FR-D9)."""

    model_config = ConfigDict(extra="forbid")

    kind: IdentifierKind = "none"
    value: str = ""


class Visual(BaseModel):
    """Soft visual evidence (FR-D8). Only attached when a classifier exists."""

    model_config = ConfigDict(extra="forbid")

    airframe_type: str = Field(min_length=1)
    airframe_confidence: float = Field(ge=0.0, le=1.0)
    model_family: str | None = None
    model_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DetectionEvent(BaseModel):
    """One `detection` frame on the detector WebSocket (DESCRIPTION 3.1)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["detection"] = "detection"
    event_id: UUID
    detected_at: datetime
    source: EventSource
    zone_id: str = Field(min_length=1)
    track_id: int = Field(ge=0)
    # `class` is reserved in Python; the wire name stays "class" via alias.
    class_name: str = Field(alias="class", min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox
    frame_index: int = Field(ge=0)
    snapshot_path: str = Field(min_length=1)
    visual: Visual | None = None
    identifier: Identifier = Field(default_factory=Identifier)

    @field_validator("detected_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        # Naive timestamps silently shift event-time matching on the server.
        if value.tzinfo is None:
            raise ValueError("detected_at must be timezone-aware (RFC 3339 UTC)")
        return value

    def to_json(self) -> str:
        """Wire encoding: aliases (`class`), no nulls (visual omitted when None)."""
        return self.model_dump_json(by_alias=True, exclude_none=True)
