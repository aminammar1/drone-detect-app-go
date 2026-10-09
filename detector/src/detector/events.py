"""Detector -> server detection message. Field-for-field per DESCRIPTION.md section 3.1."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceKind = Literal["image", "video"]
IdentifierKind = Literal["serial", "remote_id", "qr", "none"]


class BBox(BaseModel):
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
    """Absent means {"kind": "none"} (FR-D9)."""

    model_config = ConfigDict(extra="forbid")

    kind: IdentifierKind = "none"
    value: str = ""


class Visual(BaseModel):
    """Soft evidence (FR-D8); attached only when a classifier exists."""

    model_config = ConfigDict(extra="forbid")

    airframe_type: str | None = Field(default=None, min_length=1)
    airframe_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    model_family: str | None = None
    model_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DetectionEvent(BaseModel):
    """One detection frame on the detector socket (DESCRIPTION.md 3.1)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["detection"] = "detection"
    event_id: UUID
    detected_at: datetime
    source: EventSource
    zone_id: str = Field(min_length=1)
    track_id: int = Field(ge=0)
    # class is reserved; wire name stays "class" via alias.
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
        # Naive times break server event-time matching.
        if value.tzinfo is None:
            raise ValueError("detected_at must be timezone-aware (RFC 3339 UTC)")
        return value

    def to_json(self) -> str:
        """Aliases applied, nulls dropped (visual omitted when None)."""
        return self.model_dump_json(by_alias=True, exclude_none=True)
