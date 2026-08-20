from pathlib import Path

from app.captions.generator import build_caption_chunks, write_ass
from app.config.loaders import load_caption_style
from app.content.scene_planner import section_word_ranges
from app.schemas.pipeline import ScriptOutput, ScriptSection, WordTiming
from app.voice.normalize import speech_text


def _words(text: str, wps: float = 2.5) -> list[WordTiming]:
    out, t = [], 0.0
    for w in text.split():
        out.append(WordTiming(word=w, start=round(t, 3), end=round(t + 1 / wps - 0.05, 3)))
        t += 1 / wps
    return out


def test_speech_text_drops_pov_prefix_and_expands_abbreviations():
    assert speech_text("POV: you opened your laptop to check one thing.") == "you opened your laptop to check one thing."
    assert speech_text("POV you opened") == "you opened"
    assert speech_text("Slack vs. email & calendars, e.g. Monday") == "Slack versus email and calendars, for example Monday"
    assert speech_text("AI won't take your job") == "AI won't take your job"


def test_script_for_speech_keeps_sections_aligned_with_word_ranges():
    s = ScriptOutput(hook="POV: you opened your laptop.", sections=[
        ScriptSection(type="hook", text="POV: you opened your laptop."),
        ScriptSection(type="problem", text="Now twelve tabs are open."),
    ])
    spoken = s.for_speech()
    assert spoken.sections[0].text == "you opened your laptop."
    words = _words(spoken.full_text)
    assert section_word_ranges(spoken, words) == {"hook": (0, 3), "problem": (4, 8)}


def test_caption_chunks_never_exceed_two_lines_of_chars():
    style = load_caption_style("dynamic_center")
    words = _words("When I'm stuck, staring at the screen mostly creates premium-grade procrastination. Walking removes the tabs, notifications, and pressure to look busy.")
    chunks = build_caption_chunks(words, style)
    limit = style.max_chars_per_line * style.max_lines
    for c in chunks:
        assert len(c.text) <= limit or len(c.text.split()) == 1, c.text
    texts = [c.text for c in chunks]
    assert "premium-grade procrastination." in texts or "premium-grade" in " ".join(texts)
    assert not any("creates premium-grade procrastination" in t for t in texts)


def test_write_ass_no_line_longer_than_max_chars_unless_single_word_and_shrinks_it(tmp_path: Path):
    style = load_caption_style("dynamic_center")
    words = _words("mostly creates premium-grade procrastination.")
    chunks = build_caption_chunks(words, style)
    out = write_ass(chunks, [], style, tmp_path / "c.ass")
    import re
    for line in out.read_text().splitlines():
        if not line.startswith("Dialogue: 0"):
            continue
        text = line.split(",", 9)[9]
        plain = re.sub(r"\{[^}]*\}", "", text)
        for part in plain.split("\\N"):
            assert len(part) <= style.max_chars_per_line or " " not in part, part
    # a single over-long word gets a scale-down tag
    words2 = _words("supercalifragilisticexpialidocious now")
    out2 = write_ass(build_caption_chunks(words2, style), [], style, tmp_path / "d.ass")
    assert "\\fscx" in [l for l in out2.read_text().splitlines() if "supercali" in l][0]
