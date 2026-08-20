from pathlib import Path

import pytest

from app.assets.importer import import_assets
from app.assets.metadata import probe_video
from app.config.loaders import load_caption_style, load_persona
from app.models import Asset
from app.renderer.ffmpeg import render_video, RenderOptions, ffmpeg_has_filter
from app.renderer.qc import run_qc
from app.schemas.pipeline import CaptionChunk, VideoJSON, VideoJSONScene, VoiceoverSpec
from app.voice.fake import FakeVoice
from tests.conftest import make_clip


def _video_json(session, voice_audio: str, duration: float) -> VideoJSON:
    assets = session.query(Asset).order_by(Asset.id).all()
    n = 4
    step = duration / n
    scenes = []
    for i in range(n):
        a = assets[i % len(assets)]
        scenes.append(VideoJSONScene(order=i + 1, start=round(i * step, 3), end=round((i + 1) * step, 3) if i < n - 1 else duration,
                                     asset_id=a.id, asset_file=a.file, asset_start=0.5, text="BIG TEXT" if i in (0, 2) else None))
    captions = [CaptionChunk(start=0.2, end=2.0, text="Most people", emphasis_index=1),
                CaptionChunk(start=2.0, end=4.0, text="still take notes", emphasis_index=2)]
    return VideoJSON(persona="young_professional", template="story_v1", topic="t",
                     voiceover=VoiceoverSpec(text="Most people still take notes", audio=voice_audio, duration=duration - 0.3),
                     scenes=scenes, captions=captions, seed=3)


needs_libass = pytest.mark.skipif(not ffmpeg_has_filter("ass"), reason="local ffmpeg lacks libass; runs in Docker")


@pytest.fixture()
def rendered(session, mini_assets, tmp_path):
    import_assets(session, mini_assets)
    persona = load_persona("young_professional")
    voice = FakeVoice().synthesize(text=" ".join(["word"] * 30), voice=persona.voice, out_path=tmp_path / "voice.mp3")
    vj = _video_json(session, voice.audio_path, duration=round(voice.duration + 0.3, 2))
    out = tmp_path / "final.mp4"
    result = render_video(vj, assets_dir=mini_assets, voice_path=Path(voice.audio_path), out_path=out,
                          style=load_caption_style("dynamic_center"), work_dir=tmp_path / "work",
                          options=RenderOptions(preset="ultrafast", crf=30))
    return vj, out, result


@needs_libass
def test_render_produces_1080x1920_30fps_h264_aac(rendered):
    vj, out, result = rendered
    assert out.is_file() and result.output_path == str(out)
    meta = probe_video(out)
    assert (meta.width, meta.height) == (1080, 1920)
    assert abs(meta.fps - 30) < 0.01
    assert meta.codec == "h264"
    assert meta.has_audio
    assert abs(meta.duration - vj.total_duration) < 0.35


@needs_libass
def test_qc_passes_on_good_render(rendered):
    _, out, _ = rendered
    qc = run_qc(out)
    assert qc["passed"], qc


def test_qc_fails_on_missing_or_short_file(tmp_path):
    qc = run_qc(tmp_path / "nope.mp4")
    assert not qc["passed"] and "missing" in " ".join(qc["failures"])
    short = make_clip(tmp_path / "short.mp4", seconds=2, size="1080x1920")
    qc2 = run_qc(short)
    assert not qc2["passed"]
    assert any("duration" in f for f in qc2["failures"]) and any("audio" in f for f in qc2["failures"])


@needs_libass
def test_render_with_music_mixes_and_ducks(session, mini_assets, tmp_path):
    import_assets(session, mini_assets)
    persona = load_persona("young_professional")
    voice = FakeVoice().synthesize(text=" ".join(["word"] * 30), voice=persona.voice, out_path=tmp_path / "voice.mp3")
    # fake music: 3 s tone that must be looped to cover the video
    import subprocess
    music = tmp_path / "upbeat_01.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:a", "libmp3lame", str(music)], check=True)
    vj = _video_json(session, voice.audio_path, duration=round(voice.duration + 0.3, 2))
    out = tmp_path / "final.mp4"
    render_video(vj, assets_dir=mini_assets, voice_path=Path(voice.audio_path), out_path=out,
                 style=load_caption_style("dynamic_center"), work_dir=tmp_path / "work", music_path=music,
                 options=RenderOptions(preset="ultrafast", crf=30))
    meta = probe_video(out)
    assert meta.has_audio and abs(meta.duration - vj.total_duration) < 0.35
