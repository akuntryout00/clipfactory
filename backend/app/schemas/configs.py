"""Pydantic models for config-driven persona / template / caption style."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VoiceConfig(BaseModel):
    provider: str = "elevenlabs"
    voice_id: str
    model_id: str = "eleven_multilingual_v2"
    speed: float = 1.0
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0


class PersonaConfig(BaseModel):
    id: str
    name: str
    language: str = "en-US"
    audience: str
    topics: list[str]
    tone: list[str]
    avoid: list[str] = []
    target_duration: float = 18
    max_duration: float = 25
    voice: VoiceConfig
    default_music_category: str | None = None

    @model_validator(mode="after")
    def _durations(self):
        if self.target_duration > self.max_duration:
            raise ValueError("target_duration must be <= max_duration")
        return self


class DurationSpec(BaseModel):
    min: float
    target: float
    max: float

    @model_validator(mode="after")
    def _order(self):
        if not (self.min <= self.target <= self.max):
            raise ValueError("duration must satisfy min <= target <= max")
        return self


class SectionSpec(BaseModel):
    type: str
    weight: float = Field(gt=0, le=1)
    guidance: str = ""


class RangeSpec(BaseModel):
    min: float
    max: float

    @model_validator(mode="after")
    def _order(self):
        if self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class TemplateConfig(BaseModel):
    id: str
    name: str
    description: str = ""
    duration: DurationSpec
    sections: list[SectionSpec]
    voiceover: bool = True
    caption_style: str = "dynamic_center"
    music_category: str | None = None
    shot_duration: RangeSpec = RangeSpec(min=1.5, max=4.0)
    overlays: RangeSpec = RangeSpec(min=1, max=3)

    @model_validator(mode="after")
    def _weights(self):
        total = sum(s.weight for s in self.sections)
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"section weights must sum to 1.0 (got {total:.3f})")
        if not self.sections:
            raise ValueError("template needs at least one section")
        return self


class SafeZone(BaseModel):
    top: float = 0.10
    bottom: float = 0.18
    right: float = 0.12
    left: float = 0.05


class OverlayStyle(BaseModel):
    font_name: str = "DejaVu Sans"
    font_size: int = 96
    bold: bool = True
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    outline: int = 6
    vertical_anchor_ratio: float = 0.36
    max_chars_per_line: int = 14
    fade_ms: int = 150


class CaptionStyleConfig(BaseModel):
    id: str
    font_name: str = "DejaVu Sans"
    font_file: str | None = None
    font_size: int = 78
    bold: bool = True
    primary_color: str = "&H00FFFFFF"
    emphasis_color: str = "&H0000E5FF"
    outline_color: str = "&H00000000"
    outline: int = 4
    shadow: int = 1
    max_words_per_chunk: int = 4
    min_words_per_chunk: int = 2
    max_lines: int = 2
    max_chars_per_line: int = 16
    position: Literal["center", "lower_center"] = "lower_center"
    vertical_anchor_ratio: float = 0.72
    animation: Literal["none", "pop", "fade"] = "pop"
    pop_duration_ms: int = 120
    safe_zone: SafeZone = SafeZone()
    overlay: OverlayStyle = OverlayStyle()
