"""LLM provider abstraction (PRD §27): business logic never talks to a vendor SDK directly."""

from __future__ import annotations

from typing import Protocol

from app.schemas.configs import PersonaConfig, TemplateConfig
from app.schemas.pipeline import (
    AssetEnrichOutput,
    AssetRankOutput,
    ClipAnalysis,
    NormalizedScene,
    PersonaDraft,
    ScenePlanOutput,
    ScriptOutput,
    ShotlistMatchOutput,
    ShotlistOutput,
    SlideshowScript,
    TopicIdeasOutput,
    TrendAnalysisOutput,
    WordTiming,
)


class LLMProvider(Protocol):
    name: str

    def generate_script(self, *, persona: PersonaConfig, template: TemplateConfig, topic: str, target_duration: float) -> ScriptOutput: ...

    def shorten_script(
        self, *, persona: PersonaConfig, template: TemplateConfig, script: ScriptOutput, target_words: int, reason: str
    ) -> ScriptOutput: ...

    def plan_scenes(
        self,
        *,
        persona: PersonaConfig,
        template: TemplateConfig,
        topic: str,
        script: ScriptOutput,
        words: list[WordTiming],
        voice_duration: float,
        library: str | None = None,
    ) -> ScenePlanOutput: ...

    def enrich_assets(self, *, assets: list[dict]) -> AssetEnrichOutput: ...

    def analyze_clip(self, *, frames: list[bytes], filename: str, duration: float, categories: list[str]) -> ClipAnalysis: ...

    def rank_assets(self, *, topic: str, scenes: list[NormalizedScene], candidates: dict[int, list[dict]]) -> AssetRankOutput: ...

    def draft_persona(self, *, name: str, age: int | None, location: str | None, language: str, about: str) -> PersonaDraft: ...

    def generate_topics(
        self, *, persona: PersonaConfig, templates: list[TemplateConfig], counts: dict[str, int], exclude: list[str]
    ) -> TopicIdeasOutput: ...

    def generate_shotlist(
        self, *, persona: PersonaConfig, target_count: int, existing_categories: list[str], guidance: str | None
    ) -> ShotlistOutput: ...

    def match_shotlist(self, *, items: list[dict], assets: list[dict]) -> ShotlistMatchOutput: ...

    def generate_slides(
        self, *, persona: PersonaConfig, template: TemplateConfig, topic: str, n_slides: int, photo_tags: list[str]
    ) -> SlideshowScript: ...

    def analyze_trend(
        self, *, persona: PersonaConfig, meta: dict, transcript: str | None, frames: list[bytes], template_ids: list[str]
    ) -> TrendAnalysisOutput: ...


def get_llm(provider: str | None = None) -> LLMProvider:
    from app.config.settings import get_settings

    name = (provider or get_settings().llm_provider).lower()
    if name == "fake":
        from app.llm.fake import FakeLLM

        return FakeLLM()
    if name == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider()
    raise ValueError(f"unknown LLM provider: {name}")
