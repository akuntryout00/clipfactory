"""AI Lab REST API — mounted under /lab, independent of the content-factory routes."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.media import ranged_file
from app.lab.models import LabVideo
from app.lab.service import LabService
from app.projects.jobs import JobBusy

log = logging.getLogger(__name__)
router = APIRouter(prefix="/lab", tags=["ai-lab"])


class LabCreate(BaseModel):
    prompt: str = Field(min_length=5, max_length=2000)
    target_duration: float = Field(default=18, ge=15, le=25)
    style: str | None = Field(default=None, max_length=200)


class RegenBody(BaseModel):
    prompt: str | None = None


class KeyframeOut(BaseModel):
    index: int; prompt: str; caption: str | None; status: str; error: str | None; version: int; image_url: str | None


class SegmentOut(BaseModel):
    index: int; from_index: int; to_index: int; prompt: str | None; status: str; error: str | None; duration: float | None; video_url: str | None


class LabVideoOut(BaseModel):
    id: str; prompt: str; style: str | None; target_duration: float; n_segments: int; segment_seconds: int; style_guide: str | None
    status: str; stage_message: str | None; error: str | None; final_duration: float | None; image_model: str | None; video_model: str | None
    created_at: datetime; updated_at: datetime; keyframes: list[KeyframeOut] = []; segments: list[SegmentOut] = []; video_url: str | None = None


def _db(request: Request):
    s: Session = request.app.state.session_factory()
    try:
        yield s
    finally:
        s.close()


def _svc(request: Request, db: Session) -> LabService:
    return LabService(db, **request.app.state.lab_kwargs)


def _out(v: LabVideo, svc: LabService) -> LabVideoOut:
    kfs = [KeyframeOut(index=k.index, prompt=k.prompt, caption=k.caption, status=k.status, error=k.error, version=k.version,
                       image_url=f"/lab/videos/{v.id}/keyframes/{k.index}/image?v={k.version}" if k.image_path else None) for k in svc.keyframes(v.id)]
    segs = [SegmentOut(index=s.index, from_index=s.from_index, to_index=s.to_index, prompt=s.prompt, status=s.status, error=s.error, duration=s.duration,
                       video_url=f"/lab/videos/{v.id}/segments/{s.index}/video" if s.video_path else None) for s in svc.segments(v.id)]
    return LabVideoOut(id=v.id, prompt=v.prompt, style=v.style, target_duration=v.target_duration, n_segments=v.n_segments, segment_seconds=v.segment_seconds,
                       style_guide=v.style_guide, status=v.status, stage_message=v.stage_message, error=v.error, final_duration=v.final_duration,
                       image_model=v.image_model, video_model=v.video_model, created_at=v.created_at, updated_at=v.updated_at,
                       keyframes=kfs, segments=segs, video_url=f"/lab/videos/{v.id}/video" if v.final_path and v.status == "DONE" else None)


def _job(request: Request, video_id: str, op: Callable[[LabService], None]):
    factory = request.app.state.session_factory
    kwargs = request.app.state.lab_kwargs

    def run():
        with factory() as s:
            try:
                op(LabService(s, **kwargs))
            except Exception:  # noqa: BLE001 — persisted as FAILED by the service
                log.exception("lab job failed for %s", video_id)

    try:
        request.app.state.lab_jobs.submit(video_id, run)
    except JobBusy as exc:
        raise HTTPException(409, str(exc))
    return {"id": video_id, "status": "accepted"}


@router.post("/videos", response_model=LabVideoOut, status_code=201)
def create(body: LabCreate, request: Request, db: Session = Depends(_db)):
    svc = _svc(request, db)
    try:
        v = svc.create(prompt=body.prompt, target_duration=body.target_duration, style=body.style)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"planning failed: {exc}")
    return _out(v, svc)


@router.get("/videos", response_model=list[LabVideoOut])
def list_videos(request: Request, db: Session = Depends(_db)):
    svc = _svc(request, db)
    return [_out(v, svc) for v in svc.list()]


def _get(video_id: str, request: Request, db: Session) -> tuple[LabVideo, LabService]:
    svc = _svc(request, db)
    v = db.get(LabVideo, video_id)
    if v is None:
        raise HTTPException(404, "lab video not found")
    return v, svc


@router.get("/videos/{video_id}", response_model=LabVideoOut)
def get_video(video_id: str, request: Request, db: Session = Depends(_db)):
    v, svc = _get(video_id, request, db)
    return _out(v, svc)


@router.post("/videos/{video_id}/generate-images", status_code=202)
def generate_images(video_id: str, request: Request, db: Session = Depends(_db), only_missing: bool = False):
    _get(video_id, request, db)
    return _job(request, video_id, lambda s: s.generate_images(video_id, only_missing=only_missing))


@router.post("/videos/{video_id}/keyframes/{index}/regenerate", status_code=202)
def regenerate_keyframe(video_id: str, index: int, body: RegenBody, request: Request, db: Session = Depends(_db)):
    _get(video_id, request, db)
    return _job(request, video_id, lambda s: s.regenerate_keyframe(video_id, index, prompt=body.prompt))


@router.post("/videos/{video_id}/animate", status_code=202)
def animate(video_id: str, request: Request, db: Session = Depends(_db), force: bool = False):
    v, svc = _get(video_id, request, db)
    if any(k.status != "DONE" for k in svc.keyframes(video_id)):
        raise HTTPException(409, "generate all keyframe images first")
    return _job(request, video_id, lambda s: s.animate(video_id, force=force))


@router.get("/videos/{video_id}/keyframes/{index}/image")
def keyframe_image(video_id: str, index: int, request: Request, db: Session = Depends(_db)):
    v, svc = _get(video_id, request, db)
    k = next((x for x in svc.keyframes(video_id) if x.index == index), None)
    if k is None or not k.image_path or not Path(k.image_path).is_file():
        raise HTTPException(404, "image not ready")
    return FileResponse(k.image_path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/videos/{video_id}/segments/{index}/video")
def segment_video(video_id: str, index: int, request: Request, db: Session = Depends(_db)):
    v, svc = _get(video_id, request, db)
    s = next((x for x in svc.segments(video_id) if x.index == index), None)
    if s is None or not s.video_path:
        raise HTTPException(404, "segment not ready")
    return ranged_file(Path(s.video_path), request, media_type="video/mp4")


@router.get("/videos/{video_id}/video")
def final_video(video_id: str, request: Request, db: Session = Depends(_db)):
    v, _ = _get(video_id, request, db)
    if not v.final_path or not Path(v.final_path).is_file():
        raise HTTPException(404, "final video not ready")
    return ranged_file(Path(v.final_path), request, media_type="video/mp4")


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: str, request: Request, db: Session = Depends(_db)):
    v, svc = _get(video_id, request, db)
    if request.app.state.lab_jobs.is_running(video_id):
        raise HTTPException(409, "a job is running for this video")
    svc.delete(video_id)
    return Response(status_code=204)
