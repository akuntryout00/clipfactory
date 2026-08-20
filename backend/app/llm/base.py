"""LLM provider abstraction (PRD §27): business logic never talks to a vendor SDK directly."""
from __future__ import annotations

from typing import Protocol

from app.schemas.configs import PersonaConfig, TemplateConfig
from app.schemas.pipeline import AssetRankOutput, NormalizedScene, ScenePlanOutput, ScriptOutput, WordTiming


class LLMProvider(Protocol):
    name: str

    def generate_script(self, *, persona: PersonaConfig, template: TemplateConfig, topic: str, target_duration: float) -> ScriptOutput: ...

    def shorten_script(self, *, persona: PersonaConfig, template: TemplateConfig, script: ScriptOutput, target_words: int, reason: str) -> ScriptOutput: ...

    def plan_scenes(self, *, persona: PersonaConfig, template: TemplateConfig, topic: str, script: ScriptOutput, words: list[WordTiming], voice_duration: float) -> ScenePlanOutput: ...

    def rank_assets(self, *, topic: str, scenes: list[NormalizedScene], candidates: dict[int, list[dict]]) -> AssetRankOutput: ...


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
