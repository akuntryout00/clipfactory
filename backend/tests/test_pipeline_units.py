import json
from pathlib import Path
import random

import pytest

from app.schemas.pipeline import (
    ScriptOutput, ScriptSection, WordTiming, VideoJSON, VideoJSONScene, ScenePlanOutput, PlannedScene,
)
from app.content.script_generator import target_word_range, words_of
from app.voice.alignment import chars_to_words
from app.content.scene_planner import (
    section_word_ranges, normalize_plan, heuristic_plan,
)
from app.config.loaders import load_template, load_persona
from app.llm.fake import FakeLLM


# ---------- schemas ----------

def test_video_json_rejects_non_contiguous_scenes():
    data = {
        "version": "1.0", "persona": "p", "template": "story_v1", "topic": "t",
        "voiceover": {"text": "hi", "audio": "v.mp3", "duration": 5.0},
        "scenes": [
            {"order": 1, "start": 0, "end": 2.0, "asset_id": "a", "asset_file": "a.mp4", "asset_start": 0.0, "text": None},
            {"order": 2, "start": 2.5, "end": 5.0, "asset_id": "b", "asset_file": "b.mp4", "asset_start": 0.0, "text": None},
        ],
        "caption_style": "dynamic_center", "music": None, "captions": [], "seed": 1,
    }
    with pytest.raises(ValueError):
        VideoJSON.model_validate(data)


def test_video_json_accepts_valid_plan_and_roundtrips():
    data = {
        "version": "1.0", "persona": "p", "template": "story_v1", "topic": "t",
        "voiceover": {"text": "hi there", "audio": "v.mp3", "duration": 5.0},
        "scenes": [
            {"order": 1, "start": 0, "end": 2.0, "asset_id": "a", "asset_file": "a.mp4", "asset_start": 0.3, "text": "HI"},
            {"order": 2, "start": 2.0, "end": 5.0, "asset_id": "b", "asset_file": "b.mp4", "asset_start": 0.0, "text": None},
        ],
        "caption_style": "dynamic_center", "music": None,
        "captions": [{"start": 0.0, "end": 1.0, "text": "hi there", "emphasis_index": 1}], "seed": 1,
    }
    vj = VideoJSON.model_validate(data)
    assert vj.total_duration == 5.0
    assert VideoJSON.model_validate_json(vj.model_dump_json()).scenes[0].text == "HI"


# ---------- script ----------

@pytest.mark.parametrize("dur,lo,hi", [(15, 33, 45), (20, 45, 60), (25, 58, 72)])
def test_target_word_range_tracks_prd_table(dur, lo, hi):
    a, b = target_word_range(dur)
    assert lo - 3 <= a <= lo + 3
    assert hi - 3 <= b <= hi + 3


def test_script_full_text_joins_sections():
    s = ScriptOutput(hook="Stop doing this.", sections=[
        ScriptSection(type="hook", text="Stop doing this."),
        ScriptSection(type="setup", text="You type notes, you miss things."),
    ])
    assert s.full_text == "Stop doing this. You type notes, you miss things."
    assert words_of(s.full_text) == ["Stop", "doing", "this.", "You", "type", "notes,", "you", "miss", "things."]


def test_fake_llm_generates_script_for_every_template():
    llm = FakeLLM()
    persona = load_persona("young_professional")
    for t in ("story_v1", "list_v1", "pov_v1", "problem_solution_v1"):
        tpl = load_template(t)
        s = llm.generate_script(persona=persona, template=tpl, topic="Stop taking meeting notes manually", target_duration=18)
        assert [sec.type for sec in s.sections] == [sec.type for sec in tpl.sections]
        lo, hi = target_word_range(18)
        assert lo - 10 <= len(words_of(s.full_text)) <= hi + 10


def test_fake_llm_shorten_reduces_words():
    llm = FakeLLM()
    persona = load_persona("young_professional")
    tpl = load_template("story_v1")
    s = llm.generate_script(persona=persona, template=tpl, topic="x", target_duration=25)
    shorter = llm.shorten_script(persona=persona, template=tpl, script=s, target_words=30, reason="too long")
    assert len(words_of(shorter.full_text)) < len(words_of(s.full_text))


# ---------- alignment ----------

def test_chars_to_words_groups_characters_into_words():
    text = "Stop it. Now go"
    chars = list(text)
    starts = [i * 0.1 for i in range(len(chars))]
    ends = [s + 0.1 for s in starts]
    words = chars_to_words(chars, starts, ends)
    assert [w.word for w in words] == ["Stop", "it.", "Now", "go"]
    assert words[0].start == pytest.approx(0.0) and words[0].end == pytest.approx(0.4)
    assert words[2].start == pytest.approx(0.9)
    assert all(w.end > w.start for w in words)


# ---------- scene planner ----------

def _words(text: str, wps: float = 2.5) -> list[WordTiming]:
    out, t = [], 0.0
    for w in text.split():
        out.append(WordTiming(word=w, start=round(t, 3), end=round(t + 1 / wps - 0.05, 3)))
        t += 1 / wps
    return out


def test_section_word_ranges_follow_script_sections():
    s = ScriptOutput(hook="a b", sections=[ScriptSection(type="hook", text="a b"), ScriptSection(type="setup", text="c d e")])
    words = _words(s.full_text)
    assert section_word_ranges(s, words) == {"hook": (0, 1), "setup": (2, 4)}


def test_normalize_plan_snaps_to_word_times_and_is_contiguous():
    text = " ".join(f"w{i}" for i in range(40))  # 16 s at 2.5 wps
    words = _words(text)
    tpl = load_template("story_v1")
    plan = ScenePlanOutput(scenes=[
        PlannedScene(section="hook", first_word=0, last_word=4, intent="x", query_tags=["a"], overlay_text="HOOK"),
        PlannedScene(section="setup", first_word=5, last_word=12, intent="y", query_tags=["b"], overlay_text=None),
        PlannedScene(section="development", first_word=13, last_word=24, intent="z", query_tags=["c"], overlay_text=None),
        PlannedScene(section="payoff", first_word=25, last_word=39, intent="q", query_tags=["d"], overlay_text="DONE"),
    ])
    scenes = normalize_plan(plan, words, tpl, voice_duration=16.0)
    assert scenes[0].start == 0.0
    assert 16.0 <= scenes[-1].end <= 16.5  # small tail pad after the last word
    for a, b in zip(scenes, scenes[1:]):
        assert a.end == pytest.approx(b.start)
    # each shot within template range (payoff 15 words = 6 s > 4 s max → split)
    assert all(tpl.shot_duration.min - 0.01 <= (s.end - s.start) for s in scenes)
    assert all((s.end - s.start) <= tpl.shot_duration.max * 1.3 for s in scenes)
    assert len(scenes) >= 5


def test_normalize_plan_merges_too_short_scenes_and_limits_overlays():
    words = _words(" ".join(f"w{i}" for i in range(20)))  # 8 s
    tpl = load_template("story_v1")  # overlays max 3
    plan = ScenePlanOutput(scenes=[
        PlannedScene(section="hook", first_word=0, last_word=0, intent="x", query_tags=["a"], overlay_text="A"),   # 0.4 s
        PlannedScene(section="setup", first_word=1, last_word=6, intent="y", query_tags=["b"], overlay_text="B"),
        PlannedScene(section="development", first_word=7, last_word=12, intent="z", query_tags=["c"], overlay_text="C"),
        PlannedScene(section="payoff", first_word=13, last_word=19, intent="q", query_tags=["d"], overlay_text="D"),
    ])
    scenes = normalize_plan(plan, words, tpl, voice_duration=8.0)
    assert all((s.end - s.start) >= tpl.shot_duration.min - 0.01 for s in scenes)
    assert sum(1 for s in scenes if s.overlay_text) <= 3


def test_heuristic_plan_produces_4_to_8_scenes_for_18s():
    words = _words(" ".join(f"w{i}." if i % 9 == 8 else f"w{i}" for i in range(45)))
    tpl = load_template("list_v1")
    s = ScriptOutput(hook="h", sections=[ScriptSection(type=sec.type, text=" ".join(w.word for w in words[i*9:(i+1)*9])) for i, sec in enumerate(tpl.sections)])
    plan = heuristic_plan(s, words, tpl)
    scenes = normalize_plan(plan, words, tpl, voice_duration=18.0)
    assert 4 <= len(scenes) <= 8
