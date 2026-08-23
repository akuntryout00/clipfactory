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

    def for_speech(self) -> ScriptOutput:
        """Copy with section texts normalised for TTS (e.g. 'POV:' dropped). Word counts drive section ranges."""
        from app.voice.normalize import speech_text

        secs = [ScriptSection(type=sec.type, text=speech_text(sec.text)) for sec in self.sections]
        secs = [sec for sec in secs if sec.text]
        return ScriptOutput(hook=speech_text(self.hook) or (secs[0].text if secs else ""), sections=secs, notes=self.notes)


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
    overlay_text: str | None = Field(
        default=None, description="Optional big creative text overlay (max 4 words, ALL CAPS ok). null if none."
    )


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


# ---------- asset enrichment (AI-assisted semantic metadata, PRD §8) ----------


class AssetEnrichment(BaseModel):
    asset_id: str
    tags: list[str] = Field(description="6-12 lowercase single-word search tags describing what is visible / the action")
    action: str | None = Field(default=None, description="snake_case main action, e.g. typing_laptop, scrolling_phone")
    location: str | None = Field(default=None, description="cafe | office | street | home | store | other")
    mood: str | None = Field(default=None, description="neutral | focused | stressed | relaxed | happy")
    shot: str | None = Field(default=None, description="close | medium | wide")


class AssetEnrichOutput(BaseModel):
    assets: list[AssetEnrichment]


# ---------- AI clip analysis (vision) ----------


class ClipAnalysis(BaseModel):
    description: str = Field(description="One-sentence literal description of what is visible and happening")
    tags: list[str] = Field(description="6-12 lowercase single-word search tags: objects, action, place, framing, feeling, concepts")
    action: str = Field(description="snake_case main action, e.g. typing_laptop, scrolling_phone, walking_street")
    location: str = Field(description="cafe | office | street | home | store | gym | park | other")
    shot: str = Field(description="close | medium | wide")
    mood: str = Field(description="neutral | focused | stressed | relaxed | happy | energetic")
    suggested_category: str = Field(
        description="Best matching library category from the provided list, or a short new lowercase folder name"
    )
    quality_score: float = Field(default=0.8, ge=0, le=1, description="0-1 technical/visual quality estimate (steady, lit, usable)")
    notes: str | None = Field(default=None, description="Anything an editor should know (shaky part, faces, text on screen)")


class PersonaDraft(BaseModel):
    """What the LLM fills in from a few facts about a new persona (wizard step 4)."""

    display_name: str = Field(description="Short list label: '<Name> — <role in 2-4 words>', e.g. 'Anna — UX Designer'")
    background: str = Field(description="1-2 sentences: career, what they do now, how long, hobbies — in the same language as the input")
    speaks_as: str = Field(description="Narration stance, e.g. \"first person ('I'), talking to one viewer ('you')\"")
    audience: str = Field(description="One sentence: who watches these videos and why")
    topics: list[str] = Field(description="4-6 content pillars this persona can talk about credibly, lowercase short phrases")
    tone: list[str] = Field(description="4-6 tone words/phrases matching the character")
    avoid: list[str] = Field(description="4-8 things the scripts must never do (vocabulary, hype, claims) for this character")
    tools: list[str] = Field(description="3-6 tools/apps/brands the persona really uses, 'Name (what for)' form; [] if unknown")
    closing_style: str = Field(description="punchline_no_cta | question | soft_follow")
    product_mention_policy: str = Field(description="never | occasional_soft | problem_solution_only")


class TopicIdea(BaseModel):
    topic: str = Field(description="Video topic written the way the hook could sound; first person where natural; <= 120 chars")
    template_id: str = Field(description="One of the allowed template ids")


class TopicIdeasOutput(BaseModel):
    items: list[TopicIdea]


class ShotlistItemOut(BaseModel):
    category: str = Field(description="lowercase folder name, e.g. desk, phone, walking, cafe, reaction, product, networking, sport, home")
    title: str = Field(description="short label, <= 60 chars, e.g. 'Typing on laptop, close-up'")
    description: str = Field(description="what to film: framing, action, place, light — one or two sentences the creator can follow")
    shot: str = Field(description="close | medium | wide")
    action: str = Field(description="snake_case main action, e.g. typing_laptop, scrolling_phone, walking_street")
    location: str = Field(description="cafe | office | street | home | store | gym | park | other")
    mood: str = Field(description="neutral | focused | stressed | relaxed | happy | energetic")
    tags: list[str] = Field(description="4-8 lowercase single-word search tags")
    count: int = Field(description="how many distinct clips of this shot to film (1-4)")


class ShotlistOutput(BaseModel):
    items: list[ShotlistItemOut]


class ShotlistAssignment(BaseModel):
    asset_id: str
    item_index: int | None = Field(description="index into the given shot list, or null if no item matches well")


class ShotlistMatchOutput(BaseModel):
    assignments: list[ShotlistAssignment]


class TrendHook(BaseModel):
    text: str = Field(description="the hook as spoken/shown in the first 1-3 seconds (verbatim or close)")
    type: str = Field(description="pattern-interrupt | question | bold claim | POV | list promise | story open | visual hook | other")
    seconds: float = Field(description="how long the hook lasts")


class TrendSection(BaseModel):
    label: str = Field(description="short name: hook, setup, item_1, payoff, cta…")
    start: float
    end: float
    purpose: str = Field(description="what this part does for retention (one sentence)")


class TrendTemplateProposal(BaseModel):
    id: str = Field(description="snake_case template id ending with _v1, e.g. myth_bust_v1")
    name: str
    description: str
    duration_min: float
    duration_target: float
    duration_max: float
    sections: list[TrendSection] = Field(description="ordered sections with start/end in seconds of the analysed video; purpose = guidance")
    voiceover: bool
    closing: str = Field(description="one-sentence closing rule (how the video should end)")
    shot_min: float = Field(description="typical shortest shot in seconds")
    shot_max: float = Field(description="typical longest shot in seconds")
    overlays_min: int
    overlays_max: int


class TrendAnalysisOutput(BaseModel):
    summary: str = Field(description="2-3 sentences: what the video is and the core mechanic")
    hook: TrendHook
    structure: list[TrendSection]
    pacing: str = Field(description="cuts, shot length, speech speed, on-screen text rhythm — one short paragraph")
    visual_style: str = Field(description="framing, camera, lighting, B-roll type, face on camera or not")
    caption_style: str = Field(description="captions/on-screen text: position, size, emphasis, animation, colour")
    audio: str = Field(description="voice-over vs talking head, music/trend sound, sound effects")
    why_it_works: list[str] = Field(description="3-6 concrete retention/engagement mechanics")
    tips_for_persona: list[str] = Field(
        description="4-8 specific, actionable tips for THIS persona to use the mechanic with their own B-roll"
    )
    remix_ideas: list[str] = Field(description="4-6 topic ideas for this persona that reuse the mechanic, phrased as hooks")
    template_proposal: TrendTemplateProposal


class SlideSpec(BaseModel):
    index: int
    text: str = Field(description="the on-screen line for this slide, max ~10 words, natural case, no hashtags/emojis")
    photo_intent: str = Field(description="what photo fits this slide (subject, place, mood) — used to pick from the library")
    query_tags: list[str] = Field(description="3-6 lowercase single-word tags to match library photos")
    seconds: float = Field(description="how long the slide stays: 2-4 s (longer for more words)")


class SlideshowScript(BaseModel):
    title: str = Field(description="short internal title")
    slides: list[SlideSpec]
    post_caption: str = Field(description="suggested post caption (1-2 lines, no hashtags)")
