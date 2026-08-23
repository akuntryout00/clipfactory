"""Trend analysis: fake downloader/transcriber/LLM → analysis + template proposal; API; template creation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from app.trends.service import TrendService, detect_platform


def fake_downloader(src_clip: Path):
    def _dl(url: str, dest: Path) -> dict:
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "source.mp4"
        shutil.copyfile(src_clip, f)
        return {"file": str(f), "title": "3 habits that waste your time", "uploader": "someone", "duration": 9.0, "view_count": 12345}

    return _dl


def test_detect_platform():
    assert detect_platform("https://www.tiktok.com/@x/video/1") == "tiktok"
    assert detect_platform("https://instagram.com/reel/abc") == "instagram"
    assert detect_platform("https://youtu.be/x") == "youtube"


def test_pipeline_and_template_draft(session, mini_assets, tmp_path):
    from app.llm.fake import FakeLLM

    clip = next((mini_assets / "desk").glob("*.mp4"))
    svc = TrendService(
        session,
        storage_dir=tmp_path / "st",
        llm=FakeLLM(),
        downloader=fake_downloader(clip),
        transcriber=lambda p: "Stop doing this. It wastes time.",
    )
    t = svc.create(url="https://www.tiktok.com/@x/video/123", persona_id="young_professional")
    assert t.platform == "tiktok" and t.status == "QUEUED"
    t = svc.run(t.id)
    assert t.status == "DONE" and t.title and t.duration == 9.0 and t.transcript and t.thumbnail_path
    a = t.analysis
    assert a["hook"]["text"].startswith("Stop doing this") and a["template_proposal"]["id"] == "trend_remix_v1"
    draft = TrendService.template_from_proposal(a)
    assert (
        abs(sum(s["weight"] for s in draft["sections"]) - 1.0) < 1e-6
        and draft["duration"]["min"] <= draft["duration"]["target"] <= draft["duration"]["max"]
    )
    assert [s["type"] for s in draft["sections"]] == ["hook", "body", "payoff"]
    with pytest.raises(ValueError):
        svc.create(url="not a url", persona_id=None)


@pytest.fixture()
def client(mini_assets, tmp_path):
    from app.api.main import create_app
    from app.assets.importer import import_assets
    from app.config.settings import REPO_DIR
    from app.db import Base
    from app.llm.fake import FakeLLM
    from app.projects.jobs import InlineJobRunner
    from app.voice.fake import FakeVoice
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from tests.conftest import enable_sqlite_fk

    cfg = tmp_path / "configs"
    shutil.copytree(REPO_DIR / "configs", cfg)
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False})
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        import_assets(s, mini_assets)
    clip = next((mini_assets / "desk").glob("*.mp4"))
    app = create_app(
        session_factory=factory,
        jobs=InlineJobRunner(),
        configs_dir=cfg,
        service_kwargs=dict(llm=FakeLLM(), voice=FakeVoice(), storage_dir=tmp_path / "storage", assets_dir=mini_assets),
        trend_kwargs=dict(downloader=fake_downloader(clip), transcriber=lambda p: "hello there"),
    )
    with TestClient(app) as c:
        yield c


def test_trends_api_and_template_creation(client):
    r = client.post("/trends", json={"url": "https://www.tiktok.com/@x/video/9", "persona_id": "young_professional"})
    assert r.status_code == 202, r.text
    tid = r.json()["id"]
    d = client.get(f"/trends/{tid}").json()
    assert d["status"] == "DONE" and d["analysis"]["summary"] and d["template_draft"]["id"] == "trend_remix_v1" and d["video_url"]
    assert client.get(d["thumbnail_url"]).status_code == 200
    assert client.get("/trends?persona=young_professional").json()[0]["id"] == tid
    # approve the draft (edited id) → template exists and is usable by the factory
    draft = d["template_draft"]
    draft["id"] = "trend_myth_v1"
    r = client.post(f"/trends/{tid}/template", json={"template": draft})
    assert r.status_code == 201, r.text
    assert any(t["id"] == "trend_myth_v1" for t in client.get("/templates").json())
    assert client.get(f"/trends/{tid}").json()["template_id"] == "trend_myth_v1"
    assert client.post(f"/trends/{tid}/template", json={"template": draft}).status_code == 409
    assert client.post("/trends", json={"url": "nope"}).status_code == 422
    assert client.delete(f"/trends/{tid}").status_code == 204


def test_one_off_video_from_trend(client, monkeypatch):
    from app.projects import service as service_mod

    monkeypatch.setattr(service_mod.ProjectService, "generate", lambda self, pid: None)  # inline runner: skip the real pipeline
    tid = client.post("/trends", json={"url": "https://www.tiktok.com/@x/video/77", "persona_id": "young_professional"}).json()["id"]
    r = client.post(f"/trends/{tid}/generate", json={"topic": "3 things I stopped doing before 9 AM", "target_duration": 18})
    assert r.status_code == 202, r.text
    p = r.json()
    assert p["template_id"].startswith("trend_") and p["template_override"]["sections"] and p["persona_id"] == "young_professional"
    # no template file was written; the project resolves its structure inline (caption style present = template resolved)
    assert not any(t["id"] == p["template_id"] for t in client.get("/templates").json())
    assert client.get(f"/projects/{p['id']}").json()["caption_style"]["font_size"] > 0
