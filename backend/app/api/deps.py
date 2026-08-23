"""Shared FastAPI dependencies/helpers for the routers (app state: session_factory, jobs, service_kwargs, configs_dir)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import Accepted
from app.config.settings import get_settings
from app.projects.jobs import JobBusy
from app.projects.service import ProjectService

log = logging.getLogger(__name__)


def get_db(request: Request) -> Iterator[Session]:
    s: Session = request.app.state.session_factory()
    # let helpers that only get the session (e.g. _project_out) find the configured dirs
    s.info.update(
        {k: v for k, v in request.app.state.service_kwargs.items() if k in ("storage_dir", "assets_dir", "configs_dir", "fonts_dir")}
    )
    try:
        yield s
    finally:
        s.close()


def svc(db: Session, request: Request) -> ProjectService:
    return ProjectService(db, **request.app.state.service_kwargs)


def storage_dir(request: Request) -> Path:
    return Path(request.app.state.service_kwargs.get("storage_dir") or get_settings().storage_dir)


def assets_dir(request: Request) -> Path:
    return Path(request.app.state.service_kwargs.get("assets_dir") or get_settings().assets_dir)


def cfg_dir(request: Request) -> Path:
    return Path(request.app.state.configs_dir)


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
