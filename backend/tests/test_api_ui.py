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
    from tests.conftest import enable_sqlite_fk
    enable_sqlite_fk(engine)
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


def test_upload_single_video_creates_asset_file_and_row(client, mini_assets, tmp_path):
    from tests.conftest import make_clip
    clip = make_clip(tmp_path / "new.mp4", seconds=3)
    with clip.open("rb") as f:
        r = client.post("/assets/upload", data={"category": "desk", "description": "hand closes notebook", "tags": "notebook, hand", "approved": "true"},
                        files={"file": ("My Clip (1).mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["file"] == "desk/my_clip_1.mp4" and a["approved"] is True and a["duration"] > 2.5
    assert "notebook" in a["tags"] and a["description"] == "hand closes notebook"
    assert (mini_assets / "desk" / "my_clip_1.mp4").is_file()
    assert a["id"] == "asset_007"
    # same name again → does not overwrite, gets a suffix
    with clip.open("rb") as f:
        r2 = client.post("/assets/upload", data={"category": "desk"}, files={"file": ("My Clip (1).mp4", f, "video/mp4")})
    assert r2.status_code == 201 and r2.json()["file"] == "desk/my_clip_1_2.mp4" and r2.json()["approved"] is False


def test_upload_rejects_non_video_and_bad_category(client, tmp_path):
    txt = tmp_path / "x.txt"; txt.write_text("hi")
    with txt.open("rb") as f:
        assert client.post("/assets/upload", data={"category": "desk"}, files={"file": ("x.txt", f, "text/plain")}).status_code == 400
    from tests.conftest import make_clip
    clip = make_clip(tmp_path / "c.mp4", seconds=2)
    with clip.open("rb") as f:
        assert client.post("/assets/upload", data={"category": "../etc"}, files={"file": ("c.mp4", f, "video/mp4")}).status_code == 400


def test_delete_asset_removes_row_and_file(client, mini_assets):
    assert (mini_assets / "desk" / "typing_01.mp4").is_file()
    r = client.delete("/assets/asset_001")
    assert r.status_code == 204
    assert client.get("/assets/asset_001/file").status_code == 404
    assert not (mini_assets / "desk" / "typing_01.mp4").exists()
    assert client.delete("/assets/asset_001").status_code == 404
    # keep_file=true keeps the file on disk but removes the library entry
    r = client.delete("/assets/asset_002?keep_file=true")
    assert r.status_code == 204 and (mini_assets / "desk" / "coffee_pour_01.mp4").is_file()


def test_upload_accepts_usable_range_and_clamps(client, tmp_path):
    from tests.conftest import make_clip
    clip = make_clip(tmp_path / "r.mp4", seconds=4)
    with clip.open("rb") as f:
        r = client.post("/assets/upload", data={"category": "desk", "usable_start": "0.8", "usable_end": "9.9"},
                        files={"file": ("r.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["usable_start"] == 0.8 and abs(a["usable_end"] - a["duration"]) < 0.05  # end clamped to duration


def test_delete_asset_that_was_used_in_a_render(client, mini_assets, tmp_path):
    # simulate usage bookkeeping (normally written after a successful render)
    from app.models import AssetUsage
    factory = client.app.state.session_factory
    with factory() as s:
        s.add(AssetUsage(asset_id="asset_003", project_id="proj_x", render_id="render_x"))
        s.commit()
    r = client.delete("/assets/asset_003")
    assert r.status_code == 204, r.text
    assert client.get("/assets/search?q=trackpad").status_code == 200
