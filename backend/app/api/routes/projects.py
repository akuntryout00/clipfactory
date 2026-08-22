"""Content-factory projects: CRUD, pipeline actions (background jobs), artifacts, media."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, run_job, storage_dir, svc
from app.api.media import ranged_file
from app.api.schemas import Accepted, ProjectCreate, ProjectOut, SceneAssetOverride
from app.models import Asset, ProjectStatus, VideoProject, VideoScene

log = logging.getLogger(__name__)
router = APIRouter()


# ---------- projects ----------
def _project_out(p: VideoProject, db: Session) -> ProjectOut:
    scenes = (
        db.execute(
            select(VideoScene).where(VideoScene.project_id == p.id, VideoScene.plan_version == p.plan_version).order_by(VideoScene.order)
        )
        .scalars()
        .all()
    )
    out = ProjectOut.model_validate(p, from_attributes=True)
    out.scenes = [
        dict(
            order=s.order,
            section=s.section,
            start_time=s.start_time,
            end_time=s.end_time,
            asset_id=s.asset_id,
            asset_start_time=s.asset_start_time,
            overlay_text=s.overlay_text,
            intent=s.intent,
        )
        for s in scenes
    ]
    out.renders = [r for r in sorted(p.renders, key=lambda r: r.version)]
    out.events = [e for e in sorted(p.events, key=lambda e: e.created_at)][-50:]
    if p.current_render_id and p.status in (ProjectStatus.READY.value, ProjectStatus.APPROVED.value):
        out.video_url = f"/projects/{p.id}/video"
    return out


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, request: Request, db: Session = Depends(get_db)):
    try:
        p = svc(db, request).create_project(
            topic=body.topic, template_id=body.template_id, persona_id=body.persona_id, target_duration=body.target_duration
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return _project_out(p, db)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(request: Request, db: Session = Depends(get_db), limit: int = 50, persona: str | None = None):
    return [_project_out(p, db) for p in svc(db, request).list_projects(limit, persona_id=persona)]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    p = db.get(VideoProject, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return _project_out(p, db)


def _require(project_id: str, db: Session) -> VideoProject:
    p = db.get(VideoProject, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p


@router.post("/projects/{project_id}/generate", response_model=Accepted, status_code=202)
def generate(project_id: str, request: Request, db: Session = Depends(get_db)):
    _require(project_id, db)
    return run_job(request, project_id, "generate", lambda s: s.generate(project_id))


@router.post("/projects/{project_id}/regenerate-script", response_model=Accepted, status_code=202)
def regenerate_script(project_id: str, request: Request, db: Session = Depends(get_db)):
    _require(project_id, db)
    return run_job(request, project_id, "regenerate-script", lambda s: s.regenerate_script(project_id))


@router.post("/projects/{project_id}/change-assets", response_model=Accepted, status_code=202)
def change_assets(project_id: str, request: Request, db: Session = Depends(get_db)):
    p = _require(project_id, db)
    if p.plan_version == 0:
        raise HTTPException(409, "project has no plan yet — run generate first")
    return run_job(request, project_id, "change-assets", lambda s: s.change_assets(project_id))


@router.post("/projects/{project_id}/render", response_model=Accepted, status_code=202)
def render_again(project_id: str, request: Request, db: Session = Depends(get_db)):
    p = _require(project_id, db)
    if p.plan_version == 0:
        raise HTTPException(409, "project has no plan yet — run generate first")
    return run_job(request, project_id, "render-again", lambda s: s.render_again(project_id))


@router.post("/projects/{project_id}/retry", response_model=Accepted, status_code=202)
def retry(project_id: str, request: Request, db: Session = Depends(get_db)):
    _require(project_id, db)
    return run_job(request, project_id, "retry", lambda s: s.retry(project_id))


@router.post("/projects/{project_id}/approve", response_model=ProjectOut)
def approve(project_id: str, request: Request, db: Session = Depends(get_db)):
    _require(project_id, db)
    try:
        p = svc(db, request).approve(project_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return _project_out(p, db)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    import shutil

    p = _require(project_id, db)
    if request.app.state.jobs.is_running(project_id):
        raise HTTPException(409, "a job is running for this project")
    db.delete(p)
    db.commit()
    shutil.rmtree(storage_dir(request) / "projects" / project_id, ignore_errors=True)
    shutil.rmtree(storage_dir(request) / "renders" / project_id, ignore_errors=True)
    return Response(status_code=204)


@router.get("/projects/{project_id}/artifacts")
def project_artifacts(project_id: str, request: Request, db: Session = Depends(get_db)):
    """Every versioned artifact of a project (PRD §45) for the UI's history view."""
    import json as _json
    import re

    p = _require(project_id, db)
    d = storage_dir(request) / "projects" / project_id
    scripts, plans = [], []
    if d.is_dir():
        for f in sorted(d.glob("script_v*.json"), key=lambda x: int(re.findall(r"\d+", x.stem)[0])):
            scripts.append({"version": int(re.findall(r"\d+", f.stem)[0]), "content": _json.loads(f.read_text())})
        for f in sorted(d.glob("plan_v*.json"), key=lambda x: int(re.findall(r"\d+", x.stem)[0])):
            plans.append({"version": int(re.findall(r"\d+", f.stem)[0]), **_json.loads(f.read_text())})
    voices = [
        {
            "version": v.version,
            "script_version": v.script_version,
            "duration": v.duration,
            "provider": v.provider,
            "url": f"/projects/{project_id}/voices/{v.version}/audio",
        }
        for v in sorted(p.voices, key=lambda v: v.version)
    ]
    renders = [
        {
            "id": r.id,
            "version": r.version,
            "plan_version": r.plan_version,
            "voice_version": r.voice_version,
            "status": r.status,
            "qc": r.qc,
            "error": r.error,
            "created_at": r.created_at,
            "seed": r.seed,
            "url": f"/projects/{project_id}/renders/{r.version}/video" if r.status == "DONE" else None,
        }
        for r in sorted(p.renders, key=lambda r: r.version)
    ]
    return {"scripts": scripts, "voices": voices, "plans": plans, "renders": renders}


@router.get("/projects/{project_id}/voice")
def project_voice(project_id: str, request: Request, db: Session = Depends(get_db)):
    p = _require(project_id, db)
    if p.voice_version == 0:
        raise HTTPException(404, "no voice yet")
    return ranged_file(storage_dir(request) / "projects" / project_id / f"voice_v{p.voice_version}.mp3", request, media_type="audio/mpeg")


@router.get("/projects/{project_id}/voices/{version}/audio")
def project_voice_version(project_id: str, version: int, request: Request, db: Session = Depends(get_db)):
    _require(project_id, db)
    return ranged_file(storage_dir(request) / "projects" / project_id / f"voice_v{version}.mp3", request, media_type="audio/mpeg")


@router.get("/projects/{project_id}/renders/{version}/video")
def project_render_video(project_id: str, version: int, request: Request, db: Session = Depends(get_db)):
    _require(project_id, db)
    return ranged_file(storage_dir(request) / "renders" / project_id / f"render_v{version}.mp4", request, media_type="video/mp4")


@router.get("/projects/{project_id}/plan")
def get_plan(project_id: str, request: Request, db: Session = Depends(get_db)):
    p = _require(project_id, db)
    if p.plan_version == 0:
        raise HTTPException(404, "no plan yet")
    return svc(db, request).load_plan(project_id, p.plan_version).model_dump()


@router.get("/projects/{project_id}/video")
def get_video(project_id: str, request: Request, db: Session = Depends(get_db)):
    p = _require(project_id, db)
    path = svc(db, request).project_dir(project_id) / "final.mp4"
    if not p.current_render_id or not path.is_file():
        raise HTTPException(404, "no render available")
    return ranged_file(path, request, media_type="video/mp4")


@router.get("/projects/{project_id}/scenes/{order}/suggestions")
def scene_suggestions(project_id: str, order: int, request: Request, db: Session = Depends(get_db)):
    p = _require(project_id, db)
    if p.plan_version == 0:
        raise HTTPException(404, "no plan yet")
    try:
        return svc(db, request).suggest_assets(project_id, order)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"scene not found: {exc}")


@router.post("/projects/{project_id}/scenes/{order}/asset", response_model=Accepted, status_code=202)
def scene_override(project_id: str, order: int, body: SceneAssetOverride, request: Request, db: Session = Depends(get_db)):
    p = _require(project_id, db)
    if p.plan_version == 0:
        raise HTTPException(409, "no plan yet")
    if db.get(Asset, body.asset_id) is None:
        raise HTTPException(404, "asset not found")
    return run_job(request, project_id, "scene-override", lambda s: s.override_scene_asset(project_id, order, body.asset_id))
