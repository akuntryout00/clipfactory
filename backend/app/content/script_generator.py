"""Script generation with word-count targets and duration control (PRD §13, §39)."""

from __future__ import annotations

import re

from app.llm.base import LLMProvider
from app.schemas.configs import PersonaConfig, TemplateConfig
from app.schemas.pipeline import ScriptOutput

WORDS_PER_SECOND = 2.5  # ~150 wpm TikTok cadence


def words_of(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def target_word_range(duration: float, wps: float = WORDS_PER_SECOND) -> tuple[int, int]:
    """PRD §39: 15 s → ~35–45, 20 s → ~45–60, 25 s → ~60–70 words (at 2.5 wps; persona may calibrate wps)."""
    centre = duration * wps
    return int(round(centre * 0.88)), int(round(centre * 1.15))


def estimate_duration(text: str) -> float:
    return len(words_of(text)) / WORDS_PER_SECOND


def generate_script(llm: LLMProvider, persona: PersonaConfig, template: TemplateConfig, topic: str, target_duration: float) -> ScriptOutput:
    script = llm.generate_script(persona=persona, template=template, topic=topic, target_duration=target_duration)
    return _sanitize(script, template)


def shorten_script(
    llm: LLMProvider, persona: PersonaConfig, template: TemplateConfig, script: ScriptOutput, target_words: int, reason: str
) -> ScriptOutput:
    return _sanitize(
        llm.shorten_script(persona=persona, template=template, script=script, target_words=target_words, reason=reason), template
    )


def _sanitize(script: ScriptOutput, template: TemplateConfig) -> ScriptOutput:
    """Make sure section order matches the template and texts are clean single-paragraph strings."""
    wanted = [s.type for s in template.sections]
    by_type = {s.type: s for s in script.sections}
    sections = []
    for t in wanted:
        sec = by_type.get(t)
        if sec is None:
            continue
        sec.text = re.sub(r"\s+", " ", sec.text).strip()
        if sec.text:
            sections.append(sec)
    if not sections:
        raise ValueError("LLM returned a script with no usable sections")
    hook = re.sub(r"\s+", " ", script.hook or sections[0].text).strip()
    return ScriptOutput(hook=hook, sections=sections, notes=script.notes)
