"""Health, templates (CRUD), personas, caption styles, system status."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import assets_dir, cfg_dir, get_db, storage_dir
from app.config.loaders import list_personas, list_templates, load_caption_style
from app.config.settings import get_settings
from app.models import Asset, VideoProject

log = logging.getLogger(__name__)
router = APIRouter()


# ---------- meta ----------
@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/templates")
def templates(request: Request):
    return [t.model_dump() for t in list_templates(cfg_dir(request))]


def _template_path(request: Request, tid: str) -> Path:
    import re

    if not re.fullmatch(r"[a-z0-9][a-z0-9_\-]{1,40}", tid or ""):
        raise HTTPException(422, "template id must be lowercase letters/digits/underscores, e.g. story_fast_v1")
    return cfg_dir(request) / "templates" / f"{tid}.json"


def _write_template(request: Request, body: dict, path: Path):
    from pydantic import ValidationError

    from app.schemas.configs import TemplateConfig

    try:
        tpl = TemplateConfig.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0].get("msg", "invalid template") if exc.errors() else "invalid template")
    try:
        load_caption_style(tpl.caption_style, cfg_dir(request))
    except FileNotFoundError:
        raise HTTPException(422, f"unknown caption_style {tpl.caption_style}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tpl.model_dump(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return tpl.model_dump()


@router.post("/templates", status_code=201)
def template_create(body: dict, request: Request):
    path = _template_path(request, str(body.get("id", "")))
    if path.exists():
        raise HTTPException(409, f"template {body.get('id')} already exists")
    return _write_template(request, body, path)


@router.put("/templates/{template_id}")
def template_update(template_id: str, body: dict, request: Request):
    path = _template_path(request, template_id)
    if not path.exists():
        raise HTTPException(404, "template not found")
    if body.get("id") != template_id:
        raise HTTPException(422, "template id in body must match the URL (ids cannot be renamed; create a new one instead)")
    return _write_template(request, body, path)


@router.delete("/templates/{template_id}", status_code=204)
def template_delete(template_id: str, request: Request):
    path = _template_path(request, template_id)
    if not path.exists():
        raise HTTPException(404, "template not found")
    path.unlink()
    return Response(status_code=204)


@router.get("/caption-styles")
def caption_styles(request: Request):
    return sorted(p.stem for p in (cfg_dir(request) / "captions").glob("*.json"))


@router.get("/personas")
def personas(request: Request):
    out = []
    for p in list_personas(cfg_dir(request)):
        d = p.model_dump()
        d["voice"]["voice_id"] = "***" if d["voice"]["voice_id"] else ""
        out.append(d)
    return out


@router.get("/system")
def system(request: Request, db: Session = Depends(get_db)):
    from sqlalchemy import func

    from app.renderer.ffmpeg import check_render_capabilities

    st = get_settings()
    kw = request.app.state.service_kwargs
    llm = kw.get("llm")
    voice = kw.get("voice")
    missing = check_render_capabilities()
    ffmpeg_ver = ""
    try:
        import subprocess

        ffmpeg_ver = subprocess.run([st.ffmpeg_bin, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    except Exception:  # noqa: BLE001
        ffmpeg_ver = "not found"
    return {
        "llm_provider": getattr(llm, "name", None) or st.llm_provider,
        "openai_model": st.openai_model,
        "openai_key_set": bool(st.openai_api_key),
        "voice_provider": getattr(voice, "name", None) or st.voice_provider,
        "elevenlabs_key_set": bool(st.elevenlabs_api_key),
        "elevenlabs_voice_id_set": bool(st.elevenlabs_voice_id),
        "default_persona": st.default_persona,
        "database_url": st.database_url.split("@")[-1] if "@" in st.database_url else st.database_url,
        "assets_dir": str(assets_dir(request)),
        "storage_dir": str(storage_dir(request)),
        "ffmpeg": ffmpeg_ver,
        "render_ok": not missing,
        "render_missing": missing,
        "assets_count": db.execute(select(func.count()).select_from(Asset)).scalar_one(),
        "assets_approved": db.execute(select(func.count()).select_from(Asset).where(Asset.approved.is_(True))).scalar_one(),
        "projects_count": db.execute(select(func.count()).select_from(VideoProject)).scalar_one(),
        "music_tracks": sorted(p.name for p in (storage_dir(request) / "music").glob("*.mp3"))
        if (storage_dir(request) / "music").is_dir()
        else [],
        "lab": {
            "planner": st.lab_planner,
            "image_provider": st.lab_image_provider,
            "image_model": st.openai_image_model,
            "image_size": st.openai_image_size,
            "video_provider": st.lab_video_provider,
            "video_model": st.google_video_model,
            "google_key_set": bool(st.google_api_key),
            "fal_key_set": bool(st.fal_key),
            "fal_default_model": st.lab_fal_model,
        },
    }
