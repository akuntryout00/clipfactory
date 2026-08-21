"""AI Lab tables — fully separate from the content-factory tables (prefix lab_)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class LabVideo(Base):
    __tablename__ = "lab_videos"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _id("lab"))
    prompt: Mapped[str] = mapped_column(Text)
    style: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_duration: Mapped[float] = mapped_column(Float)
    n_segments: Mapped[int] = mapped_column(Integer)
    segment_seconds: Mapped[int] = mapped_column(Integer)
    style_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PLANNING")  # PLANNING → PLANNED → GENERATING_IMAGES → IMAGES_READY → ANIMATING → DONE | FAILED
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    final_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    video_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    keyframes: Mapped[list["LabKeyframe"]] = relationship(back_populates="video", cascade="all, delete-orphan", order_by="LabKeyframe.index")
    segments: Mapped[list["LabSegment"]] = relationship(back_populates="video", cascade="all, delete-orphan", order_by="LabSegment.index")
    events: Mapped[list["LabEvent"]] = relationship(back_populates="video", cascade="all, delete-orphan", order_by="LabEvent.id")


class LabKeyframe(Base):
    __tablename__ = "lab_keyframes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("lab_videos.id"))
    index: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")  # PENDING → GENERATING → DONE | FAILED
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    video: Mapped[LabVideo] = relationship(back_populates="keyframes")


class LabSegment(Base):
    __tablename__ = "lab_segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("lab_videos.id"))
    index: Mapped[int] = mapped_column(Integer)
    from_index: Mapped[int] = mapped_column(Integer)
    to_index: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)  # e.g. Omni interaction id (for conversational edits)
    last_edit: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    video: Mapped[LabVideo] = relationship(back_populates="segments")


class LabEvent(Base):
    """Step-by-step activity log shown in the UI (what is happening, what failed and why)."""
    __tablename__ = "lab_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("lab_videos.id"))
    stage: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(16), default="info")  # info | success | warning | error
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    video: Mapped[LabVideo] = relationship(back_populates="events")
