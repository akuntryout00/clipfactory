"""AI Lab — isolated module: prompt → keyframe images (OpenAI) → animated segments (Google) → 9:16 MP4."""

import time
from pathlib import Path

import pytest
from app.assets.metadata import probe_video
from app.db import Base
from app.lab.models import LabKeyframe, LabSegment, LabVideo  # noqa: F401 (register tables)
from app.lab.planning import segment_plan
from app.lab.providers import FakeImageGen, FakePlanner, FakeVideoGen
from app.lab.service import LabService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


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
    vg = FakeVideoGen()
    vg.max_seconds = 10
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

    def flaky(*, prompt, out_path, reference=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("image API down")
        return real(prompt=prompt, out_path=out_path, reference=reference)

    monkeypatch.setattr(svc.image, "generate", flaky)
    with pytest.raises(RuntimeError):
        svc.generate_images(v.id)
    v = svc.get(v.id)
    assert v.status == "FAILED" and "image API down" in v.error
    assert [k.status for k in svc.keyframes(v.id)] == ["DONE", "FAILED", "PENDING"]  # sequential: stops at the failure
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
    app = create_app(
        session_factory=factory,
        jobs=InlineJobRunner(),
        service_kwargs=dict(storage_dir=tmp_path / "storage"),
        lab_kwargs=dict(image=FakeImageGen(), video=FakeVideoGen(), planner=FakePlanner()),
    )
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
    time.sleep(0.05)
    svc.animate(v.id)  # no force → segments untouched
    assert [p.stat().st_mtime_ns for p in first_paths] == mtimes
    svc.animate(v.id, force=True)  # force → re-rendered
    assert [p.stat().st_mtime_ns for p in first_paths] != mtimes
    assert svc.get(v.id).status == "DONE"


def test_generate_images_chains_previous_frame_as_reference(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()

    class RecordingImage(FakeImageGen):
        calls: list[tuple[str, str | None]] = []

        def generate(self, *, prompt, out_path, reference=None):
            self.calls.append((str(out_path.name), str(reference.name) if reference else None))
            return super().generate(prompt=prompt, out_path=out_path, reference=reference)

    img = RecordingImage()
    svc = LabService(s, image=img, video=FakeVideoGen(), planner=FakePlanner(), storage_dir=tmp_path / "storage")
    v = svc.create(prompt="A quiet cafe morning", target_duration=18)  # 4 keyframes
    svc.plan(v.id)
    svc.generate_images(v.id)
    assert img.calls == [
        ("kf_00_v1.png", None),
        ("kf_01_v1.png", "kf_00_v1.png"),
        ("kf_02_v1.png", "kf_01_v1.png"),
        ("kf_03_v1.png", "kf_02_v1.png"),
    ]
    # regenerating frame 2 uses frame 1 as reference
    img.calls.clear()
    svc.regenerate_keyframe(v.id, 2, prompt="a red door in the rain")
    assert img.calls == [("kf_02_v2.png", "kf_01_v1.png")]


def test_default_image_quality_is_low():
    from app.config.settings import Settings

    assert Settings(_env_file=None).openai_image_quality == "low"


def test_regenerate_segment_with_new_prompt_reconcats(lab):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)
    svc.run_to_images(v.id)
    svc.animate(v.id)
    seg0 = svc.segments(v.id)[0]
    old_mtime = Path(seg0.video_path).stat().st_mtime_ns
    final_mtime = Path(svc.get(v.id).final_path).stat().st_mtime_ns
    time.sleep(0.05)
    svc.regenerate_segment(v.id, 0, prompt="whip pan to the door")
    seg0 = svc.segments(v.id)[0]
    assert seg0.prompt == "whip pan to the door" and Path(seg0.video_path).stat().st_mtime_ns != old_mtime
    v = svc.get(v.id)
    assert v.status == "DONE" and Path(v.final_path).stat().st_mtime_ns != final_mtime


def test_edit_segment_uses_provider_edit_when_available(lab):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)
    svc.run_to_images(v.id)
    svc.animate(v.id)
    seg1 = svc.segments(v.id)[1]
    assert seg1.provider_ref  # fake provider hands back an id like a real interaction
    svc.regenerate_segment(v.id, 1, edit_instruction="make it night time, keep everything else the same")
    seg1 = svc.segments(v.id)[1]
    assert seg1.status == "DONE" and "night" in (seg1.last_edit or "")
    assert svc.get(v.id).status == "DONE"


def test_set_duration_same_segment_count_keeps_keyframes(lab):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)  # 2×8 (fake max 8)
    svc.run_to_images(v.id)
    svc.animate(v.id)
    kf_paths = [k.image_path for k in svc.keyframes(v.id)]
    v = svc.set_duration(v.id, 16)  # still 2 segments
    assert (v.n_segments, v.segment_seconds) == (2, 8)
    assert [k.image_path for k in svc.keyframes(v.id)] == kf_paths
    assert all(x.status == "PENDING" for x in svc.segments(v.id)) and v.status == "IMAGES_READY" and v.final_path is None


def test_set_duration_new_segment_count_replans(lab):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)  # 2 segments, 3 keyframes
    svc.run_to_images(v.id)
    v = svc.set_duration(v.id, 25)  # 4 segments, 5 keyframes
    assert (v.n_segments, v.segment_seconds) == (4, 6) and v.status == "PLANNING"
    assert svc.keyframes(v.id) == []
    svc.run_to_images(v.id)
    assert len(svc.keyframes(v.id)) == 5 and svc.get(v.id).status == "IMAGES_READY"


def test_clone_copies_keyframes_and_animates_with_other_provider(lab, tmp_path):
    svc, s = lab
    v = svc.create(prompt="A quiet cafe morning", target_duration=15)
    svc.run_to_images(v.id)
    svc.animate(v.id)
    other = FakeVideoGen()
    other.model = "other-video-model"
    other.max_seconds = 6
    svc2 = LabService(s, image=svc.image, video=other, planner=svc.planner, storage_dir=svc.storage_dir.parent)
    c = svc2.clone(v.id)
    assert c.id != v.id and c.prompt == v.prompt and c.video_model == "other-video-model"
    # other provider max 6 s → 15 s needs 3×5 (4 keyframes) ≠ 3 keyframes → keyframes can't be reused → must re-plan
    assert (c.n_segments, c.segment_seconds) == (3, 5) and c.status == "PLANNING" and svc2.keyframes(c.id) == []
    # same segment count → keyframes are copied and the clone is ready to animate
    same = FakeVideoGen()
    same.model = "same-count-model"
    svc3 = LabService(s, image=svc.image, video=same, planner=svc.planner, storage_dir=svc.storage_dir.parent)
    c2 = svc3.clone(v.id)
    assert c2.status == "IMAGES_READY" and len(svc3.keyframes(c2.id)) == 3
    assert all(Path(k.image_path).is_file() and str(c2.id) in k.image_path for k in svc3.keyframes(c2.id))
    svc3.animate(c2.id)
    assert svc3.get(c2.id).status == "DONE"


def test_lab_api_providers_and_create_with_provider(tmp_path):
    from app.api.main import create_app
    from app.projects.jobs import InlineJobRunner

    engine = create_engine(f"sqlite:///{tmp_path / 'lab2.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(
        session_factory=factory,
        jobs=InlineJobRunner(),
        service_kwargs=dict(storage_dir=tmp_path / "storage"),
        lab_kwargs=dict(image=FakeImageGen(), planner=FakePlanner()),
    )
    with TestClient(app) as c:
        provs = c.get("/lab/providers").json()
        assert any(p["id"] == "fake" for p in provs) and any(p["id"].startswith("fal:") for p in provs)
        r = c.post("/lab/videos", json={"prompt": "Cozy cafe morning, cinematic", "target_duration": 15, "video_provider": "fake"})
        assert r.status_code == 201, r.text
        g = c.get(f"/lab/videos/{r.json()['id']}").json()
        assert g["video_provider"] == "fake" and g["provider_label"] and g["supports_edit"] is True
        assert g["status"] == "IMAGES_READY"
        assert c.post("/lab/videos", json={"prompt": "Cozy cafe morning, cinematic", "video_provider": "fal:nope"}).status_code == 422
