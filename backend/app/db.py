"""Database engine/session helpers (SQLAlchemy 2.0)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        kwargs = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)
    from app.lab import models as lab_models  # noqa: F401  (AI Lab tables, isolated module)

    Base.metadata.create_all(get_engine())
    _ensure_columns(get_engine())


def _ensure_columns(engine) -> None:
    """Tiny forward-only migration: add columns that newer code expects to tables created by older versions."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    wanted = {
        "lab_segments": {"provider_ref": "VARCHAR(256)", "last_edit": "TEXT", "version": "INTEGER DEFAULT 0"},
        "lab_videos": {"video_provider": "VARCHAR(64)"},
        "assets": {"persona_id": "VARCHAR(64)"},
        "video_projects": {"caption_overrides": "JSON", "batch_id": "VARCHAR(64)"},
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


@contextmanager
def session_scope() -> Iterator[Session]:
    s = get_sessionmaker()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()
