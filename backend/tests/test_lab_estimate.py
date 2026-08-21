import pytest
from app.db import Base
from app.lab.planning import segment_plan
from app.lab.pricing import estimate_cost
from app.lab.providers import FAL_MODELS, FakeImageGen, FakePlanner, FakeVideoGen, list_video_providers
from app.lab.service import LabService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.mark.parametrize(
    "dur,max_seg,min_seg,expected",
    [
        (3, 10, 2, (1, 3)),  # short video → one clip, two keyframes
        (3, 10, 5, (1, 5)),  # provider min 5 s → clip stretched to 5 s
        (8, 10, 4, (1, 8)),
        (12, 10, 4, (2, 6)),
        (20, 10, 4, (2, 10)),
        (25, 10, 4, (3, 8)),
        (25, 15, 4, (3, 8)),  # preferred granularity caps clips at 10 s even if the model allows 15
        (15, 8, 4, (2, 8)),
    ],
)
def test_segment_plan_supports_single_segment_and_min_seconds(dur, max_seg, min_seg, expected):
    assert segment_plan(dur, max_seg=max_seg, min_seg=min_seg) == expected


def test_registry_gains_seedance_25_1080p_and_kling_pro():
    assert {"seedance-2.5", "seedance-2.0-1080p", "kling-3.0-pro"} <= set(FAL_MODELS)
    assert FAL_MODELS["seedance-2.5"]["endpoint"] == "bytedance/seedance-2.5/image-to-video"
    a = FAL_MODELS["seedance-2.5"]["args"]("u1", "u2", "p", 10)
    assert a["duration"] == "10" and a["aspect_ratio"] == "9:16" and a["end_image_url"] == "u2"
    assert FAL_MODELS["seedance-2.0-1080p"]["args"]("u1", "u2", "p", 8)["resolution"] == "1080p"
    assert all("price_per_second" in spec and spec["price_per_second"] > 0 for spec in FAL_MODELS.values())


def test_providers_list_includes_numeric_prices_and_min_seconds():
    rows = {r["id"]: r for r in list_video_providers()}
    for pid in ("omni", "veo", "fal:seedance-2.0", "fal:seedance-2.5", "fake"):
        assert rows[pid]["price_per_second"] >= 0 and rows[pid]["min_seconds"] >= 1


def test_estimate_cost_breakdown():
    e = estimate_cost(provider_id="fal:seedance-2.0", target_duration=20)
    assert e["n_segments"] == 2 and e["segment_seconds"] == 10 and e["keyframes"] == 3
    assert e["video_seconds"] == 20 and e["video_cost"] == pytest.approx(20 * FAL_MODELS["seedance-2.0"]["price_per_second"], rel=1e-3)
    assert e["image_cost"] > 0 and e["total"] == pytest.approx(e["video_cost"] + e["image_cost"] + e["planner_cost"], rel=1e-3)
    short = estimate_cost(provider_id="fal:minimax-h3", target_duration=3)
    assert short["n_segments"] == 1 and short["segment_seconds"] == 5 and short["video_seconds"] == 5 and short["keyframes"] == 2


def test_service_accepts_3_second_videos(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    svc = LabService(s, image=FakeImageGen(), video=FakeVideoGen(), planner=FakePlanner(), storage_dir=tmp_path / "storage")
    v = svc.create(prompt="A quick wave hello", target_duration=3)
    assert (v.n_segments, v.segment_seconds) == (1, 3)
    svc.run_to_images(v.id)
    assert len(svc.keyframes(v.id)) == 2
    svc.animate(v.id)
    assert svc.get(v.id).status == "DONE"
    with pytest.raises(ValueError):
        svc.create(prompt="too short", target_duration=2)


def test_estimate_endpoint(tmp_path):
    from app.api.main import create_app
    from app.projects.jobs import InlineJobRunner

    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(
        session_factory=factory,
        jobs=InlineJobRunner(),
        service_kwargs=dict(storage_dir=tmp_path / "storage"),
        lab_kwargs=dict(image=FakeImageGen(), planner=FakePlanner(), video=FakeVideoGen()),
    )
    with TestClient(app) as c:
        r = c.get("/lab/estimate", params={"provider": "fal:seedance-2.0", "duration": 12})
        assert r.status_code == 200 and r.json()["n_segments"] == 2 and r.json()["total"] > 0
        assert c.get("/lab/estimate", params={"provider": "fal:nope", "duration": 12}).status_code == 422
        assert (
            c.post("/lab/videos", json={"prompt": "A quick wave hello", "target_duration": 3, "video_provider": "fake"}).status_code == 201
        )
