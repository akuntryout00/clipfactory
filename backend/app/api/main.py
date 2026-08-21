"""FastAPI application factory + routes (PRD §47 minimum API)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Iterator

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.media import ranged_file, thumbnail_for
from app.api.schemas import (
    Accepted, AssetOut, AssetPatch, ProjectCreate, ProjectOut, SceneAssetOverride,
)
from app.assets.importer import VIDEO_EXT, import_assets, register_asset_file
from app.assets.selector import extract_query_tags, find_candidates
import json

from app.config.loaders import list_personas, list_templates, load_caption_style
from app.config.settings import get_settings
from app.models import Asset, ProjectStatus, VideoProject, VideoScene
from app.projects.jobs import InlineJobRunner, JobBusy, JobRunner
from app.projects.service import ProjectService

log = logging.getLogger(__name__)


def create_app(session_factory: sessionmaker | None = None, jobs: JobRunner | None = None,
               service_kwargs: dict | None = None, configs_dir: Path | None = None, lab_kwargs: dict | None = None) -> FastAPI:
    service_kwargs = dict(service_kwargs or {})
    lab_kwargs = dict(lab_kwargs or {})
    if service_kwargs.get("storage_dir") and "storage_dir" not in lab_kwargs:
        lab_kwargs["storage_dir"] = service_kwargs["storage_dir"]
    if configs_dir is not None:
        service_kwargs["configs_dir"] = Path(configs_dir)
    cfg_dir: Path = Path(configs_dir) if configs_dir is not None else get_settings().configs_dir

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if session_factory is None:
            from app.db import get_sessionmaker, init_db

            init_db()
            app.state.session_factory = get_sessionmaker()
            get_settings().ensure_dirs()
            _seed_configs(app.state.session_factory)
        else:
            app.state.session_factory = session_factory
        app.state.jobs = jobs or JobRunner()
        app.state.lab_jobs = jobs or JobRunner()  # separate runner for the isolated AI Lab module
        app.state.service_kwargs = service_kwargs
        app.state.lab_kwargs = lab_kwargs
        yield
        app.state.jobs.shutdown()
        app.state.lab_jobs.shutdown()

    app = FastAPI(title="TikTok Content Factory", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Range", "Accept-Ranges"])

    def storage_dir(request: Request) -> Path:
        return Path(request.app.state.service_kwargs.get("storage_dir") or get_settings().storage_dir)

    def assets_dir(request: Request) -> Path:
        return Path(request.app.state.service_kwargs.get("assets_dir") or get_settings().assets_dir)

    def get_db(request: Request) -> Iterator[Session]:
        s: Session = request.app.state.session_factory()
        try:
            yield s
        finally:
            s.close()

    def svc(db: Session, request: Request) -> ProjectService:
        return ProjectService(db, **request.app.state.service_kwargs)

    def run_job(request: Request, project_id: str, action: str, op: Callable[[ProjectService], None]) -> Accepted:
        factory: sessionmaker = request.app.state.session_factory
        kwargs = request.app.state.service_kwargs

        def _job():
            with factory() as s:
                try:
                    op(ProjectService(s, **kwargs))
                except Exception:  # noqa: BLE001 — already persisted as FAILED by the service
                    log.exception("%s failed for %s", action, project_id)

        try:
            request.app.state.jobs.submit(project_id, _job)
        except JobBusy as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
        return Accepted(project_id=project_id, action=action)

    # ---------- meta ----------
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/templates")
    def templates():
        return [t.model_dump() for t in list_templates(cfg_dir)]

    def _template_path(tid: str) -> Path:
        import re

        if not re.fullmatch(r"[a-z0-9][a-z0-9_\-]{1,40}", tid or ""):
            raise HTTPException(422, "template id must be lowercase letters/digits/underscores, e.g. story_fast_v1")
        return cfg_dir / "templates" / f"{tid}.json"

    def _write_template(body: dict, path: Path):
        from pydantic import ValidationError

        from app.schemas.configs import TemplateConfig

        try:
            tpl = TemplateConfig.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors()[0].get("msg", "invalid template") if exc.errors() else "invalid template")
        try:
            load_caption_style(tpl.caption_style, cfg_dir)
        except FileNotFoundError:
            raise HTTPException(422, f"unknown caption_style {tpl.caption_style}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tpl.model_dump(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return tpl.model_dump()

    @app.post("/templates", status_code=201)
    def template_create(body: dict):
        path = _template_path(str(body.get("id", "")))
        if path.exists():
            raise HTTPException(409, f"template {body.get('id')} already exists")
        return _write_template(body, path)

    @app.put("/templates/{template_id}")
    def template_update(template_id: str, body: dict):
        path = _template_path(template_id)
        if not path.exists():
            raise HTTPException(404, "template not found")
        if body.get("id") != template_id:
            raise HTTPException(422, "template id in body must match the URL (ids cannot be renamed; create a new one instead)")
        return _write_template(body, path)

    @app.delete("/templates/{template_id}", status_code=204)
    def template_delete(template_id: str):
        path = _template_path(template_id)
        if not path.exists():
            raise HTTPException(404, "template not found")
        path.unlink()
        return Response(status_code=204)

    @app.get("/caption-styles")
    def caption_styles():
        return sorted(p.stem for p in (cfg_dir / "captions").glob("*.json"))

    @app.get("/personas")
    def personas():
        out = []
        for p in list_personas(cfg_dir):
            d = p.model_dump()
            d["voice"]["voice_id"] = "***" if d["voice"]["voice_id"] else ""
            out.append(d)
        return out

    @app.get("/system")
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
            "music_tracks": sorted(p.name for p in (storage_dir(request) / "music").glob("*.mp3")) if (storage_dir(request) / "music").is_dir() else [],
            "lab": {
                "planner": st.lab_planner, "image_provider": st.lab_image_provider, "image_model": st.openai_image_model,
                "image_size": st.openai_image_size, "video_provider": st.lab_video_provider, "video_model": st.google_video_model,
                "google_key_set": bool(st.google_api_key),
            },
        }

    # ---------- assets ----------
    @app.get("/assets", response_model=list[AssetOut])
    def assets(db: Session = Depends(get_db), approved: bool | None = None):
        q = select(Asset).order_by(Asset.id)
        if approved is not None:
            q = q.where(Asset.approved.is_(approved))
        return list(db.execute(q).scalars())

    @app.get("/assets/search")
    def assets_search(q: str, limit: int = 10, db: Session = Depends(get_db)):
        tags = extract_query_tags(q.split())
        return [c.as_dict() for c in find_candidates(db, tags, limit=limit)]

    @app.post("/assets/import")
    def assets_import(request: Request, db: Session = Depends(get_db), approve_unseeded: bool = False):
        assets_dir = Path(request.app.state.service_kwargs.get("assets_dir") or get_settings().assets_dir)
        rep = import_assets(db, assets_dir, approve_unseeded=approve_unseeded)
        return {"created": rep.created, "updated": rep.updated, "errors": rep.errors}

    @app.post("/assets/enrich")
    def assets_enrich(request: Request, db: Session = Depends(get_db), overwrite: bool = False):
        from app.assets.enrich import enrich_library
        from app.llm.base import get_llm

        llm = request.app.state.service_kwargs.get("llm") or get_llm()
        return {"enriched": enrich_library(db, llm, overwrite=overwrite)}

    @app.post("/assets/analyze")
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
        return {**analysis.model_dump(), "duration": round(meta.duration, 3), "width": meta.width, "height": meta.height,
                "fps": round(meta.fps, 3), "usable_start": round(margin, 2), "usable_end": round(max(meta.duration - margin, margin), 2),
                "frames_analyzed": len(frames), "categories": cats}

    @app.post("/assets/upload", response_model=AssetOut, status_code=201)
    async def asset_upload(request: Request, response: Response, file: UploadFile = File(...), category: str = Form(...),
                           description: str | None = Form(None), tags: str | None = Form(None), approved: bool = Form(False),
                           usable_start: float | None = Form(None), usable_end: float | None = Form(None),
                           action: str | None = Form(None), location: str | None = Form(None), shot: str | None = Form(None),
                           mood: str | None = Form(None), quality_score: float | None = Form(None),
                           enrich: bool = True, db: Session = Depends(get_db)):
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
            asset = register_asset_file(db, assets_dir(request), rel, description=description or None,
                                        tags=(tags or "").split(","), approved=approved,
                                        usable_start=usable_start, usable_end=usable_end,
                                        action=action or None, location=location or None, shot=shot or None, mood=mood or None,
                                        quality_score=quality_score if quality_score is not None else 0.8)
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

    @app.delete("/assets/{asset_id}", status_code=204)
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

    @app.get("/assets/{asset_id}/file")
    def asset_file(asset_id: str, request: Request, db: Session = Depends(get_db)):
        a = db.get(Asset, asset_id)
        if a is None:
            raise HTTPException(404, "asset not found")
        return ranged_file(assets_dir(request) / a.file, request, media_type="video/mp4")

    @app.get("/assets/{asset_id}/thumbnail")
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

    @app.patch("/assets/{asset_id}", response_model=AssetOut)
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

    # ---------- projects ----------
    def _project_out(p: VideoProject, db: Session) -> ProjectOut:
        scenes = db.execute(select(VideoScene).where(VideoScene.project_id == p.id, VideoScene.plan_version == p.plan_version)
                            .order_by(VideoScene.order)).scalars().all()
        out = ProjectOut.model_validate(p, from_attributes=True)
        out.scenes = [dict(order=s.order, section=s.section, start_time=s.start_time, end_time=s.end_time, asset_id=s.asset_id,
                           asset_start_time=s.asset_start_time, overlay_text=s.overlay_text, intent=s.intent) for s in scenes]
        out.renders = [r for r in sorted(p.renders, key=lambda r: r.version)]
        out.events = [e for e in sorted(p.events, key=lambda e: e.created_at)][-50:]
        if p.current_render_id and p.status in (ProjectStatus.READY.value, ProjectStatus.APPROVED.value):
            out.video_url = f"/projects/{p.id}/video"
        return out

    @app.post("/projects", response_model=ProjectOut, status_code=201)
    def create_project(body: ProjectCreate, request: Request, db: Session = Depends(get_db)):
        try:
            p = svc(db, request).create_project(topic=body.topic, template_id=body.template_id, persona_id=body.persona_id,
                                                target_duration=body.target_duration)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return _project_out(p, db)

    @app.get("/projects", response_model=list[ProjectOut])
    def list_projects(request: Request, db: Session = Depends(get_db), limit: int = 50):
        return [_project_out(p, db) for p in svc(db, request).list_projects(limit)]

    @app.get("/projects/{project_id}", response_model=ProjectOut)
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

    @app.post("/projects/{project_id}/generate", response_model=Accepted, status_code=202)
    def generate(project_id: str, request: Request, db: Session = Depends(get_db)):
        _require(project_id, db)
        return run_job(request, project_id, "generate", lambda s: s.generate(project_id))

    @app.post("/projects/{project_id}/regenerate-script", response_model=Accepted, status_code=202)
    def regenerate_script(project_id: str, request: Request, db: Session = Depends(get_db)):
        _require(project_id, db)
        return run_job(request, project_id, "regenerate-script", lambda s: s.regenerate_script(project_id))

    @app.post("/projects/{project_id}/change-assets", response_model=Accepted, status_code=202)
    def change_assets(project_id: str, request: Request, db: Session = Depends(get_db)):
        p = _require(project_id, db)
        if p.plan_version == 0:
            raise HTTPException(409, "project has no plan yet — run generate first")
        return run_job(request, project_id, "change-assets", lambda s: s.change_assets(project_id))

    @app.post("/projects/{project_id}/render", response_model=Accepted, status_code=202)
    def render_again(project_id: str, request: Request, db: Session = Depends(get_db)):
        p = _require(project_id, db)
        if p.plan_version == 0:
            raise HTTPException(409, "project has no plan yet — run generate first")
        return run_job(request, project_id, "render-again", lambda s: s.render_again(project_id))

    @app.post("/projects/{project_id}/retry", response_model=Accepted, status_code=202)
    def retry(project_id: str, request: Request, db: Session = Depends(get_db)):
        _require(project_id, db)
        return run_job(request, project_id, "retry", lambda s: s.retry(project_id))

    @app.post("/projects/{project_id}/approve", response_model=ProjectOut)
    def approve(project_id: str, request: Request, db: Session = Depends(get_db)):
        _require(project_id, db)
        try:
            p = svc(db, request).approve(project_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return _project_out(p, db)

    @app.delete("/projects/{project_id}", status_code=204)
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

    @app.get("/projects/{project_id}/artifacts")
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
        voices = [{"version": v.version, "script_version": v.script_version, "duration": v.duration, "provider": v.provider,
                   "url": f"/projects/{project_id}/voices/{v.version}/audio"} for v in sorted(p.voices, key=lambda v: v.version)]
        renders = [{"id": r.id, "version": r.version, "plan_version": r.plan_version, "voice_version": r.voice_version, "status": r.status,
                    "qc": r.qc, "error": r.error, "created_at": r.created_at, "seed": r.seed,
                    "url": f"/projects/{project_id}/renders/{r.version}/video" if r.status == "DONE" else None}
                   for r in sorted(p.renders, key=lambda r: r.version)]
        return {"scripts": scripts, "voices": voices, "plans": plans, "renders": renders}

    @app.get("/projects/{project_id}/voice")
    def project_voice(project_id: str, request: Request, db: Session = Depends(get_db)):
        p = _require(project_id, db)
        if p.voice_version == 0:
            raise HTTPException(404, "no voice yet")
        return ranged_file(storage_dir(request) / "projects" / project_id / f"voice_v{p.voice_version}.mp3", request, media_type="audio/mpeg")

    @app.get("/projects/{project_id}/voices/{version}/audio")
    def project_voice_version(project_id: str, version: int, request: Request, db: Session = Depends(get_db)):
        _require(project_id, db)
        return ranged_file(storage_dir(request) / "projects" / project_id / f"voice_v{version}.mp3", request, media_type="audio/mpeg")

    @app.get("/projects/{project_id}/renders/{version}/video")
    def project_render_video(project_id: str, version: int, request: Request, db: Session = Depends(get_db)):
        _require(project_id, db)
        return ranged_file(storage_dir(request) / "renders" / project_id / f"render_v{version}.mp4", request, media_type="video/mp4")

    @app.get("/projects/{project_id}/plan")
    def get_plan(project_id: str, request: Request, db: Session = Depends(get_db)):
        p = _require(project_id, db)
        if p.plan_version == 0:
            raise HTTPException(404, "no plan yet")
        return svc(db, request).load_plan(project_id, p.plan_version).model_dump()

    @app.get("/projects/{project_id}/video")
    def get_video(project_id: str, request: Request, db: Session = Depends(get_db)):
        p = _require(project_id, db)
        path = svc(db, request).project_dir(project_id) / "final.mp4"
        if not p.current_render_id or not path.is_file():
            raise HTTPException(404, "no render available")
        return ranged_file(path, request, media_type="video/mp4")

    @app.get("/projects/{project_id}/scenes/{order}/suggestions")
    def scene_suggestions(project_id: str, order: int, request: Request, db: Session = Depends(get_db)):
        p = _require(project_id, db)
        if p.plan_version == 0:
            raise HTTPException(404, "no plan yet")
        try:
            return svc(db, request).suggest_assets(project_id, order)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(404, f"scene not found: {exc}")

    @app.post("/projects/{project_id}/scenes/{order}/asset", response_model=Accepted, status_code=202)
    def scene_override(project_id: str, order: int, body: SceneAssetOverride, request: Request, db: Session = Depends(get_db)):
        p = _require(project_id, db)
        if p.plan_version == 0:
            raise HTTPException(409, "no plan yet")
        if db.get(Asset, body.asset_id) is None:
            raise HTTPException(404, "asset not found")
        return run_job(request, project_id, "scene-override", lambda s: s.override_scene_asset(project_id, order, body.asset_id))

    from app.lab.api import router as lab_router

    app.include_router(lab_router)
    return app


def _seed_configs(factory: sessionmaker) -> None:
    """Mirror persona/template configs into the DB (PRD §27) — config files stay the source of truth."""
    from app.models import Persona, Template

    with factory() as s:
        for p in list_personas():
            row = s.get(Persona, p.id) or Persona(id=p.id, name=p.name, config={})
            row.name, row.config = p.name, p.model_dump(exclude={"voice"})
            s.add(row)
        for t in list_templates():
            row = s.get(Template, t.id) or Template(id=t.id, name=t.name, config={})
            row.name, row.config = t.name, t.model_dump()
            s.add(row)
        s.commit()


app = create_app()
