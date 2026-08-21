"""Endpoints added for the web UI: media streaming, thumbnails, artifacts, system, delete."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.assets.importer import import_assets
from app.db import Base
from app.llm.fake import FakeLLM
from app.projects.jobs import InlineJobRunner
from app.renderer.ffmpeg import ffmpeg_has_filter
from app.voice.fake import FakeVoice

needs_libass = pytest.mark.skipif(not ffmpeg_has_filter("ass"), reason="local ffmpeg lacks libass; runs in Docker")


@pytest.fixture()
def client(mini_assets, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        import_assets(s, mini_assets)
    app = create_app(session_factory=factory, jobs=InlineJobRunner(),
                     service_kwargs=dict(llm=FakeLLM(), voice=FakeVoice(), storage_dir=tmp_path / "storage",
                                         assets_dir=mini_assets, render_preset="ultrafast", render_crf=30))
    with TestClient(app) as c:
        yield c


def test_cors_headers_present(client):
    r = client.options("/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") in ("*", "http://localhost:3000")


def test_asset_file_streams_video_with_range(client):
    r = client.get("/assets/asset_001/file", headers={"Range": "bytes=0-99"})
    assert r.status_code in (200, 206)
    assert r.headers["content-type"].startswith("video/")
    assert client.get("/assets/nope/file").status_code == 404


def test_asset_thumbnail_is_generated_and_cached(client, tmp_path):
    r = client.get("/assets/asset_001/thumbnail")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and len(r.content) > 500
    r2 = client.get("/assets/asset_001/thumbnail")
    assert r2.content == r.content


def test_assets_enrich_endpoint(client):
    r = client.post("/assets/enrich")
    assert r.status_code == 200 and r.json()["enriched"] == 6


def test_system_endpoint_reports_providers_and_render(client):
    d = client.get("/system").json()
    assert d["llm_provider"] == "fake" and d["voice_provider"] == "fake"
    assert "render_ok" in d and "assets_count" in d and d["assets_count"] == 6
    assert "ffmpeg" in d


def test_project_artifacts_voice_and_delete(client):
    pid = client.post("/projects", json={"topic": "Stop taking meeting notes manually", "template_id": "story_v1"}).json()["id"]
    assert client.get(f"/projects/{pid}/artifacts").json() == {"scripts": [], "voices": [], "plans": [], "renders": []}
    assert client.get(f"/projects/{pid}/voice").status_code == 404
    r = client.delete(f"/projects/{pid}")
    assert r.status_code == 204
    assert client.get(f"/projects/{pid}").status_code == 404


@needs_libass
def test_artifacts_and_media_after_generate(client):
    pid = client.post("/projects", json={"topic": "Stop taking meeting notes manually", "template_id": "story_v1"}).json()["id"]
    assert client.post(f"/projects/{pid}/generate").status_code == 202
    art = client.get(f"/projects/{pid}/artifacts").json()
    assert art["scripts"][0]["version"] == 1 and "hook" in art["scripts"][0]["content"]
    assert art["voices"][0]["duration"] > 0 and art["plans"][0]["scenes"]
    assert art["renders"][0]["qc"]["passed"]
    v = client.get(f"/projects/{pid}/voice")
    assert v.status_code == 200 and v.headers["content-type"].startswith("audio/")
    rv = client.get(f"/projects/{pid}/renders/1/video")
    assert rv.status_code == 200 and rv.headers["content-type"] == "video/mp4"
