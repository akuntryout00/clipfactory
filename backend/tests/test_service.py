import json
from pathlib import Path

import pytest

from app.assets.importer import import_assets
from app.llm.fake import FakeLLM
from app.models import Asset, ProjectStatus, Render, VideoProject, VideoScene, VoiceGeneration
from app.projects.service import ProjectService
from app.renderer.ffmpeg import ffmpeg_has_filter
from app.voice.fake import FakeVoice

needs_libass = pytest.mark.skipif(not ffmpeg_has_filter("ass"), reason="local ffmpeg lacks libass; runs in Docker")


@pytest.fixture()
def svc(session, mini_assets, tmp_path):
    import_assets(session, mini_assets)
    storage = tmp_path / "storage"
    return ProjectService(session, llm=FakeLLM(), voice=FakeVoice(), storage_dir=storage, assets_dir=mini_assets,
                          render_preset="ultrafast", render_crf=30)


def test_create_project_defaults(svc):
    p = svc.create_project(topic="Stop taking meeting notes manually", template_id="story_v1")
    assert p.status == ProjectStatus.DRAFT.value
    assert p.persona_id == "michael"
    assert p.target_duration == 18
    assert p.id.startswith("proj_")


def test_create_project_rejects_bad_duration_or_template(svc):
    with pytest.raises(ValueError):
        svc.create_project(topic="x", template_id="story_v1", target_duration=40)
    with pytest.raises(FileNotFoundError):
        svc.create_project(topic="x", template_id="nope")


def test_stages_up_to_plan_produce_versioned_artifacts(svc, session):
    p = svc.create_project(topic="Stop taking meeting notes manually", template_id="list_v1")
    svc.run_script(p.id)
    svc.run_voice(p.id)
    svc.run_plan(p.id)
    p = session.get(VideoProject, p.id)
    assert p.script_version == 1 and p.voice_version == 1 and p.plan_version == 1
    d = svc.project_dir(p.id)
    assert (d / "script_v1.json").is_file() and (d / "voice_v1.mp3").is_file() and (d / "plan_v1.json").is_file()
    plan = json.loads((d / "plan_v1.json").read_text())
    assert plan["version"] == "1.0" and 4 <= len(plan["scenes"]) <= 8
    assert p.actual_duration and abs(p.actual_duration - plan["voiceover"]["duration"]) < 0.01
    scenes = session.query(VideoScene).filter_by(project_id=p.id, plan_version=1).all()
    assert len(scenes) == len(plan["scenes"])
    assert len({s.asset_id for s in scenes}) == len(scenes)


def test_voice_is_master_clock_and_shortens_when_over_max(svc, session, monkeypatch):
    # make the fake voice slow so the first take exceeds max duration → shorten loop kicks in
    import app.voice.fake as fake_mod
    monkeypatch.setattr(fake_mod, "WORDS_PER_SECOND", 1.2)
    p = svc.create_project(topic="Stop taking meeting notes manually", template_id="story_v1", target_duration=20)
    svc.run_script(p.id)
    v1_words = len(session.get(VideoProject, p.id).script.split())
    svc.run_voice(p.id)
    p = session.get(VideoProject, p.id)
    assert p.script_version >= 2  # was rewritten at least once
    assert len(p.script.split()) < v1_words
    vg = session.query(VoiceGeneration).filter_by(project_id=p.id).order_by(VoiceGeneration.version.desc()).first()
    assert p.actual_duration == vg.duration


def test_voice_fails_after_two_rewrites(svc, session, monkeypatch):
    import app.voice.fake as fake_mod
    monkeypatch.setattr(fake_mod, "WORDS_PER_SECOND", 0.3)  # hopeless
    p = svc.create_project(topic="x", template_id="story_v1", target_duration=18)
    svc.run_script(p.id)
    with pytest.raises(RuntimeError):
        svc.run_voice(p.id)
    p = session.get(VideoProject, p.id)
    assert p.status == ProjectStatus.FAILED.value
    assert p.script_version == 3  # v1 + 2 rewrites


@needs_libass
def test_generate_end_to_end_and_controls(svc, session):
    p = svc.create_project(topic="Stop taking meeting notes manually", template_id="story_v1")
    svc.generate(p.id)
    p = session.get(VideoProject, p.id)
    assert p.status == ProjectStatus.READY.value, p.error
    r1 = session.get(Render, p.current_render_id)
    assert Path(r1.output_path).is_file() and r1.qc["passed"]
    assert (svc.project_dir(p.id) / "final.mp4").is_file()
    # asset usage bookkeeping only after success
    used = session.query(Asset).filter(Asset.usage_count > 0).all()
    assert used and all(a.last_used_project_id == p.id for a in used)
    plan1 = svc.load_plan(p.id, 1)

    # change assets: script+voice kept, plan v2 with different assets, render v2
    svc.change_assets(p.id)
    p = session.get(VideoProject, p.id)
    assert p.script_version == 1 and p.voice_version == 1 and p.plan_version == 2 and p.render_version == 2
    plan2 = svc.load_plan(p.id, 2)
    assert [s.asset_id for s in plan1.scenes] != [s.asset_id for s in plan2.scenes]

    # render again: same plan assets, new seed → offsets differ, render v3
    svc.render_again(p.id)
    p = session.get(VideoProject, p.id)
    assert p.plan_version == 3 and p.render_version == 3
    plan3 = svc.load_plan(p.id, 3)
    assert [s.asset_id for s in plan2.scenes] == [s.asset_id for s in plan3.scenes]
    assert plan3.seed != plan2.seed

    # regenerate script: everything re-done
    svc.regenerate_script(p.id)
    p = session.get(VideoProject, p.id)
    assert p.script_version == 2 and p.voice_version == 2 and p.plan_version == 4 and p.render_version == 4

    # manual override of one scene then approve
    sugg = svc.suggest_assets(p.id, scene_order=1)
    assert sugg
    svc.override_scene_asset(p.id, scene_order=1, asset_id=sugg[0]["asset_id"])
    p = session.get(VideoProject, p.id)
    assert svc.load_plan(p.id, p.plan_version).scenes[0].asset_id == sugg[0]["asset_id"]
    svc.approve(p.id)
    assert session.get(VideoProject, p.id).status == ProjectStatus.APPROVED.value


def test_render_failure_marks_failed_without_rerunning_llm(svc, session, monkeypatch):
    p = svc.create_project(topic="x", template_id="story_v1")
    svc.run_script(p.id); svc.run_voice(p.id); svc.run_plan(p.id)
    calls = {"n": 0}
    real = svc.llm.generate_script
    def counting(**kw):
        calls["n"] += 1
        return real(**kw)
    monkeypatch.setattr(svc.llm, "generate_script", counting)
    import app.projects.service as svc_mod
    def boom(*a, **k):
        raise RuntimeError("ffmpeg exploded")
    monkeypatch.setattr(svc_mod, "render_video", boom)
    with pytest.raises(RuntimeError):
        svc.run_render(p.id)
    p = session.get(VideoProject, p.id)
    assert p.status == ProjectStatus.FAILED.value and "ffmpeg exploded" in p.error
    assert calls["n"] == 0
    assert p.script_version == 1 and p.plan_version == 1
