"""Health, templates (CRUD), personas, caption styles, system status."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import assets_dir, cfg_dir, get_db, storage_dir
from app.config.loaders import list_templates, load_caption_style
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


def _mask(cfg) -> dict:
    d = cfg.model_dump()
    if d.get("voice", {}).get("voice_id"):
        d["voice"]["voice_id_set"] = True
    return d


def _persona_id_ok(pid: str) -> bool:
    import re

    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_\-]{1,40}", pid or ""))


@router.get("/personas")
def personas(request: Request, db: Session = Depends(get_db)):
    from app.personas.repo import list_personas, seed_personas_from_configs

    rows = list_personas(db)
    if not rows:  # first run: seed from configs
        seed_personas_from_configs(db, cfg_dir(request))
        rows = list_personas(db)
    return [_mask(p) for p in rows]


class PersonaDraftIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    age: int | None = Field(default=None, ge=5, le=120)
    location: str | None = Field(default=None, max_length=120)
    language: str = Field(default="en-US", max_length=16)
    about: str = Field(min_length=10, max_length=4000)


@router.post("/personas/draft")
def persona_draft(body: PersonaDraftIn, request: Request, db: Session = Depends(get_db)):
    """Wizard: a few facts + free text → complete persona proposal (not saved; POST /personas to create it)."""
    from app.llm.base import get_llm
    from app.personas.repo import persona_from_draft

    llm = request.app.state.service_kwargs.get("llm") or get_llm()
    try:
        draft = llm.draft_persona(name=body.name, age=body.age, location=body.location, language=body.language, about=body.about)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"AI draft failed: {exc}")
    cfg = persona_from_draft(db, name=body.name, age=body.age, location=body.location, language=body.language, draft=draft)
    return _mask(cfg)


@router.get("/personas/{persona_id}")
def persona_get(persona_id: str, db: Session = Depends(get_db)):
    from app.personas.repo import get_persona

    try:
        return _mask(get_persona(db, persona_id))
    except KeyError:
        raise HTTPException(404, "persona not found")


def _validate_persona(body: dict):
    from pydantic import ValidationError

    from app.schemas.configs import PersonaConfig

    body = dict(body)
    body.pop("voice_id_set", None)
    if isinstance(body.get("voice"), dict):
        body["voice"].pop("voice_id_set", None)
    if not _persona_id_ok(str(body.get("id", ""))):
        raise HTTPException(422, "persona id must be lowercase letters/digits/underscores, e.g. anna_designer")
    try:
        return PersonaConfig.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0].get("msg", "invalid persona") if exc.errors() else "invalid persona")


@router.post("/personas", status_code=201)
def persona_create(body: dict, db: Session = Depends(get_db)):
    from app.models import Persona
    from app.personas.repo import upsert_persona

    cfg = _validate_persona(body)
    if db.get(Persona, cfg.id) is not None:
        raise HTTPException(409, f"persona {cfg.id} already exists")
    return _mask(upsert_persona(db, cfg))


@router.put("/personas/{persona_id}")
def persona_update(persona_id: str, body: dict, db: Session = Depends(get_db)):
    from app.models import Persona
    from app.personas.repo import upsert_persona

    if db.get(Persona, persona_id) is None:
        raise HTTPException(404, "persona not found")
    if body.get("id") != persona_id:
        raise HTTPException(422, "persona id in body must match the URL (ids cannot be renamed)")
    return _mask(upsert_persona(db, _validate_persona(body)))


@router.delete("/personas/{persona_id}", status_code=204)
def persona_delete(persona_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import func

    from app.models import Persona
    from app.personas.repo import delete_persona

    if db.get(Persona, persona_id) is None:
        raise HTTPException(404, "persona not found")
    n_assets = db.execute(select(func.count()).select_from(Asset).where(Asset.persona_id == persona_id)).scalar_one()
    n_projects = db.execute(select(func.count()).select_from(VideoProject).where(VideoProject.persona_id == persona_id)).scalar_one()
    if n_assets or n_projects:
        raise HTTPException(409, f"persona still owns {n_assets} clips and {n_projects} projects — move or delete them first")
    delete_persona(db, persona_id)
    return Response(status_code=204)


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
