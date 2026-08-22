"""SQLAlchemy ORM models."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class ProjectStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    GENERATING_SCRIPT = "GENERATING_SCRIPT"
    GENERATING_VOICE = "GENERATING_VOICE"
    PLANNING = "PLANNING"
    SELECTING_ASSETS = "SELECTING_ASSETS"
    GENERATING_CAPTIONS = "GENERATING_CAPTIONS"
    RENDERING = "RENDERING"
    READY = "READY"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


class Persona(Base):
    __tablename__ = "personas"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    """Key/value store for UI-editable global settings (e.g. key 'captions')."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file: Mapped[str] = mapped_column(String(512), unique=True)
    persona_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mood: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # technical
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    orientation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # selection
    usable_start: Mapped[float] = mapped_column(Float, default=0.0)
    usable_end: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.8)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def search_text(self) -> str:
        parts = [self.description or "", self.action or "", self.location or "", self.shot or "", self.mood or ""]
        parts += list(self.tags or [])
        return " ".join(parts).lower()


class AssetUsage(Base):
    __tablename__ = "asset_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    project_id: Mapped[str] = mapped_column(String(64))
    render_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoProject(Base):
    __tablename__ = "video_projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("proj"))
    persona_id: Mapped[str] = mapped_column(String(64))
    template_id: Mapped[str] = mapped_column(String(64))
    topic: Mapped[str] = mapped_column(Text)
    target_duration: Mapped[float] = mapped_column(Float, default=18.0)
    actual_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=ProjectStatus.DRAFT.value)
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    script: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_version: Mapped[int] = mapped_column(Integer, default=0)
    voice_version: Mapped[int] = mapped_column(Integer, default=0)
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    render_version: Mapped[int] = mapped_column(Integer, default=0)
    current_render_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # per-project caption overrides (font, size, position…) on top of the global caption settings; None = use defaults
    caption_overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    scenes: Mapped[list[VideoScene]] = relationship(back_populates="project", cascade="all, delete-orphan")
    voices: Mapped[list[VoiceGeneration]] = relationship(back_populates="project", cascade="all, delete-orphan")
    renders: Mapped[list[Render]] = relationship(back_populates="project", cascade="all, delete-orphan")
    events: Mapped[list[ProjectEvent]] = relationship(back_populates="project", cascade="all, delete-orphan")


class VideoScene(Base):
    __tablename__ = "video_scenes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    plan_version: Mapped[int] = mapped_column(Integer)
    order: Mapped[int] = mapped_column(Integer)
    asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    asset_start_time: Mapped[float] = mapped_column(Float, default=0.0)
    overlay_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    section: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_tags: Mapped[list] = mapped_column(JSON, default=list)

    project: Mapped[VideoProject] = relationship(back_populates="scenes")


class VoiceGeneration(Base):
    __tablename__ = "voice_generations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("voice"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    version: Mapped[int] = mapped_column(Integer)
    script_version: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    audio_path: Mapped[str] = mapped_column(String(512))
    alignment_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[VideoProject] = relationship(back_populates="voices")


class Render(Base):
    __tablename__ = "renders"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("render"))
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    version: Mapped[int] = mapped_column(Integer)
    plan_version: Mapped[int] = mapped_column(Integer)
    voice_version: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    output_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    qc: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[VideoProject] = relationship(back_populates="renders")


class ProjectEvent(Base):
    __tablename__ = "project_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"))
    stage: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[VideoProject] = relationship(back_populates="events")
