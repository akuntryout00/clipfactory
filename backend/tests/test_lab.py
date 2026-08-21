"""AI Lab — isolated module: prompt → keyframe images (OpenAI) → animated segments (Google) → 9:16 MP4."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.assets.metadata import probe_video
from app.db import Base
from app.lab.planning import segment_plan
from app.lab.providers import FakeImageGen, FakePlanner, FakeVideoGen
from app.lab.service import LabService
from app.lab.models import LabVideo, LabKeyframe, LabSegment  # noqa: F401 (register tables)


@pytest.mark.parametrize("dur,n_seg,seg", [(15, 2, 8), (18, 3, 6), (20, 3, 7), (25, 4, 6)])
def test_segment_plan_covers_target_with_4_to_8s_segments(dur, n_seg, seg):
    n, s = segment_plan(dur, max_seg=8)
    assert (n, s) == (n_seg, seg)
    assert 4 <= s <= 8 and n >= 2


@pytest.mark.parametrize("dur,n_seg,seg", [(15, 2, 8), (18, 2, 9), (20, 2, 10), (25, 3, 8)])
def test_segment_plan_with_10s_segments_for_omni(dur, n_seg, seg):
    assert segment_plan(dur, max_seg=10) == (n_seg, seg)


def test_service_uses_provider_max_seconds(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    vg = FakeVideoGen(); vg.max_seconds = 10
    svc = LabService(s, image=FakeImageGen(), video=vg, planner=FakePlanner(), storage_dir=tmp_path / "storage")
    v = svc.create(prompt="A quiet cafe morning", target_duration=20)
    assert (v.n_segments, v.segment_seconds) == (2, 10)


@pytest.fixture()
def lab(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    svc = LabService(s, image=FakeImageGen(), video=FakeVideoGen(), planner=FakePlanner(), storage_dir=tmp_path / "storage")
    yield svc, s
    s.close()


def test_create_is_instant_and_plan_makes_keyframes(lab):
    svc, s = lab
    v = svc.create(prompt="A solo founder's morning: coffee, laptop, sunrise city walk", target_duration=18)
    assert v.status == "PLANNING" and v.n_segments == 3 and v.segment_seconds == 6
    assert svc.keyframes(v.id) == []
    svc.plan(v.id)
    v = svc.get(v.id)
    assert v.status == "PLANNED"
    kfs = svc.keyframes(v.id)
    assert len(kfs) == 4 and [k.index for k in kfs] == [0, 1, 2, 3]
    assert all(k.prompt for k in kfs) and v.style_guide
    stages = [e.stage for e in svc.events(v.id)]
    assert "PLANNING" in stages and "PLANNED" in stages


def test_run_to_images_does_plan_and_images_and_logs_progress(lab):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)
    svc.run_to_images(v.id)
    v = svc.get(v.id)
    assert v.status == "IMAGES_READY"
    msgs = [e.message for e in svc.events(v.id)]
    assert any("Keyframe 1/3" in m for m in msgs) and any("Keyframe 3/3" in m for m in msgs)


def test_retry_resumes_from_failed_stage(lab, monkeypatch):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)
    svc.plan(v.id)
    calls = {"n": 0}
    real = svc.image.generate
    def flaky(*, prompt, out_path):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("image API down")
        return real(prompt=prompt, out_path=out_path)
    monkeypatch.setattr(svc.image, "generate", flaky)
    with pytest.raises(RuntimeError):
        svc.generate_images(v.id)
    v = svc.get(v.id)
    assert v.status == "FAILED" and "image API down" in v.error
    assert [k.status for k in svc.keyframes(v.id)] == ["DONE", "FAILED", "PENDING"]
    svc.retry(v.id)  # resumes: only missing images, no re-plan
    v = svc.get(v.id)
    assert v.status == "IMAGES_READY" and calls["n"] == 4  # 1 ok + 1 fail + 2 resumed


def test_generate_images_then_animate_produces_916_mp4(lab):
    svc, s = lab
    v = svc.create(prompt="Morning routine", target_duration=15)
    svc.plan(v.id)
    svc.generate_images(v.id)
    v = svc.get(v.id)
    assert v.status == "IMAGES_READY"
    for k in svc.keyframes(v.id):
        assert k.image_path and Path(k.image_path).is_file() and k.status == "DONE"
    svc.animate(v.id)
    v = svc.get(v.id)
    assert v.status == "DONE", v.error
    segs = svc.segments(v.id)
    assert len(segs) == 2 and all(Path(x.video_path).is_file() for x in segs)
    meta = probe_video(Path(v.final_path))
    assert (meta.width, meta.height) == (1080, 1920) and abs(meta.duration - 16) < 1.0


def test_regenerate_single_keyframe_with_new_prompt(lab):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)
    svc.run_to_images(v.id)
    k1 = svc.keyframes(v.id)[1]
    old_path, old_version = k1.image_path, k1.version
    svc.regenerate_keyframe(v.id, 1, prompt="a red door in the rain")
    k1 = svc.keyframes(v.id)[1]
    assert k1.prompt == "a red door in the rain" and k1.version == old_version + 1 and k1.image_path != old_path
    assert svc.get(v.id).status == "IMAGES_READY"


def test_animate_requires_images(lab):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)
    with pytest.raises(RuntimeError):
        svc.animate(v.id)


def test_lab_api_flow(tmp_path):
    from app.api.main import create_app
    from app.projects.jobs import InlineJobRunner

    engine = create_engine(f"sqlite:///{tmp_path / 'lab.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(session_factory=factory, jobs=InlineJobRunner(), service_kwargs=dict(storage_dir=tmp_path / "storage"),
                     lab_kwargs=dict(image=FakeImageGen(), video=FakeVideoGen(), planner=FakePlanner()))
    with TestClient(app) as c:
        r = c.post("/lab/videos", json={"prompt": "Cozy cafe morning, cinematic", "target_duration": 18})
        assert r.status_code == 201, r.text
        vid = r.json()["id"]
        # inline job runner → planning + images already ran by the time we look
        g = c.get(f"/lab/videos/{vid}").json()
        assert g["status"] == "IMAGES_READY" and len(g["keyframes"]) == 4
        assert g["events"] and g["events"][0]["stage"] and all("created_at" in e for e in g["events"])
        assert c.post(f"/lab/videos/{vid}/retry").status_code == 202
        assert c.get(f"/lab/videos/{vid}/keyframes/0/image").headers["content-type"] == "image/png"
        assert c.post(f"/lab/videos/{vid}/keyframes/1/regenerate", json={"prompt": "night version"}).status_code == 202
        assert c.get(f"/lab/videos/{vid}").json()["keyframes"][1]["prompt"] == "night version"
        assert c.post(f"/lab/videos/{vid}/animate").status_code == 202
        g = c.get(f"/lab/videos/{vid}").json()
        assert g["status"] == "DONE" and g["video_url"]
        assert c.get(f"/lab/videos/{vid}/video").status_code == 200
        assert c.get("/lab/videos").json()[0]["id"] == vid
        assert c.delete(f"/lab/videos/{vid}").status_code == 204
        assert c.get(f"/lab/videos/{vid}").status_code == 404


def test_animate_force_redoes_finished_segments(lab):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)
    svc.run_to_images(v.id)
    svc.animate(v.id)
    first_paths = [Path(x.video_path) for x in svc.segments(v.id)]
    mtimes = [p.stat().st_mtime_ns for p in first_paths]
    import time; time.sleep(0.05)
    svc.animate(v.id)  # no force → segments untouched
    assert [p.stat().st_mtime_ns for p in first_paths] == mtimes
    svc.animate(v.id, force=True)  # force → re-rendered
    assert [p.stat().st_mtime_ns for p in first_paths] != mtimes
    assert svc.get(v.id).status == "DONE"
