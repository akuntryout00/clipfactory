"""OpenAI provider using structured outputs (chat.completions.parse → pydantic)."""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from app.config.settings import get_settings
from app.content.scene_planner import section_word_ranges
from app.llm import prompts
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

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        from openai import OpenAI

        s = get_settings()
        key = api_key or s.openai_api_key
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=key)
        self.model = model or s.openai_model

    def _parse(self, system: str, user, schema: type[T], temperature: float = 0.8) -> T:
        kwargs = dict(
            model=self.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], response_format=schema
        )
        if not self.model.startswith(("o1", "o3", "o4", "gpt-5")):
            kwargs["temperature"] = temperature
        completion = self._client.chat.completions.parse(**kwargs)
        msg = completion.choices[0].message
        if msg.refusal:
            raise RuntimeError(f"LLM refused: {msg.refusal}")
        if msg.parsed is None:
            raise RuntimeError("LLM returned no parsed output")
        return msg.parsed

    def generate_script(self, *, persona: PersonaConfig, template: TemplateConfig, topic: str, target_duration: float) -> ScriptOutput:
        from app.content.script_generator import target_word_range

        lo, hi = target_word_range(target_duration, getattr(persona, "speech_rate_wps", 2.5))
        return self._parse(
            prompts.SCRIPT_SYSTEM, prompts.script_user_prompt(persona, template, topic, target_duration, lo, hi), ScriptOutput
        )

    def shorten_script(
        self, *, persona: PersonaConfig, template: TemplateConfig, script: ScriptOutput, target_words: int, reason: str
    ) -> ScriptOutput:
        return self._parse(
            prompts.SCRIPT_SYSTEM,
            prompts.shorten_user_prompt(persona, template, script, target_words, reason),
            ScriptOutput,
            temperature=0.5,
        )

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
    ) -> ScenePlanOutput:
        ranges = section_word_ranges(script, words)
        return self._parse(
            prompts.PLAN_SYSTEM,
            prompts.plan_user_prompt(persona, template, topic, script, words, voice_duration, ranges, library),
            ScenePlanOutput,
            temperature=0.4,
        )

    def enrich_assets(self, *, assets: list[dict]) -> AssetEnrichOutput:
        return self._parse(prompts.ENRICH_SYSTEM, prompts.enrich_user_prompt(assets), AssetEnrichOutput, temperature=0.2)

    def rank_assets(self, *, topic: str, scenes: list[NormalizedScene], candidates: dict[int, list[dict]]) -> AssetRankOutput:
        return self._parse(prompts.RANK_SYSTEM, prompts.rank_user_prompt(topic, scenes, candidates), AssetRankOutput, temperature=0.3)

    def generate_topics(
        self, *, persona: PersonaConfig, templates: list[TemplateConfig], counts: dict[str, int], exclude: list[str]
    ) -> TopicIdeasOutput:
        return self._parse(
            prompts.TOPICS_SYSTEM, prompts.topics_user_prompt(persona, templates, counts, exclude), TopicIdeasOutput, temperature=0.9
        )

    def generate_shotlist(
        self, *, persona: PersonaConfig, target_count: int, existing_categories: list[str], guidance: str | None
    ) -> ShotlistOutput:
        return self._parse(
            prompts.SHOTLIST_SYSTEM,
            prompts.shotlist_user_prompt(persona, target_count, existing_categories, guidance),
            ShotlistOutput,
            temperature=0.7,
        )

    def match_shotlist(self, *, items: list[dict], assets: list[dict]) -> ShotlistMatchOutput:
        return self._parse(
            prompts.SHOTLIST_MATCH_SYSTEM, prompts.shotlist_match_user_prompt(items, assets), ShotlistMatchOutput, temperature=0.1
        )

    def generate_slides(
        self, *, persona: PersonaConfig, template: TemplateConfig, topic: str, n_slides: int, photo_tags: list[str]
    ) -> SlideshowScript:
        return self._parse(
            prompts.SLIDES_SYSTEM,
            prompts.slides_user_prompt(persona, template, topic, n_slides, photo_tags),
            SlideshowScript,
            temperature=0.8,
        )

    def analyze_trend(
        self, *, persona: PersonaConfig, meta: dict, transcript: str | None, frames: list[bytes], template_ids: list[str]
    ) -> TrendAnalysisOutput:
        import base64

        content: list[dict] = [{"type": "text", "text": prompts.trend_user_prompt(persona, meta, transcript, len(frames), template_ids)}]
        for fr in frames:
            content.append(
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(fr).decode(), "detail": "low"}}
            )
        return self._parse(prompts.TREND_SYSTEM, content, TrendAnalysisOutput, temperature=0.4)

    def draft_persona(self, *, name: str, age: int | None, location: str | None, language: str, about: str) -> PersonaDraft:
        return self._parse(
            prompts.PERSONA_DRAFT_SYSTEM,
            prompts.persona_draft_user_prompt(name=name, age=age, location=location, language=language, about=about),
            PersonaDraft,
            temperature=0.6,
        )

    def analyze_clip(self, *, frames: list[bytes], filename: str, duration: float, categories: list[str]) -> ClipAnalysis:
        import base64

        content: list[dict] = [{"type": "text", "text": prompts.analyze_user_prompt(filename, duration, categories, len(frames))}]
        for fr in frames:
            content.append(
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(fr).decode(), "detail": "low"}}
            )
        return self._parse(prompts.ANALYZE_SYSTEM, content, ClipAnalysis, temperature=0.2)
