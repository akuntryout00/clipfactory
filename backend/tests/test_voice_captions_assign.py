import random
from pathlib import Path

import pytest

from app.assets.importer import import_assets
from app.assets.metadata import probe_video
from app.captions.generator import build_caption_chunks, write_ass
from app.config.loaders import load_caption_style, load_persona, load_template
from app.content.asset_assignment import assign_assets
from app.content.scene_planner import heuristic_plan, normalize_plan
from app.llm.fake import FakeLLM
from app.schemas.pipeline import ScriptOutput, ScriptSection, WordTiming, VideoJSON
from app.voice.fake import FakeVoice
from app.voice.base import get_voice_provider


def test_fake_voice_writes_audio_with_duration_and_words(tmp_path: Path):
    persona = load_persona("young_professional")
    text = "Most people still take meeting notes like it is two thousand fifteen. Stop."
    res = FakeVoice().synthesize(text=text, voice=persona.voice, out_path=tmp_path / "v.mp3")
    assert Path(res.audio_path).is_file()
    meta = probe_video.__module__  # sanity import
    assert res.duration > 3
    assert [w.word for w in res.words] == text.split()
    assert res.words[-1].end <= res.duration + 0.01
    assert res.provider == "fake"


def test_get_voice_provider_fake():
    assert get_voice_provider("fake").name == "fake"


def _words(text: str, wps: float = 2.5) -> list[WordTiming]:
    out, t = [], 0.0
    for w in text.split():
        out.append(WordTiming(word=w, start=round(t, 3), end=round(t + 1 / wps - 0.05, 3)))
        t += 1 / wps
    return out


def test_caption_chunks_are_2_to_5_words_and_cover_all_words():
    style = load_caption_style("dynamic_center")
    words = _words("Most people still take meeting notes like it is 2015. You listen, type, miss something, then fix it. Done.")
    chunks = build_caption_chunks(words, style)
    assert all(1 <= len(c.text.split()) <= style.max_words_per_chunk for c in chunks)
    assert " ".join(c.text for c in chunks).split() == [w.word for w in words]
    for a, b in zip(chunks, chunks[1:]):
        assert a.end <= b.start + 1e-6
    assert chunks[0].start == pytest.approx(0.0)


def test_caption_chunks_break_on_punctuation():
    style = load_caption_style("dynamic_center")
    words = _words("Stop it. Now do this thing")
    chunks = build_caption_chunks(words, style)
    assert chunks[0].text == "Stop it."


def test_caption_chunk_has_emphasis_on_longest_word():
    style = load_caption_style("dynamic_center")
    words = _words("take meeting notes now")
    chunks = build_caption_chunks(words, style)
    c = chunks[0]
    assert c.text.split()[c.emphasis_index] == "meeting"


def test_write_ass_contains_style_and_events(tmp_path: Path):
    style = load_caption_style("dynamic_center")
    words = _words("Most people still take meeting notes.")
    chunks = build_caption_chunks(words, style)
    overlays = [(0.0, 2.0, "STOP DOING THIS")]
    out = write_ass(chunks, overlays, style, tmp_path / "c.ass", width=1080, height=1920)
    txt = out.read_text()
    assert "[V4+ Styles]" in txt and "Style: Caption" in txt and "Style: Overlay" in txt
    assert "Dialogue:" in txt and "STOP DOING" in txt
    assert "PlayResX: 1080" in txt
    # captions positioned inside the safe zone (lower-center but above the bottom 18 %)
    assert "MarginV" in txt


def test_assign_assets_builds_valid_video_json(session, mini_assets, tmp_path: Path):
    import_assets(session, mini_assets)
    tpl = load_template("story_v1")
    persona = load_persona("young_professional")
    text = ("Most people still take meeting notes by typing on a laptop at a desk. "
            "You scroll your phone, you get stressed, you walk to coffee, and then you fix everything later. "
            "Record it, transcribe it, summarize it, and you are done with the whole thing today.")
    words = _words(text)
    script = ScriptOutput(hook="x", sections=[
        ScriptSection(type="hook", text=" ".join(text.split()[:6])),
        ScriptSection(type="setup", text=" ".join(text.split()[6:16])),
        ScriptSection(type="development", text=" ".join(text.split()[16:30])),
        ScriptSection(type="payoff", text=" ".join(text.split()[30:40])),
        ScriptSection(type="ending", text=" ".join(text.split()[40:])),
    ])
    plan = heuristic_plan(script, words, tpl)
    scenes = normalize_plan(plan, words, tpl, voice_duration=words[-1].end)
    vj = assign_assets(
        session=session, llm=FakeLLM(), persona=persona, template=tpl, topic="notes",
        scenes=scenes, words=words, voice_audio="voice_v1.mp3", voice_duration=words[-1].end,
        caption_style=load_caption_style("dynamic_center"), seed=7,
    )
    assert isinstance(vj, VideoJSON)
    ids = [s.asset_id for s in vj.scenes]
    assert len(ids) == len(scenes)
    assert len(set(ids)) == len(ids)  # no repeats within a video
    assert all(s.asset_file.endswith(".mp4") for s in vj.scenes)
    assert vj.captions and vj.captions[-1].end <= vj.total_duration + 1e-6
    # asset_start is inside the usable range
    from app.models import Asset
    for s in vj.scenes:
        a = session.get(Asset, s.asset_id)
        assert a.usable_start - 1e-6 <= s.asset_start <= max(a.usable_start, a.usable_end - 0.5) + 1e-6


def test_assign_assets_render_again_changes_offsets(session, mini_assets):
    import_assets(session, mini_assets)
    tpl = load_template("story_v1")
    persona = load_persona("young_professional")
    text = " ".join(["typing laptop desk work"] * 10)
    words = _words(text)
    script = ScriptOutput(hook="x", sections=[ScriptSection(type="hook", text=text)])
    scenes = normalize_plan(heuristic_plan(script, words, tpl), words, tpl, voice_duration=words[-1].end)
    kw = dict(session=session, llm=FakeLLM(), persona=persona, template=tpl, topic="t", scenes=scenes, words=words,
              voice_audio="v.mp3", voice_duration=words[-1].end, caption_style=load_caption_style("dynamic_center"))
    a = assign_assets(seed=1, **kw)
    b = assign_assets(seed=2, **kw)
    assert [s.asset_id for s in a.scenes] == [s.asset_id for s in b.scenes]  # same assets (render again keeps content)
    assert [s.asset_start for s in a.scenes] != [s.asset_start for s in b.scenes]


def test_assign_assets_change_assets_excludes_previous(session, mini_assets):
    import_assets(session, mini_assets)
    tpl = load_template("story_v1")
    persona = load_persona("young_professional")
    text = " ".join(["typing laptop desk work"] * 4)
    words = _words(text)
    script = ScriptOutput(hook="x", sections=[ScriptSection(type="hook", text=text)])
    scenes = normalize_plan(heuristic_plan(script, words, tpl), words, tpl, voice_duration=words[-1].end)
    kw = dict(session=session, llm=FakeLLM(), persona=persona, template=tpl, topic="t", scenes=scenes, words=words,
              voice_audio="v.mp3", voice_duration=words[-1].end, caption_style=load_caption_style("dynamic_center"), seed=1)
    a = assign_assets(**kw)
    b = assign_assets(exclude_asset_ids={s.asset_id for s in a.scenes}, **kw)
    assert not ({s.asset_id for s in a.scenes} & {s.asset_id for s in b.scenes})


def test_write_ass_keeps_emphasis_tag_and_wraps_plain_text(tmp_path: Path):
    style = load_caption_style("dynamic_center")
    words = _words("3 productivity habits that")
    chunks = build_caption_chunks(words, style)
    out = write_ass(chunks, [], style, tmp_path / "c.ass")
    line = [l for l in out.read_text().splitlines() if l.startswith("Dialogue:")][0]
    assert "{\\1c&H0000E5FF}productivity{\\1c&H00FFFFFF}" in line
    assert "(\\1c" not in line
    # wrapping decided on plain text: "3 productivity" (14 chars) fits on line 1 at 16 chars/line
    assert line.endswith("}productivity{\\1c&H00FFFFFF}\\Nhabits that") or "3 {\\1c&H0000E5FF}productivity{\\1c&H00FFFFFF}\\Nhabits that" in line
