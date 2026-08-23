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
    ShotlistAssignment,
    ShotlistItemOut,
    ShotlistMatchOutput,
    ShotlistOutput,
    SlideshowScript,
    SlideSpec,
    TopicIdea,
    TopicIdeasOutput,
    TrendAnalysisOutput,
    TrendHook,
    TrendSection,
    TrendTemplateProposal,
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

    def generate_topics(
        self, *, persona: PersonaConfig, templates: list[TemplateConfig], counts: dict[str, int], exclude: list[str]
    ) -> TopicIdeasOutput:
        items = []
        for t in templates:
            for i in range(counts.get(t.id, 0)):
                items.append(TopicIdea(topic=f"{t.id} idea {i + 1} about {persona.topics[i % len(persona.topics)]}", template_id=t.id))
        return TopicIdeasOutput(items=items)

    def generate_shotlist(
        self, *, persona: PersonaConfig, target_count: int, existing_categories: list[str], guidance: str | None
    ) -> ShotlistOutput:
        base = [
            ("desk", "Typing on laptop, close-up", "typing_laptop", "office", "close"),
            ("phone", "Scrolling phone at a table", "scrolling_phone", "cafe", "close"),
            ("walking", "Walking down the street, medium", "walking_street", "street", "medium"),
            ("reaction", "Looking up from the screen and smiling", "reaction_smile", "cafe", "medium"),
        ]
        n = len(base)
        per, extra = divmod(max(1, target_count), n)
        items = [
            ShotlistItemOut(
                category=c,
                title=t,
                description=f"Film: {t}. {guidance or ''}".strip(),
                shot=sh,
                action=a,
                location=loc,
                mood="neutral",
                tags=[c, a.split("_")[0], "broll"],
                count=per + (1 if i < extra else 0),
            )
            for i, (c, t, a, loc, sh) in enumerate(base)
        ]
        return ShotlistOutput(items=[it for it in items if it.count > 0])

    def match_shotlist(self, *, items: list[dict], assets: list[dict]) -> ShotlistMatchOutput:
        out = []
        for a in assets:
            idx = next((i for i, it in enumerate(items) if it.get("action") and it["action"] == a.get("action")), None)
            if idx is None:
                idx = next(
                    (
                        i
                        for i, it in enumerate(items)
                        if it.get("category") and str(a.get("file", "")).split("/")[-2:-1] == [it["category"]]
                    ),
                    None,
                )
            out.append(ShotlistAssignment(asset_id=a["asset_id"], item_index=idx))
        return ShotlistMatchOutput(assignments=out)

    def generate_slides(
        self, *, persona: PersonaConfig, template: TemplateConfig, topic: str, n_slides: int, photo_tags: list[str]
    ) -> SlideshowScript:
        tags = photo_tags or ["desk", "cafe", "phone"]
        slides = [
            SlideSpec(
                index=i,
                text=(
                    f"Things nobody tells you about {topic}"
                    if i == 0
                    else f"Slide {i}: {topic} idea {i}"
                    if i < n_slides - 1
                    else "And that's the whole trick."
                ),
                photo_intent=f"photo for slide {i}",
                query_tags=[tags[i % len(tags)]],
                seconds=3.0 if i == 0 else 2.5,
            )
            for i in range(n_slides)
        ]
        return SlideshowScript(title=f"Slideshow: {topic[:40]}", slides=slides, post_caption=f"{topic} — save this.")

    def analyze_trend(
        self, *, persona: PersonaConfig, meta: dict, transcript: str | None, frames: list[bytes], template_ids: list[str]
    ) -> TrendAnalysisOutput:
        dur = float(meta.get("duration") or 18.0)
        secs = [
            TrendSection(label="hook", start=0, end=round(dur * 0.15, 1), purpose="Pattern interrupt"),
            TrendSection(label="body", start=round(dur * 0.15, 1), end=round(dur * 0.85, 1), purpose="The substance"),
            TrendSection(label="payoff", start=round(dur * 0.85, 1), end=round(dur, 1), purpose="Close"),
        ]
        tid = "trend_remix_v1"
        n = 2
        while tid in template_ids:
            tid, n = f"trend_remix_v{n}", n + 1
        return TrendAnalysisOutput(
            summary=f"Fake analysis of {meta.get('title') or 'video'} ({dur:.0f}s).",
            hook=TrendHook(text=(transcript or "…").split(".")[0][:80], type="bold claim", seconds=2.0),
            structure=secs,
            pacing="fast cuts every ~2 s",
            visual_style="handheld, face on camera",
            caption_style="big centered captions",
            audio="voice-over with trend sound",
            why_it_works=["curiosity gap", "fast pacing"],
            tips_for_persona=[f"Use {persona.topics[0]} as the subject", "Open with the result"],
            remix_ideas=["Why I stopped X", "3 things about Y"],
            template_proposal=TrendTemplateProposal(
                id=tid,
                name="Trend remix",
                description="Structure copied from an analysed video",
                duration_min=15,
                duration_target=18,
                duration_max=22,
                sections=secs,
                voiceover=True,
                closing="End on the payoff line, no CTA.",
                shot_min=1.5,
                shot_max=3.5,
                overlays_min=1,
                overlays_max=3,
            ),
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
