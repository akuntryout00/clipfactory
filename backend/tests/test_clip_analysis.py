from pathlib import Path

from app.assets.frames import extract_frames
from app.llm import prompts
from app.llm.fake import FakeLLM
from app.schemas.pipeline import ClipAnalysis

from tests.conftest import make_clip


def test_extract_frames_returns_n_jpegs(tmp_path: Path):
    clip = make_clip(tmp_path / "c.mp4", seconds=4, color="red")
    frames = extract_frames(clip, n=5, width=256)
    assert len(frames) == 5
    assert all(f[:3] == b"\xff\xd8\xff" for f in frames)  # JPEG magic


def test_fake_llm_analyze_clip_returns_full_metadata():
    out = FakeLLM().analyze_clip(frames=[b"x"], filename="phone/phone_scroll_09.mp4", duration=5.0, categories=["desk", "phone"])
    assert isinstance(out, ClipAnalysis)
    assert out.description and len(out.tags) >= 3 and out.action and out.location and out.shot in ("close", "medium", "wide")
    assert out.mood and out.suggested_category in ("desk", "phone")


def test_analyze_prompt_mentions_categories_and_rules():
    txt = prompts.analyze_user_prompt("clip.mp4", 5.2, ["desk", "phone"], n_frames=6)
    assert "desk" in txt and "6 frames" in txt and "5.2" in txt
