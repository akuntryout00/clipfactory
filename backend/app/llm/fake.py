"""Deterministic offline LLM used for tests and dry runs."""

from __future__ import annotations

from app.schemas.configs import PersonaConfig, TemplateConfig
from app.schemas.pipeline import (
    AssetEnrichment,
    AssetEnrichOutput,
    AssetRankOutput,
    ClipAnalysis,
    NormalizedScene,
    PersonaDraft,
    SceneAssetChoice,
    ScenePlanOutput,
    ScriptOutput,
    ScriptSection,
    WordTiming,
)

_FILLER = [
    "Most",
    "people",
    "still",
    "do",
    "this",
    "the",
    "slow",
    "way.",
    "You",
    "sit",
    "there,",
    "you",
    "type,",
    "you",
    "miss",
    "half",
    "of",
    "it,",
    "and",
    "then",
    "you",
    "spend",
    "another",
    "twenty",
    "minutes",
    "cleaning",
    "it",
    "up.",
    "Your",
    "phone",
    "already",
    "does",
    "this",
    "for",
    "you.",
    "Record",
    "it,",
    "transcribe",
    "it,",
    "summarize",
    "it,",
    "done.",
    "Nobody",
    "is",
    "grading",
    "your",
    "effort",
    "here.",
    "The",
    "tool",
    "exists,",
    "it",
    "is",
    "cheap,",
    "and",
    "it",
    "is",
    "honestly",
    "faster",
    "than",
    "you.",
    "Stop",
    "pretending",
    "manual",
    "is",
    "noble.",
]


class FakeLLM:
    name = "fake"

    def generate_script(self, *, persona: PersonaConfig, template: TemplateConfig, topic: str, target_duration: float) -> ScriptOutput:
        from app.content.script_generator import target_word_range

        lo, hi = target_word_range(target_duration, getattr(persona, "speech_rate_wps", 2.5))
        total = (lo + hi) // 2
        return self._build(template, topic, total)

    def shorten_script(
        self, *, persona: PersonaConfig, template: TemplateConfig, script: ScriptOutput, target_words: int, reason: str
    ) -> ScriptOutput:
        from app.content.script_generator import words_of

        current = len(words_of(script.full_text))
        return self._build(template, script.hook, min(target_words, max(8, current - 8)))

    def _build(self, template: TemplateConfig, topic: str, total_words: int) -> ScriptOutput:
        sections: list[ScriptSection] = []
        remaining = total_words
        pool = list(_FILLER)
        cursor = 0
        for i, sec in enumerate(template.sections):
            n = max(3, int(round(total_words * sec.weight))) if i < len(template.sections) - 1 else max(3, remaining)
            n = min(n, remaining) if i < len(template.sections) - 1 else n
            if sec.type == "hook":
                words = (f"{topic.rstrip('.')}?".split() + pool)[:n]
            else:
                words = [pool[(cursor + k) % len(pool)] for k in range(n)]
                cursor += n
            text = " ".join(words).strip()
            if not text.endswith((".", "?", "!")):
                text += "."
            sections.append(ScriptSection(type=sec.type, text=text))
            remaining -= n
        return ScriptOutput(hook=sections[0].text, sections=sections)

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
        from app.content.scene_planner import heuristic_plan

        return heuristic_plan(script, words, template)

    def rank_assets(self, *, topic: str, scenes: list[NormalizedScene], candidates: dict[int, list[dict]]) -> AssetRankOutput:
        used: set[str] = set()
        choices = []
        for sc in scenes:
            for c in candidates.get(sc.order, []):
                if c["asset_id"] not in used:
                    used.add(c["asset_id"])
                    choices.append(SceneAssetChoice(scene_order=sc.order, asset_id=c["asset_id"], reason="top candidate"))
                    break
        return AssetRankOutput(choices=choices)

    def enrich_assets(self, *, assets: list[dict]) -> AssetEnrichOutput:
        return AssetEnrichOutput(
            assets=[
                AssetEnrichment(
                    asset_id=a["asset_id"],
                    tags=list(a.get("tags") or []) + ["broll"],
                    action=a.get("action"),
                    location=a.get("location"),
                    mood=None,
                    shot=a.get("shot"),
                )
                for a in assets
            ]
        )

    def draft_persona(self, *, name: str, age: int | None, location: str | None, language: str, about: str) -> PersonaDraft:
        role = about.strip().split(".")[0][:40] or "Creator"
        return PersonaDraft(
            display_name=f"{name} — {role}",
            background=f"{about.strip()} ({age or '?'}, {location or 'somewhere'})",
            speaks_as="first person ('I'), talking to one viewer ('you')",
            audience=f"People who share {name}'s interests",
            topics=["daily routines", "tools", "lessons learned", "behind the scenes"],
            tone=["friendly", "direct", "concrete"],
            avoid=["hype", "fake statistics", "corporate language"],
            tools=["Notion (planning)"],
            closing_style="punchline_no_cta",
            product_mention_policy="never",
        )

    def analyze_clip(self, *, frames: list[bytes], filename: str, duration: float, categories: list[str]) -> ClipAnalysis:
        stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        base = "phone" if "phone" in stem else "walk" if "walk" in stem else "desk"
        cat = next((c for c in categories if base in c), categories[0] if categories else base)
        return ClipAnalysis(
            description=f"Synthetic analysis of {stem} ({duration:.1f}s, {len(frames)} frames)",
            tags=[base, "clip", "test", "broll", "cafe"],
            action=f"{base}_action",
            location="cafe",
            shot="medium",
            mood="neutral",
            suggested_category=cat,
            quality_score=0.75,
            notes=None,
        )
