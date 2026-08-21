"""AI-assisted semantic metadata enrichment from clip descriptions (PRD §8)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.models import Asset
from app.schemas.pipeline import AssetEnrichOutput

_DEFAULT_MOODS = {None, "", "neutral"}


def enrich_library(
    session: Session, llm: LLMProvider, overwrite: bool = False, only_unapproved: bool = False, asset_ids: list[str] | None = None
) -> int:
    q = select(Asset).order_by(Asset.id)
    if only_unapproved:
        q = q.where(Asset.approved.is_(False))
    if asset_ids:
        q = q.where(Asset.id.in_(asset_ids))
    rows = list(session.execute(q).scalars())
    if not rows:
        return 0
    payload = [
        {
            "asset_id": a.id,
            "file": a.file,
            "description": a.description or "",
            "tags": list(a.tags or []),
            "action": a.action,
            "location": a.location,
            "shot": a.shot,
        }
        for a in rows
    ]
    out = llm.enrich_assets(assets=payload)
    return apply_enrichment(session, out, overwrite=overwrite)


def apply_enrichment(session: Session, out: AssetEnrichOutput, overwrite: bool = False) -> int:
    n = 0
    for e in out.assets:
        a = session.get(Asset, e.asset_id)
        if a is None:
            continue
        merged = list(dict.fromkeys([t.lower().strip() for t in (a.tags or [])] + [t.lower().strip() for t in e.tags if t.strip()]))
        a.tags = merged
        for field, value in (("action", e.action), ("location", e.location), ("shot", e.shot)):
            if value and (overwrite or not getattr(a, field)):
                setattr(a, field, value)
        if e.mood and (overwrite or a.mood in _DEFAULT_MOODS):
            a.mood = e.mood
        n += 1
    session.commit()
    return n
