"""FastAPI application factory + routes (PRD §47 minimum API)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Iterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import (
    Accepted, AssetOut, AssetPatch, ProjectCreate, ProjectOut, SceneAssetOverride,
)
from app.assets.importer import import_assets
from app.assets.selector import extract_query_tags, find_candidates
from app.config.loaders import list_personas, list_templates
from app.config.settings import get_settings
from app.models import Asset, ProjectStatus, VideoProject, VideoScene
from app.projects.jobs import InlineJobRunner, JobBusy, JobRunner
from app.projects.service import ProjectService

log = logging.getLogger(__name__)


def create_app(session_factory: sessionmaker | None = None, jobs: JobRunner | None = None,
               service_kwargs: dict | None = None) -> FastAPI:
    service_kwargs = service_kwargs or {}

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
        app.state.service_kwargs = service_kwargs
        yield
        app.state.jobs.shutdown()

    app = FastAPI(title="TikTok Content Factory", version="0.1.0", lifespan=lifespan)

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
        return [t.model_dump() for t in list_templates()]

    @app.get("/personas")
    def personas():
        out = []
        for p in list_personas():
            d = p.model_dump()
            d["voice"]["voice_id"] = "***" if d["voice"]["voice_id"] else ""
            out.append(d)
        return out

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
        return FileResponse(path, media_type="video/mp4", filename=f"{project_id}.mp4")

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
