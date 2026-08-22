"""FastAPI application factory. Routes live in app/api/routes/* (content factory) and app/lab/api.py (AI Lab)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from app.config.loaders import list_templates
from app.config.settings import get_settings
from app.projects.jobs import JobRunner


def create_app(
    session_factory: sessionmaker | None = None,
    jobs: JobRunner | None = None,
    service_kwargs: dict | None = None,
    configs_dir: Path | None = None,
    lab_kwargs: dict | None = None,
) -> FastAPI:
    service_kwargs = dict(service_kwargs or {})
    lab_kwargs = dict(lab_kwargs or {})
    if configs_dir is not None:
        service_kwargs["configs_dir"] = Path(configs_dir)
    if service_kwargs.get("storage_dir") and "storage_dir" not in lab_kwargs:
        lab_kwargs["storage_dir"] = service_kwargs["storage_dir"]
    cfg_dir: Path = Path(configs_dir) if configs_dir is not None else get_settings().configs_dir

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if session_factory is None:
            from app.db import get_sessionmaker, init_db

            init_db()
            app.state.session_factory = get_sessionmaker()
            # keys/models saved from the web UI override .env for every later get_settings() call
            from app.config.store import apply_from_db

            with app.state.session_factory() as s:
                apply_from_db(s)
            get_settings().ensure_dirs()
            _seed_configs(app.state.session_factory, cfg_dir)
        else:
            app.state.session_factory = session_factory
        app.state.jobs = jobs or JobRunner()
        app.state.lab_jobs = jobs or JobRunner()  # separate runner for the isolated AI Lab module
        app.state.service_kwargs = service_kwargs
        app.state.lab_kwargs = lab_kwargs
        app.state.configs_dir = cfg_dir
        yield
        app.state.jobs.shutdown()
        app.state.lab_jobs.shutdown()

    app = FastAPI(title="ClipFactory", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Range", "Accept-Ranges"]
    )

    from app.api.routes import assets, batches, meta, projects, shotlist
    from app.lab.api import router as lab_router

    app.include_router(meta.router)
    app.include_router(assets.router)
    app.include_router(projects.router)
    app.include_router(batches.router)
    app.include_router(shotlist.router)
    app.include_router(lab_router)
    return app


def _seed_configs(factory: sessionmaker, cfg_dir: Path) -> None:
    """Personas: seed DB from configs/personas/*.json once (DB is the source of truth afterwards).
    Templates: mirrored into the DB for reference (config files stay the source of truth)."""
    from app.models import Template
    from app.personas.repo import seed_personas_from_configs

    with factory() as s:
        seed_personas_from_configs(s, cfg_dir)
        for t in list_templates(cfg_dir):
            row = s.get(Template, t.id) or Template(id=t.id, name=t.name, config={})
            row.name, row.config = t.name, t.model_dump()
            s.add(row)
        s.commit()


app = create_app()
