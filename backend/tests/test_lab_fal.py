"""fal.ai multi-model video provider (stubbed fal_client) + per-video provider selection."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.lab.providers import FAL_MODELS, FalVideoGen, get_video_gen, list_video_providers, FakeImageGen, FakePlanner, FakeVideoGen
from app.lab.service import LabService
from tests.conftest import make_clip


@pytest.fixture()
def fal_stub(monkeypatch, tmp_path):
    """Stub fal_client: records calls, returns a tiny mp4 URL served from disk."""
    import app.lab.providers as P

    calls = {"uploads": [], "subscribe": []}
    clip = make_clip(tmp_path / "fal_out.mp4", seconds=3, size="720x1280")

    class StubClient:
        @staticmethod
        def upload_file(path, **kw):
            calls["uploads"].append(str(path))
            return f"https://fal.media/files/{Path(path).name}"

        @staticmethod
        def subscribe(application, arguments, **kw):
            calls["subscribe"].append((application, arguments))
            return {"video": {"url": f"file://{clip}"}, "seed": 1}

    monkeypatch.setattr(P, "_fal", lambda: StubClient)
    monkeypatch.setattr(P, "_download", lambda url, dst: Path(dst).write_bytes(Path(url.replace("file://", "")).read_bytes()))
    monkeypatch.setenv("FAL_KEY", "test")
    from app.config.settings import get_settings
    get_settings.cache_clear()
    yield calls
    get_settings.cache_clear()


def test_registry_has_expected_models():
    assert {"minimax-h3", "seedance-2.0", "seedance-2.0-fast", "kling-3.0-std"} <= set(FAL_MODELS)
    assert FAL_MODELS["minimax-h3"]["endpoint"] == "minimax/h3/image-to-video"
    assert FAL_MODELS["seedance-2.0"]["max_seconds"] == 15 and FAL_MODELS["kling-3.0-std"]["max_seconds"] == 15


@pytest.mark.parametrize("key,first_key,last_key,extra", [
    ("minimax-h3", "image_url", "end_image_url", {"resolution": "2K", "duration": 8}),
    ("seedance-2.0", "image_url", "end_image_url", {"aspect_ratio": "9:16", "duration": "8", "resolution": "720p"}),
    ("seedance-2.0-fast", "image_url", "end_image_url", {"aspect_ratio": "9:16", "duration": "8"}),
    ("kling-3.0-std", "start_image_url", "end_image_url", {"duration": "8"}),
])
def test_fal_animate_builds_arguments_and_normalizes(fal_stub, tmp_path, key, first_key, last_key, extra):
    first = make_clip(tmp_path / "a.mp4", seconds=1)  # any file works for the stub uploader
    last = make_clip(tmp_path / "b.mp4", seconds=1)
    gen = FalVideoGen(key)
    assert gen.name == "fal" and gen.model == FAL_MODELS[key]["endpoint"] and gen.max_seconds == FAL_MODELS[key]["max_seconds"]
    out = gen.animate(first=first, last=last, prompt="slow push in", seconds=8, out_path=tmp_path / "seg.mp4")
    assert out.is_file()
    from app.assets.metadata import probe_video
    meta = probe_video(out)
    assert (meta.width, meta.height) == (1080, 1920)
    app_id, args = fal_stub["subscribe"][-1]
    assert app_id == FAL_MODELS[key]["endpoint"]
    assert args[first_key].startswith("https://fal.media/") and args[last_key].startswith("https://fal.media/")
    assert args["prompt"] == "slow push in"
    for k, v in extra.items():
        assert args[k] == v, (k, args)
    with pytest.raises(NotImplementedError):
        gen.edit(ref="x", instruction="y", out_path=tmp_path / "e.mp4")


def test_get_video_gen_parses_fal_keys(fal_stub):
    assert get_video_gen("fal:seedance-2.0").model == FAL_MODELS["seedance-2.0"]["endpoint"]
    assert get_video_gen("fal").model == FAL_MODELS["minimax-h3"]["endpoint"]  # default fal model
    assert get_video_gen("fake").name == "fake"
    with pytest.raises(ValueError):
        get_video_gen("fal:nope")


def test_list_video_providers_reports_availability(monkeypatch):
    import app.lab.providers as P
    from app.config.settings import Settings
    monkeypatch.setattr(P, "get_settings", lambda: Settings(_env_file=None, google_api_key=None, fal_key=None))
    rows = {r["id"]: r for r in list_video_providers()}
    assert {"omni", "veo", "fake", "fal:minimax-h3", "fal:seedance-2.0"} <= set(rows)
    assert rows["omni"]["supports_edit"] is True and rows["fal:minimax-h3"]["supports_edit"] is False
    assert rows["fal:minimax-h3"]["available"] is False and rows["omni"]["available"] is False and rows["fake"]["available"] is True
    assert rows["fal:seedance-2.0"]["max_seconds"] == 15 and rows["fal:seedance-2.0"]["label"]


def test_service_uses_per_video_provider(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    svc = LabService(s, image=FakeImageGen(), planner=FakePlanner(), storage_dir=tmp_path / "storage",
                     video_factory=lambda name: _named_fake(name))
    v = svc.create(prompt="A quiet cafe morning", target_duration=20, video_provider="fake:alpha")
    assert v.video_provider == "fake:alpha" and v.video_model == "alpha-model"
    assert (v.n_segments, v.segment_seconds) == (2, 10)  # alpha max 10
    svc.run_to_images(v.id); svc.animate(v.id)
    assert svc.get(v.id).status == "DONE"
    c = svc.clone(v.id, video_provider="fake:beta")  # beta max 8 → 20 s → 3×7 → re-plan
    assert c.video_provider == "fake:beta" and c.video_model == "beta-model" and c.status == "PLANNING"


def _named_fake(name: str):
    g = FakeVideoGen()
    tag = name.split(":", 1)[1] if ":" in name else name
    g.model = f"{tag}-model"
    g.max_seconds = 10 if tag == "alpha" else 8
    return g
