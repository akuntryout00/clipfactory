"""Scene planning: LLM proposes semantic word ranges; backend snaps to voice timings and enforces template rules.

Voice timings are the master clock (PRD §30). Scenes never use fixed 5 s blocks (PRD §17).
"""

from __future__ import annotations

import re

from app.schemas.configs import TemplateConfig
from app.schemas.pipeline import NormalizedScene, PlannedScene, ScenePlanOutput, ScriptOutput, WordTiming

_TAIL_PAD = 0.35  # seconds of picture after the last word


def section_word_ranges(script: ScriptOutput, words: list[WordTiming]) -> dict[str, tuple[int, int]]:
    """Map each script section to (first_idx, last_idx) in the spoken word list by counting words."""
    ranges: dict[str, tuple[int, int]] = {}
    cursor = 0
    total = len(words)
    for sec in script.sections:
        n = len([w for w in re.split(r"\s+", sec.text.strip()) if w])
        if n == 0:
            continue
        first = min(cursor, total - 1)
        last = min(cursor + n - 1, total - 1)
        ranges[sec.type] = (first, last)
        cursor += n
    # if TTS normalisation changed the word count, stretch the last section to the end
    if ranges and total:
        last_type = list(ranges)[-1]
        f, _ = ranges[last_type]
        ranges[last_type] = (f, total - 1)
    return ranges


def _sentence_breaks(words: list[WordTiming], lo: int, hi: int) -> list[int]:
    """Indices within [lo, hi] whose word ends a sentence/clause."""
    return [i for i in range(lo, hi + 1) if re.search(r"[.!?;:,]$", words[i].word)]


def heuristic_plan(script: ScriptOutput, words: list[WordTiming], template: TemplateConfig) -> ScenePlanOutput:
    """Deterministic fallback planner: split each section at sentence/clause breaks into ~2.5-3.5 s shots."""
    ranges = section_word_ranges(script, words)
    ideal = (template.shot_duration.min + template.shot_duration.max) / 2.0
    scenes: list[PlannedScene] = []
    for sec_type, (lo, hi) in ranges.items():
        start_i = lo
        breaks = set(_sentence_breaks(words, lo, hi))
        i = lo
        while i <= hi:
            dur = words[i].end - words[start_i].start
            is_last = i == hi
            if is_last or (dur >= ideal and (i in breaks or dur >= template.shot_duration.max)):
                tags = _tags_from_text(" ".join(w.word for w in words[start_i : i + 1]))
                overlay = None
                if sec_type.startswith("item_") or sec_type == "hook":
                    overlay = _overlay_from_text(sec_type, " ".join(w.word for w in words[start_i : i + 1]))
                scenes.append(
                    PlannedScene(
                        section=sec_type,
                        first_word=start_i,
                        last_word=i,
                        intent=f"{sec_type}: {' '.join(w.word for w in words[start_i : i + 1])}",
                        query_tags=tags,
                        overlay_text=overlay if start_i == lo else None,
                    )
                )
                start_i = i + 1
            i += 1
    return ScenePlanOutput(scenes=scenes)


_GENERIC_TAGS = ["desk", "laptop", "phone", "walking", "coffee", "typing", "stressed", "scrolling"]


def _tags_from_text(text: str) -> list[str]:
    text_l = text.lower()
    tags = [t for t in _GENERIC_TAGS if t in text_l or t[:-1] in text_l]
    words = [w.strip(".,!?;:").lower() for w in text.split()]
    tags += [w for w in words if len(w) > 4][:3]
    return (tags or ["desk", "laptop"])[:6]


def _overlay_from_text(section: str, text: str) -> str | None:
    words = [w.strip(".,!?;:") for w in text.split() if w.strip(".,!?;:")]
    if not words:
        return None
    if section.startswith("item_"):
        n = section.split("_")[-1]
        return f"{n}. {' '.join(words[:3]).upper()}"
    return " ".join(words[:3]).upper()


def normalize_plan(
    plan: ScenePlanOutput, words: list[WordTiming], template: TemplateConfig, voice_duration: float
) -> list[NormalizedScene]:
    """Snap LLM word ranges to real timings, fix gaps/overlaps, merge too-short and split too-long shots,
    cap overlays, and return ordered contiguous scenes covering [0, voice_duration + tail]."""
    n_words = len(words)
    if n_words == 0:
        raise ValueError("no words to plan against")
    smin, smax = template.shot_duration.min, template.shot_duration.max

    # 1) clamp + sort + make word ranges contiguous
    raw = sorted(plan.scenes, key=lambda s: s.first_word)
    fixed: list[PlannedScene] = []
    cursor = 0
    for s in raw:
        first = max(cursor, min(s.first_word, n_words - 1))
        last = max(first, min(s.last_word, n_words - 1))
        if first > last or first >= n_words:
            continue
        fixed.append(
            PlannedScene(
                section=s.section, first_word=first, last_word=last, intent=s.intent, query_tags=s.query_tags, overlay_text=s.overlay_text
            )
        )
        cursor = last + 1
    if not fixed:
        fixed = [
            PlannedScene(
                section=template.sections[0].type,
                first_word=0,
                last_word=n_words - 1,
                intent="generic",
                query_tags=["desk", "laptop"],
                overlay_text=None,
            )
        ]
    if fixed[0].first_word != 0:
        fixed[0].first_word = 0
    if fixed[-1].last_word != n_words - 1:
        fixed[-1].last_word = n_words - 1

    def dur_of(s: PlannedScene) -> float:
        return words[s.last_word].end - words[s.first_word].start

    def split_long(items: list[PlannedScene]) -> list[PlannedScene]:
        """Split scenes longer than smax*1.15 at the word nearest the midpoint (prefer punctuation)."""
        out: list[PlannedScene] = []
        stack = list(items)
        while stack:
            s = stack.pop(0)
            if dur_of(s) > smax * 1.15 and s.last_word > s.first_word:
                mid_t = words[s.first_word].start + dur_of(s) / 2
                best = min(
                    range(s.first_word, s.last_word),
                    key=lambda i: abs(words[i].end - mid_t) - (0.3 if re.search(r"[.!?,;:]$", words[i].word) else 0),
                )
                a = PlannedScene(
                    section=s.section,
                    first_word=s.first_word,
                    last_word=best,
                    intent=s.intent,
                    query_tags=s.query_tags,
                    overlay_text=s.overlay_text,
                )
                b = PlannedScene(
                    section=s.section,
                    first_word=best + 1,
                    last_word=s.last_word,
                    intent=s.intent,
                    query_tags=s.query_tags,
                    overlay_text=None,
                )
                stack = [a, b] + stack
            else:
                out.append(s)
        return out

    def merge_short(items: list[PlannedScene]) -> list[PlannedScene]:
        """Merge scenes shorter than smin into the neighbour that stays shortest (prev or next)."""
        items = [PlannedScene(**x.model_dump()) for x in items]
        changed = True
        while changed and len(items) > 1:
            changed = False
            for idx, s in enumerate(items):
                if dur_of(s) >= smin:
                    continue
                prev = items[idx - 1] if idx > 0 else None
                nxt = items[idx + 1] if idx + 1 < len(items) else None
                prev_d = (words[s.last_word].end - words[prev.first_word].start) if prev else float("inf")
                next_d = (words[nxt.last_word].end - words[s.first_word].start) if nxt else float("inf")
                if prev is not None and (nxt is None or prev_d <= next_d):
                    prev.last_word = s.last_word
                    prev.overlay_text = prev.overlay_text or s.overlay_text
                    prev.query_tags = list(dict.fromkeys(prev.query_tags + s.query_tags))[:6]
                else:
                    nxt.first_word = s.first_word
                    nxt.overlay_text = s.overlay_text or nxt.overlay_text
                    nxt.section = s.section if idx == 0 else nxt.section
                    nxt.query_tags = list(dict.fromkeys(s.query_tags + nxt.query_tags))[:6]
                del items[idx]
                changed = True
                break
        return items

    # 2)+3) split → merge → split again (merging can create over-long shots), bounded rounds
    merged = split_long(fixed)
    for _ in range(3):
        before = [(x.first_word, x.last_word) for x in merged]
        merged = split_long(merge_short(merged))
        if [(x.first_word, x.last_word) for x in merged] == before:
            break

    # 4) to times
    end_total = max(voice_duration + _TAIL_PAD, words[-1].end + 0.05)
    scenes: list[NormalizedScene] = []
    for i, s in enumerate(merged):
        start = 0.0 if i == 0 else scenes[-1].end
        end = end_total if i == len(merged) - 1 else round((words[s.last_word].end + words[s.last_word + 1].start) / 2, 3)
        scenes.append(
            NormalizedScene(
                order=i + 1,
                section=s.section,
                start=round(start, 3),
                end=round(end, 3),
                first_word=s.first_word,
                last_word=s.last_word,
                intent=s.intent,
                query_tags=s.query_tags or ["desk"],
                overlay_text=_clean_overlay(s.overlay_text),
            )
        )

    # 5) cap overlays to template.max (keep earliest / hook & last payoff first)
    max_ov = int(template.overlays.max)
    with_ov = [s for s in scenes if s.overlay_text]
    if len(with_ov) > max_ov:
        keep = set()
        keep.add(with_ov[0].order)
        keep.add(with_ov[-1].order)
        for s in with_ov:
            if len(keep) >= max_ov:
                break
            keep.add(s.order)
        for s in scenes:
            if s.overlay_text and s.order not in keep:
                s.overlay_text = None
    return scenes


def _clean_overlay(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"\s+", " ", text).strip()
    words = t.split()
    if len(words) > 6:
        t = " ".join(words[:6])
    return t or None
