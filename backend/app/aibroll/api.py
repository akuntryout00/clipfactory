"""AI B-roll API: jobs (create/list/get/retry/delete/media), estimate, providers, persona reference photo."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.aibroll.service import DEFAULT_PROVIDER, MAX_SECONDS, MIN_SECONDS, AiBrollService, estimate, persona_image_path, save_persona_image
from app.api.deps import assets_dir, get_db, storage_dir
from app.lab.providers import list_video_providers
from app.models import AiBrollJob
from app.projects.jobs import JobBusy

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ai-broll", tags=["ai-broll"])


def _svc(request: Request, db: Session) -> AiBrollService:
    kw = request.app.state.lab_kwargs
    return AiBrollService(
        db, storage_dir=storage_dir(request), assets_dir=assets_dir(request), image=kw.get("image"), video=kw.get("video")
    )


def _out(j: AiBrollJob) -> dict:
    return {
        "id": j.id,
        "persona_id": j.persona_id,
        "shotlist_item_id": j.shotlist_item_id,
        "title": j.title,
        "prompt": j.prompt,
        "category": j.category,
        "shot": j.shot,
        "action": j.action,
        "location": j.location,
        "mood": j.mood,
        "tags": j.tags or [],
        "seconds": j.seconds,
        "video_provider": j.video_provider,
        "use_reference": bool(j.use_reference),
        "status": j.status,
        "stage_message": j.stage_message,
        "error": j.error,
        "asset_id": j.asset_id,
        "keyframe_url": f"/ai-broll/jobs/{j.id}/keyframe" if j.keyframe_path else None,
        "video_url": f"/ai-broll/jobs/{j.id}/video" if j.video_path else None,
        "created_at": j.created_at,
        "updated_at": j.updated_at,
    }


def _start(request: Request, job_id: str) -> None:
    factory = request.app.state.session_factory
    kw = request.app.state.lab_kwargs
    sd, ad = storage_dir(request), assets_dir(request)

    def _job():
        with factory() as s:
            try:
                AiBrollService(s, storage_dir=sd, assets_dir=ad, image=kw.get("image"), video=kw.get("video")).run(job_id)
            except Exception:  # noqa: BLE001 — persisted on the job
                log.exception("ai b-roll %s failed", job_id)

    request.app.state.lab_jobs.submit(job_id, _job)


@router.get("/providers")
def providers():
    """Video models usable for B-roll (single start frame)."""
    return [p for p in list_video_providers() if p["id"] != "fake" or True]


@router.get("/estimate")
def estimate_route(provider: str = DEFAULT_PROVIDER, seconds: int = 5, with_reference: bool = False):
    try:
        return estimate(provider, seconds, with_reference)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/jobs", status_code=202)
async def job_create(
    request: Request,
    persona_id: str = Form(...),
    prompt: str = Form(..., min_length=5, max_length=2000),
    title: str | None = Form(None),
    category: str = Form("ai"),
    shot: str | None = Form(None),
    action: str | None = Form(None),
    location: str | None = Form(None),
    mood: str | None = Form(None),
    tags: str | None = Form(None),
    seconds: int = Form(5),
    video_provider: str | None = Form(None),
    use_reference: bool = Form(False),
    shotlist_item_id: str | None = Form(None),
    reference: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    if not (MIN_SECONDS <= seconds <= MAX_SECONDS):
        raise HTTPException(422, f"seconds must be between {MIN_SECONDS} and {MAX_SECONDS}")
    ref_bytes = await reference.read() if reference is not None else None
    try:
        j = _svc(request, db).create(
            persona_id=persona_id,
            prompt=prompt,
            title=title,
            category=category,
            shot=shot,
            action=action,
            location=location,
            mood=mood,
            tags=[t for t in (tags or "").split(",") if t.strip()],
            seconds=seconds,
            video_provider=video_provider,
            use_reference=use_reference,
            reference_bytes=ref_bytes,
            shotlist_item_id=shotlist_item_id,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        _start(request, j.id)
    except JobBusy as exc:
        raise HTTPException(409, str(exc))
    db.refresh(j)
    return _out(j)


@router.get("/jobs")
def jobs_list(request: Request, persona: str | None = None, db: Session = Depends(get_db)):
    return [_out(j) for j in _svc(request, db).list(persona)]


@router.get("/jobs/{job_id}")
def job_get(job_id: str, db: Session = Depends(get_db)):
    j = db.get(AiBrollJob, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return _out(j)


@router.post("/jobs/{job_id}/retry", status_code=202)
def job_retry(job_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        j = _svc(request, db).retry(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")
    try:
        _start(request, j.id)
    except JobBusy as exc:
        raise HTTPException(409, str(exc))
    return _out(j)


@router.delete("/jobs/{job_id}", status_code=204)
def job_delete(job_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        _svc(request, db).delete(job_id)
    except KeyError:
        raise HTTPException(404, "job not found")


@router.get("/jobs/{job_id}/keyframe")
def job_keyframe(job_id: str, db: Session = Depends(get_db)):
    j = db.get(AiBrollJob, job_id)
    if j is None or not j.keyframe_path or not Path(j.keyframe_path).is_file():
        raise HTTPException(404, "no keyframe")
    return FileResponse(j.keyframe_path, media_type="image/png")


@router.get("/jobs/{job_id}/video")
def job_video(job_id: str, db: Session = Depends(get_db)):
    j = db.get(AiBrollJob, job_id)
    if j is None or not j.video_path or not Path(j.video_path).is_file():
        raise HTTPException(404, "no video")
    return FileResponse(j.video_path, media_type="video/mp4")


# ---------------- persona reference photo
@router.get("/personas/{persona_id}/image")
def persona_image_get(persona_id: str, request: Request):
    p = persona_image_path(storage_dir(request), persona_id)
    if not p.is_file():
        raise HTTPException(404, "no photo for this persona")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.put("/personas/{persona_id}/image")
async def persona_image_put(persona_id: str, request: Request, file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "image too large (max 15 MB)")
    try:
        save_persona_image(storage_dir(request), persona_id, data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"not an image I can read: {exc}")
    return {"persona_id": persona_id, "image_url": f"/ai-broll/personas/{persona_id}/image"}


@router.delete("/personas/{persona_id}/image", status_code=204)
def persona_image_delete(persona_id: str, request: Request):
    p = persona_image_path(storage_dir(request), persona_id)
    p.unlink(missing_ok=True)


@router.get("/personas/{persona_id}/image/status")
def persona_image_status(persona_id: str, request: Request):
    p = persona_image_path(storage_dir(request), persona_id)
    return {
        "persona_id": persona_id,
        "has_image": p.is_file(),
        "image_url": f"/ai-broll/personas/{persona_id}/image" if p.is_file() else None,
    }
