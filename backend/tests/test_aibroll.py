"""AI B-roll: job pipeline with fake providers ends up as an approved library asset; API; persona photo."""

from __future__ import annotations

import io

import pytest
from app.aibroll.service import AiBrollService, estimate, persona_image_path, save_persona_image
from app.lab.providers import FakeImageGen, FakeVideoGen, clean_args
from app.models import Asset
from PIL import Image


def _png_bytes(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 600), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(mini_assets, tmp_path):
    """API client whose AI providers are all fake (never touches OpenAI/fal in tests)."""
    from app.api.main import create_app
    from app.assets.importer import import_assets
    from app.db import Base
    from app.lab.providers import FakePlanner
    from app.llm.fake import FakeLLM
    from app.projects.jobs import InlineJobRunner
    from app.voice.fake import FakeVoice
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from tests.conftest import enable_sqlite_fk

    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False})
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        import_assets(s, mini_assets)
    app = create_app(
        session_factory=factory,
        jobs=InlineJobRunner(),
        service_kwargs=dict(llm=FakeLLM(), voice=FakeVoice(), storage_dir=tmp_path / "storage", assets_dir=mini_assets),
        lab_kwargs=dict(image=FakeImageGen(), video=FakeVideoGen(), planner=FakePlanner(), storage_dir=tmp_path / "storage"),
    )
    with TestClient(app) as c:
        yield c


def test_clean_args_drops_none():
    assert clean_args({"image_url": "a", "end_image_url": None, "duration": 5}) == {"image_url": "a", "duration": 5}


def test_job_runs_and_lands_in_library(session, mini_assets, tmp_path):
    from app.assets.importer import import_assets
    from app.assets.shotlist import generate_shotlist
    from app.llm.fake import FakeLLM

    import_assets(session, mini_assets, default_persona="young_professional")
    generate_shotlist(session, FakeLLM(), "young_professional", target_count=8)
    from app.models import ShotlistItem

    item = session.query(ShotlistItem).first()
    svc = AiBrollService(session, storage_dir=tmp_path / "storage", assets_dir=mini_assets, image=FakeImageGen(), video=FakeVideoGen())
    j = svc.create(
        persona_id="young_professional",
        prompt="Hands typing on a laptop in a cafe",
        title="Typing",
        category="desk",
        shot="close",
        action="typing_laptop",
        tags=["laptop", "cafe"],
        seconds=4,
        video_provider="fake",
        shotlist_item_id=item.id,
    )
    assert j.status == "QUEUED" and j.seconds == 4 and j.reference_path is None
    j = svc.run(j.id)
    assert j.status == "DONE" and j.asset_id
    a = session.get(Asset, j.asset_id)
    assert a.persona_id == "young_professional" and a.approved and a.file.startswith("young_professional/desk/ai_")
    assert a.shotlist_item_id == item.id and "ai" in a.tags and a.action == "typing_laptop" and a.duration >= 3
    assert (mini_assets / a.file).is_file()


def test_reference_photo_flow(session, mini_assets, tmp_path):
    sd = tmp_path / "storage"
    save_persona_image(sd, "young_professional", _png_bytes())
    assert persona_image_path(sd, "young_professional").is_file()
    calls = {}

    class SpyImage(FakeImageGen):
        def generate(self, *, prompt, out_path, reference=None, identity=False, quality=None):
            calls.update(reference=reference, identity=identity, quality=quality)
            return super().generate(prompt=prompt, out_path=out_path)

    svc = AiBrollService(session, storage_dir=sd, assets_dir=mini_assets, image=SpyImage(), video=FakeVideoGen())
    j = svc.create(
        persona_id="young_professional", prompt="Smiling at the camera in a park", seconds=3, video_provider="fake", use_reference=True
    )
    assert j.reference_path and j.reference_path.endswith("reference.png")
    svc.run(j.id)
    assert calls["identity"] is True and calls["quality"] == "high" and calls["reference"] is not None
    # no photo → clear error
    try:
        svc.create(persona_id="nobody_here", prompt="anything at all", seconds=3, video_provider="fake", use_reference=True)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "no photo" in str(exc)


def test_estimate_and_api(client):  # noqa: F811
    e = estimate("fake", 5, with_reference=True)
    assert e["seconds"] == 5 and e["image_cost"] == 0.19 and e["total"] >= e["video_cost"]
    r = client.get("/ai-broll/providers")
    assert r.status_code == 200 and any(p["id"] == "fake" for p in r.json())
    r = client.get("/ai-broll/estimate?provider=fake&seconds=4")
    assert r.status_code == 200 and r.json()["seconds"] == 4
    r = client.put("/ai-broll/personas/young_professional/image", files={"file": ("me.png", _png_bytes(), "image/png")})
    assert r.status_code == 200
    assert client.get("/ai-broll/personas/young_professional/image/status").json()["has_image"] is True
    assert client.get("/ai-broll/personas/young_professional/image").status_code == 200
    r = client.post(
        "/ai-broll/jobs",
        data={
            "persona_id": "young_professional",
            "prompt": "Pouring coffee in a bright kitchen",
            "seconds": "3",
            "video_provider": "fake",
            "use_reference": "true",
            "category": "kitchen",
        },
    )
    assert r.status_code == 202, r.text
    j = r.json()
    assert j["use_reference"] is True and j["status"] in ("DONE", "QUEUED", "KEYFRAME", "ANIMATING", "IMPORTING")
    g = client.get(f"/ai-broll/jobs/{j['id']}").json()
    assert g["status"] == "DONE" and g["asset_id"] and g["video_url"]
    assert client.get(g["video_url"]).status_code == 200
    assert client.get("/ai-broll/jobs?persona=young_professional").json()[0]["id"] == j["id"]
    assert client.delete(f"/ai-broll/jobs/{j['id']}").status_code == 204
    assert client.delete("/ai-broll/personas/young_professional/image").status_code == 204
    assert client.post("/ai-broll/jobs", data={"persona_id": "x", "prompt": "too short?", "seconds": "99"}).status_code == 422
