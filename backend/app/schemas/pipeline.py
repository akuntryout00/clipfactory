"""Pipeline data contracts: script, word timings, scene plan, Video JSON."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


# ---------- script ----------

class ScriptSection(BaseModel):
    type: str
    text: str


class ScriptOutput(BaseModel):
    hook: str = Field(description="The first line (1-2 s pattern interrupt). Must equal the first section text.")
    sections: list[ScriptSection]
    notes: str | None = Field(default=None, description="Optional creative notes (not spoken).")

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.sections if s.text.strip())


# ---------- voice ----------

class WordTiming(BaseModel):
    word: str
    start: float
    end: float


class VoiceResult(BaseModel):
    audio_path: str
    duration: float
    words: list[WordTiming]
    provider: str
    alignment_path: str | None = None


# ---------- scene planning ----------

class PlannedScene(BaseModel):
    section: str
    first_word: int = Field(ge=0, description="Index (0-based) of first spoken word in this scene")
    last_word: int = Field(ge=0, description="Index (0-based, inclusive) of last spoken word in this scene")
    intent: str = Field(description="What the viewer should SEE (visual description, not the spoken words)")
    query_tags: list[str] = Field(description="3-6 short B-roll search tags, e.g. ['typing','laptop','desk']")
    overlay_text: str | None = Field(default=None, description="Optional big creative text overlay (max 4 words, ALL CAPS ok). null if none.")


class ScenePlanOutput(BaseModel):
    scenes: list[PlannedScene]


class NormalizedScene(BaseModel):
    order: int
    section: str
    start: float
    end: float
    first_word: int
    last_word: int
    intent: str
    query_tags: list[str]
    overlay_text: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


# ---------- asset ranking ----------

class SceneAssetChoice(BaseModel):
    scene_order: int
    asset_id: str
    reason: str | None = None


class AssetRankOutput(BaseModel):
    choices: list[SceneAssetChoice]


# ---------- captions ----------

class CaptionChunk(BaseModel):
    start: float
    end: float
    text: str
    emphasis_index: int | None = Field(default=None, description="index of emphasised word within chunk")


# ---------- Video JSON ----------

class VoiceoverSpec(BaseModel):
    text: str
    audio: str
    duration: float


class VideoJSONScene(BaseModel):
    order: int
    start: float
    end: float
    asset_id: str
    asset_file: str
    asset_start: float = 0.0
    text: str | None = None
    section: str | None = None

    @model_validator(mode="after")
    def _order(self):
        if self.end <= self.start:
            raise ValueError(f"scene {self.order}: end must be > start")
        if self.asset_start < 0:
            raise ValueError("asset_start must be >= 0")
        return self


class VideoJSON(BaseModel):
    version: str = "1.0"
    persona: str
    template: str
    topic: str
    voiceover: VoiceoverSpec
    scenes: list[VideoJSONScene]
    caption_style: str = "dynamic_center"
    music: str | None = None
    captions: list[CaptionChunk] = []
    seed: int = 0

    @model_validator(mode="after")
    def _contiguous(self):
        if not self.scenes:
            raise ValueError("at least one scene required")
        if abs(self.scenes[0].start) > 1e-6:
            raise ValueError("first scene must start at 0")
        for a, b in zip(self.scenes, self.scenes[1:]):
            if abs(a.end - b.start) > 0.011:
                raise ValueError(f"scenes {a.order}->{b.order} not contiguous ({a.end} vs {b.start})")
            if b.order != a.order + 1:
                raise ValueError("scene order must be sequential")
        return self

    @property
    def total_duration(self) -> float:
        return self.scenes[-1].end
