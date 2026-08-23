"""Trends API: analyse a TikTok/Reels/Shorts URL, browse analyses, create a template from a proposal."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import cfg_dir, get_db, storage_dir
from app.api.routes.meta import _template_path, _write_template
from app.models import TrendAnalysis
from app.projects.jobs import JobBusy
from app.trends.service import TrendService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/trends", tags=["trends"])


def _svc(request: Request, db: Session) -> TrendService:
    kw = request.app.state.service_kwargs
    tk = getattr(request.app.state, "trend_kwargs", {}) or {}
    return TrendService(db, storage_dir=storage_dir(request), configs_dir=cfg_dir(request), llm=kw.get("llm"), **tk)


def _out(t: TrendAnalysis, full: bool = False) -> dict:
    d = {
        "id": t.id,
        "url": t.url,
        "platform": t.platform,
        "persona_id": t.persona_id,
        "status": t.status,
        "stage_message": t.stage_message,
        "error": t.error,
        "title": t.title,
        "uploader": t.uploader,
        "duration": t.duration,
        "meta": {
            k: v for k, v in (t.meta or {}).items() if k in ("view_count", "like_count", "comment_count", "upload_date", "webpage_url")
        },
        "thumbnail_url": f"/trends/{t.id}/thumbnail" if t.thumbnail_path else None,
        "video_url": f"/trends/{t.id}/video" if t.video_path else None,
        "template_id": t.template_id,
        "has_transcript": bool(t.transcript),
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }
    if full:
        d["transcript"] = t.transcript
        d["analysis"] = t.analysis
        d["template_draft"] = TrendService.template_from_proposal(t.analysis) if t.analysis else None
    return d


def _start(request: Request, tid: str) -> None:
    factory = request.app.state.session_factory
    kw = request.app.state.service_kwargs
    tk = getattr(request.app.state, "trend_kwargs", {}) or {}
    sd, cd = storage_dir(request), cfg_dir(request)

    def _job():
        with factory() as s:
            try:
                TrendService(s, storage_dir=sd, configs_dir=cd, llm=kw.get("llm"), **tk).run(tid)
            except Exception:  # noqa: BLE001
                log.exception("trend %s failed", tid)

    request.app.state.lab_jobs.submit(tid, _job)


class TrendCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    persona_id: str | None = None


@router.post("", status_code=202)
def trend_create(body: TrendCreate, request: Request, db: Session = Depends(get_db)):
    try:
        t = _svc(request, db).create(url=body.url, persona_id=body.persona_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        _start(request, t.id)
    except JobBusy as exc:
        raise HTTPException(409, str(exc))
    return _out(t)


@router.get("")
def trend_list(request: Request, persona: str | None = None, db: Session = Depends(get_db)):
    return [_out(t) for t in _svc(request, db).list(persona)]


@router.get("/{tid}")
def trend_get(tid: str, db: Session = Depends(get_db)):
    t = db.get(TrendAnalysis, tid)
    if t is None:
        raise HTTPException(404, "not found")
    return _out(t, full=True)


@router.post("/{tid}/retry", status_code=202)
def trend_retry(tid: str, request: Request, db: Session = Depends(get_db)):
    try:
        t = _svc(request, db).retry(tid)
    except KeyError:
        raise HTTPException(404, "not found")
    try:
        _start(request, tid)
    except JobBusy as exc:
        raise HTTPException(409, str(exc))
    return _out(t)


@router.delete("/{tid}", status_code=204)
def trend_delete(tid: str, request: Request, db: Session = Depends(get_db)):
    try:
        _svc(request, db).delete(tid)
    except KeyError:
        raise HTTPException(404, "not found")


@router.get("/{tid}/thumbnail")
def trend_thumb(tid: str, db: Session = Depends(get_db)):
    t = db.get(TrendAnalysis, tid)
    if t is None or not t.thumbnail_path or not Path(t.thumbnail_path).is_file():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(t.thumbnail_path, media_type="image/jpeg")


@router.get("/{tid}/video")
def trend_video(tid: str, db: Session = Depends(get_db)):
    t = db.get(TrendAnalysis, tid)
    if t is None or not t.video_path or not Path(t.video_path).is_file():
        raise HTTPException(404, "no video")
    return FileResponse(t.video_path, media_type="video/mp4")


class GenerateFromTrend(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    persona_id: str | None = None
    target_duration: float | None = Field(default=None, ge=15, le=25)


@router.post("/{tid}/generate", status_code=202)
def trend_generate(tid: str, body: GenerateFromTrend, request: Request, db: Session = Depends(get_db)):
    """One-off video with this trend's structure (no template is saved): creates the project and starts generation."""
    from app.api.deps import run_job, svc
    from app.api.routes.projects import _project_out

    t = db.get(TrendAnalysis, tid)
    if t is None:
        raise HTTPException(404, "not found")
    if not t.analysis:
        raise HTTPException(409, "analysis not finished")
    tpl = TrendService.template_from_proposal(t.analysis)
    tpl["id"] = f"trend_{t.id.split('_')[-1]}"
    try:
        p = svc(db, request).create_project(
            topic=body.topic,
            template_id=tpl["id"],
            persona_id=body.persona_id or t.persona_id,
            target_duration=body.target_duration,
            template_override=tpl,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    run_job(request, p.id, "generate", lambda s: s.generate(p.id))
    return _project_out(p, db)


class TemplateFromTrend(BaseModel):
    template: dict | None = None  # full TemplateConfig dict (edited in the UI); None = use the draft as-is


@router.post("/{tid}/template", status_code=201)
def trend_template(tid: str, body: TemplateFromTrend, request: Request, db: Session = Depends(get_db)):
    """Create a template from this analysis (the user approved the draft, possibly edited)."""
    t = db.get(TrendAnalysis, tid)
    if t is None:
        raise HTTPException(404, "not found")
    if not t.analysis:
        raise HTTPException(409, "analysis not finished")
    tpl = body.template or TrendService.template_from_proposal(t.analysis)
    path = _template_path(request, str(tpl.get("id", "")))
    if path.exists():
        raise HTTPException(409, f"template {tpl.get('id')} already exists — change the id")
    saved = _write_template(request, tpl, path)
    t.template_id = saved["id"]
    db.commit()
    return saved
