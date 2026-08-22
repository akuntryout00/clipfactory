"""Batch generation: start N videos for a persona from the UI and follow progress (PRD §51)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, svc
from app.api.routes.projects import _project_out
from app.api.schemas import ProjectOut
from app.models import Batch, VideoProject
from app.projects.batch import MAX_BATCH, BatchService
from app.projects.jobs import JobBusy
from app.projects.service import ProjectService

log = logging.getLogger(__name__)
router = APIRouter(tags=["batches"])


class BatchCreate(BaseModel):
    persona_id: str
    count: int = Field(ge=1, le=MAX_BATCH)
    template_ids: list[str] | None = None
    topics: list[str] | None = Field(default=None, description="own topics, one per item; omit to let AI pick them")
    target_duration: float | None = Field(default=None, ge=15, le=25)
    name: str | None = Field(default=None, max_length=128)


def _start(request: Request, batch_id: str) -> None:
    factory = request.app.state.session_factory
    kwargs = request.app.state.service_kwargs

    def _job():
        with factory() as s:
            BatchService(s, ProjectService(s, **kwargs)).run(batch_id)

    request.app.state.jobs.submit(batch_id, _job)


@router.post("/batches", status_code=202)
def batch_create(body: BatchCreate, request: Request, db: Session = Depends(get_db)):
    bs = BatchService(db, svc(db, request))
    try:
        b = bs.create(
            persona_id=body.persona_id,
            count=body.count,
            template_ids=body.template_ids,
            topics=body.topics,
            target_duration=body.target_duration,
            name=body.name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:  # noqa: BLE001 — topic generation failed (LLM)
        raise HTTPException(502, f"could not plan the batch: {exc}")
    try:
        _start(request, b.id)
    except JobBusy as exc:
        raise HTTPException(409, str(exc))
    return bs.summary(b)


@router.get("/batches")
def batch_list(request: Request, persona: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    bs = BatchService(db, svc(db, request))
    q = select(Batch).order_by(Batch.created_at.desc()).limit(limit)
    if persona:
        q = q.where(Batch.persona_id == persona)
    return [bs.summary(b) for b in db.execute(q).scalars()]


@router.get("/batches/{batch_id}")
def batch_get(batch_id: str, request: Request, db: Session = Depends(get_db)):
    b = db.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    bs = BatchService(db, svc(db, request))
    out = bs.summary(b)
    projects = db.execute(select(VideoProject).where(VideoProject.batch_id == batch_id).order_by(VideoProject.created_at)).scalars().all()
    items: list[ProjectOut] = [_project_out(p, db) for p in projects]
    out["projects"] = [i.model_dump(exclude={"events", "scenes", "renders"}) for i in items]
    return out


@router.post("/batches/{batch_id}/cancel")
def batch_cancel(batch_id: str, request: Request, db: Session = Depends(get_db)):
    bs = BatchService(db, svc(db, request))
    try:
        return bs.summary(bs.cancel(batch_id))
    except KeyError:
        raise HTTPException(404, "batch not found")


@router.post("/batches/{batch_id}/resume", status_code=202)
def batch_resume(batch_id: str, request: Request, db: Session = Depends(get_db)):
    """Re-run the remaining DRAFT/FAILED projects of a finished or cancelled batch."""
    b = db.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    b.cancel_requested = False
    b.status = "PENDING"
    b.finished_at = None
    db.commit()
    try:
        _start(request, batch_id)
    except JobBusy as exc:
        raise HTTPException(409, str(exc))
    return BatchService(db, svc(db, request)).summary(b)
