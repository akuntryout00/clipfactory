import pytest
from app.api.main import create_app
from app.assets.importer import import_assets
from app.db import Base
from app.llm.fake import FakeLLM
from app.projects.jobs import InlineJobRunner
from app.renderer.ffmpeg import ffmpeg_has_filter
from app.voice.fake import FakeVoice
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

needs_libass = pytest.mark.skipif(not ffmpeg_has_filter("ass"), reason="local ffmpeg lacks libass; runs in Docker")


@pytest.fixture()
def client(mini_assets, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        import_assets(s, mini_assets)
    app = create_app(
        session_factory=factory,
        jobs=InlineJobRunner(),
        service_kwargs=dict(
            llm=FakeLLM(),
            voice=FakeVoice(),
            storage_dir=tmp_path / "storage",
            assets_dir=mini_assets,
            render_preset="ultrafast",
            render_crf=30,
        ),
    )
    with TestClient(app) as c:
        yield c


def test_health_and_templates(client):
    assert client.get("/health").json()["status"] == "ok"
    ids = {t["id"] for t in client.get("/templates").json()}
    assert ids >= {"story_v1", "list_v1", "pov_v1", "problem_solution_v1"}  # user-made templates may exist too
    assert {p["id"] for p in client.get("/personas").json()} >= {"indie_maker", "young_professional"}


def test_assets_list_patch_and_search(client):
    items = client.get("/assets").json()
    assert len(items) == 6 and items[0]["id"] == "asset_001"
    r = client.patch("/assets/asset_001", json={"mood": "focused", "quality_score": 0.95, "tags": ["typing", "laptop", "desk", "focus"]})
    assert r.status_code == 200 and r.json()["mood"] == "focused"
    res = client.get("/assets/search", params={"q": "typing desk close"}).json()
    assert res[0]["asset_id"] == "asset_001"


def test_assets_import_endpoint(client):
    r = client.post("/assets/import")
    assert r.status_code == 200 and r.json()["updated"] == 6


def test_create_and_get_project(client):
    r = client.post("/projects", json={"topic": "Stop taking meeting notes manually", "template_id": "story_v1"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    g = client.get(f"/projects/{pid}").json()
    assert g["status"] == "DRAFT" and g["template_id"] == "story_v1" and g["target_duration"] == 18
    assert client.get("/projects").json()[0]["id"] == pid
    assert client.get("/projects/nope").status_code == 404


def test_create_project_validation(client):
    assert client.post("/projects", json={"topic": "", "template_id": "story_v1"}).status_code == 422
    assert client.post("/projects", json={"topic": "Real topic", "template_id": "story_v1", "target_duration": 60}).status_code == 422
    assert client.post("/projects", json={"topic": "Real topic", "template_id": "nope"}).status_code == 404


def test_approve_requires_ready(client):
    pid = client.post("/projects", json={"topic": "Real topic", "template_id": "story_v1"}).json()["id"]
    assert client.post(f"/projects/{pid}/approve").status_code == 409


@needs_libass
def test_generate_flow_via_api(client):
    pid = client.post("/projects", json={"topic": "Stop taking meeting notes manually", "template_id": "list_v1"}).json()["id"]
    r = client.post(f"/projects/{pid}/generate")
    assert r.status_code == 202
    g = client.get(f"/projects/{pid}").json()
    assert g["status"] == "READY", g
    assert g["render_version"] == 1 and len(g["scenes"]) >= 4
    v = client.get(f"/projects/{pid}/video")
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4"
    plan = client.get(f"/projects/{pid}/plan").json()
    assert plan["version"] == "1.0"
    sugg = client.get(f"/projects/{pid}/scenes/1/suggestions").json()
    assert sugg
    r = client.post(f"/projects/{pid}/scenes/1/asset", json={"asset_id": sugg[0]["asset_id"]})
    assert r.status_code == 202
    assert client.post(f"/projects/{pid}/change-assets").status_code == 202
    assert client.post(f"/projects/{pid}/render").status_code == 202
    assert client.post(f"/projects/{pid}/approve").status_code == 200
    assert client.get(f"/projects/{pid}").json()["status"] == "APPROVED"
