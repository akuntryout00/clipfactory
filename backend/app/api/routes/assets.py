"""B-roll asset library: list/search/import/upload/analyze/enrich/patch/delete/media."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import assets_dir, get_db, storage_dir
from app.api.media import ranged_file, thumbnail_for
from app.api.schemas import AssetOut, AssetPatch
from app.assets.importer import VIDEO_EXT, import_assets, register_asset_file
from app.assets.selector import extract_query_tags, find_candidates
from app.config.settings import get_settings
from app.models import Asset

log = logging.getLogger(__name__)
router = APIRouter()


# ---------- assets ----------
@router.get("/assets", response_model=list[AssetOut])
def assets(db: Session = Depends(get_db), approved: bool | None = None):
    q = select(Asset).order_by(Asset.id)
    if approved is not None:
        q = q.where(Asset.approved.is_(approved))
    return list(db.execute(q).scalars())


@router.get("/assets/search")
def assets_search(q: str, limit: int = 10, db: Session = Depends(get_db)):
    tags = extract_query_tags(q.split())
    return [c.as_dict() for c in find_candidates(db, tags, limit=limit)]


@router.post("/assets/import")
def assets_import(request: Request, db: Session = Depends(get_db), approve_unseeded: bool = False):
    assets_dir = Path(request.app.state.service_kwargs.get("assets_dir") or get_settings().assets_dir)
    rep = import_assets(db, assets_dir, approve_unseeded=approve_unseeded)
    return {"created": rep.created, "updated": rep.updated, "errors": rep.errors}


@router.post("/assets/enrich")
def assets_enrich(request: Request, db: Session = Depends(get_db), overwrite: bool = False):
    from app.assets.enrich import enrich_library
    from app.llm.base import get_llm

    llm = request.app.state.service_kwargs.get("llm") or get_llm()
    return {"enriched": enrich_library(db, llm, overwrite=overwrite)}


@router.post("/assets/analyze")
async def asset_analyze(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """AI autocomplete: sample frames from the uploaded video and let the LLM fill every metadata field. Nothing is saved."""
    import shutil
    import tempfile

    from sqlalchemy import distinct

    from app.assets.frames import extract_frames
    from app.assets.metadata import probe_video
    from app.llm.base import get_llm

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXT:
        raise HTTPException(400, f"unsupported file type {suffix or '(none)'}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / f"clip{suffix}"
        with tmp.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            meta = probe_video(tmp)
            frames = extract_frames(tmp, n=6, width=512)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"could not read video: {exc}")
        if not frames:
            raise HTTPException(400, "could not extract frames from the video")
        cats = sorted({f.split("/")[0] for (f,) in db.execute(select(distinct(Asset.file))).all()})
        llm = request.app.state.service_kwargs.get("llm") or get_llm()
        try:
            analysis = llm.analyze_clip(frames=frames, filename=file.filename or "clip", duration=meta.duration, categories=cats)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"AI analysis failed: {exc}")
    margin = min(0.2, meta.duration * 0.05)
    return {
        **analysis.model_dump(),
        "duration": round(meta.duration, 3),
        "width": meta.width,
        "height": meta.height,
        "fps": round(meta.fps, 3),
        "usable_start": round(margin, 2),
        "usable_end": round(max(meta.duration - margin, margin), 2),
        "frames_analyzed": len(frames),
        "categories": cats,
    }


@router.post("/assets/upload", response_model=AssetOut, status_code=201)
async def asset_upload(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    category: str = Form(...),
    description: str | None = Form(None),
    tags: str | None = Form(None),
    approved: bool = Form(False),
    usable_start: float | None = Form(None),
    usable_end: float | None = Form(None),
    action: str | None = Form(None),
    location: str | None = Form(None),
    shot: str | None = Form(None),
    mood: str | None = Form(None),
    quality_score: float | None = Form(None),
    enrich: bool = True,
    db: Session = Depends(get_db),
):
    """Add a single B-roll clip: saves under assets/<category>/ (never overwrites), probes it, creates the asset row,
    then (by default) runs AI enrichment for just this clip so it is searchable right away."""
    import re
    import shutil

    raw_cat = (category or "").strip().lower()
    cat = re.sub(r"[^a-z0-9_\-]", "", raw_cat)
    if not cat or cat != raw_cat or cat.startswith("_"):
        raise HTTPException(400, "category must be a simple folder name, e.g. desk, phone, walking")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXT:
        raise HTTPException(400, f"unsupported file type {suffix or '(none)'}; allowed: {', '.join(sorted(VIDEO_EXT))}")
    stem = re.sub(r"[^a-z0-9]+", "_", Path(file.filename or "clip").stem.lower()).strip("_") or "clip"
    folder = assets_dir(request) / cat
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{stem}{suffix}"
    n = 2
    while dest.exists():
        dest = folder / f"{stem}_{n}{suffix}"
        n += 1
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    rel = dest.relative_to(assets_dir(request)).as_posix()
    try:
        asset = register_asset_file(
            db,
            assets_dir(request),
            rel,
            description=description or None,
            tags=(tags or "").split(","),
            approved=approved,
            usable_start=usable_start,
            usable_end=usable_end,
            action=action or None,
            location=location or None,
            shot=shot or None,
            mood=mood or None,
            quality_score=quality_score if quality_score is not None else 0.8,
        )
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"could not read video: {exc}")
    enriched = False
    if enrich:
        try:
            from app.assets.enrich import enrich_library
            from app.llm.base import get_llm

            llm = request.app.state.service_kwargs.get("llm") or get_llm()
            enriched = enrich_library(db, llm, asset_ids=[asset.id]) > 0
            db.refresh(asset)
        except Exception as exc:  # noqa: BLE001 — enrichment is best-effort; the upload itself succeeded
            log.warning("auto-enrich failed for %s: %s", asset.id, exc)
            response.headers["X-Enrich-Error"] = str(exc)[:200]
    response.headers["X-Enriched"] = "true" if enriched else "false"
    return asset


@router.delete("/assets/{asset_id}", status_code=204)
def asset_delete(asset_id: str, request: Request, db: Session = Depends(get_db), keep_file: bool = False):
    """Remove a clip from the library (and from disk unless keep_file=true). Past projects keep their renders."""
    a = db.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "asset not found")
    path = assets_dir(request) / a.file
    from sqlalchemy import delete as sa_delete

    from app.models import AssetUsage

    db.execute(sa_delete(AssetUsage).where(AssetUsage.asset_id == asset_id))  # usage history goes with the clip
    db.delete(a)
    db.commit()
    if not keep_file:
        path.unlink(missing_ok=True)
    (storage_dir(request) / "thumbs" / "assets" / f"{asset_id}.jpg").unlink(missing_ok=True)
    return Response(status_code=204)


@router.get("/assets/{asset_id}/file")
def asset_file(asset_id: str, request: Request, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "asset not found")
    return ranged_file(assets_dir(request) / a.file, request, media_type="video/mp4")


@router.get("/assets/{asset_id}/thumbnail")
def asset_thumbnail(asset_id: str, request: Request, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "asset not found")
    src = assets_dir(request) / a.file
    if not src.is_file():
        raise HTTPException(404, "asset file missing")
    at = min(max(a.usable_start or 0.5, 0.3), max((a.duration or 1) - 0.2, 0.3))
    path = thumbnail_for(src, storage_dir(request) / "thumbs" / "assets", a.id, at=at)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def asset_patch(asset_id: str, patch: AssetPatch, db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "asset not found")
    for k, v in patch.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    if a.usable_end and a.usable_end > a.duration:
        a.usable_end = a.duration
    db.commit()
    db.refresh(a)
    return a
