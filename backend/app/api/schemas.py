"""API request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    template_id: str
    persona_id: str | None = None
    target_duration: float | None = Field(default=None, ge=15, le=25)


class SceneOut(BaseModel):
    order: int
    section: str | None
    start_time: float
    end_time: float
    asset_id: str | None
    asset_start_time: float
    overlay_text: str | None
    intent: str | None = None


class RenderOut(BaseModel):
    id: str
    version: int
    plan_version: int
    voice_version: int
    status: str
    output_path: str | None
    qc: dict | None
    error: str | None
    created_at: datetime


class EventOut(BaseModel):
    stage: str
    level: str
    message: str
    created_at: datetime


class ProjectOut(BaseModel):
    id: str
    persona_id: str
    template_id: str
    topic: str
    target_duration: float
    actual_duration: float | None
    status: str
    stage_message: str | None
    error: str | None
    script: str | None
    script_version: int
    voice_version: int
    plan_version: int
    render_version: int
    current_render_id: str | None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    scenes: list[SceneOut] = []
    renders: list[RenderOut] = []
    events: list[EventOut] = []
    video_url: str | None = None
    caption_overrides: dict | None = None
    batch_id: str | None = None
    caption_style: dict | None = None  # effective style (template → global → project), for the UI preview


class AssetPatch(BaseModel):
    persona_id: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    action: str | None = None
    location: str | None = None
    shot: str | None = None
    mood: str | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
    usable_start: float | None = Field(default=None, ge=0)
    usable_end: float | None = Field(default=None, ge=0)
    approved: bool | None = None


class AssetOut(BaseModel):
    id: str
    file: str
    persona_id: str | None = None
    description: str | None
    tags: list
    action: str | None
    location: str | None
    shot: str | None
    mood: str | None
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    orientation: str | None
    usable_start: float
    usable_end: float
    quality_score: float
    usage_count: int
    last_used_at: datetime | None
    approved: bool


class SceneAssetOverride(BaseModel):
    asset_id: str


class Accepted(BaseModel):
    project_id: str
    action: str
    status: str = "accepted"
