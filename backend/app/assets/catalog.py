"""Library-aware helpers: compact catalog summary for the planner and candidate sizing."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset

SMALL_LIBRARY = 60


def candidate_limit_for(n_approved: int) -> int:
    """Small library → hand the LLM the whole catalog (PRD §9); large → top-15 after filtering."""
    return n_approved if n_approved <= SMALL_LIBRARY else 15


def library_summary(session: Session, max_listing: int = SMALL_LIBRARY) -> str:
    assets = list(session.execute(select(Asset).where(Asset.approved.is_(True)).order_by(Asset.id)).scalars())
    n = len(assets)
    if n == 0:
        return "LIBRARY: empty"
    cats = Counter(a.file.split("/")[0] for a in assets)
    actions = Counter(a.action for a in assets if a.action)
    locs = Counter(a.location for a in assets if a.location)
    shots = Counter(a.shot for a in assets if a.shot)
    lines = [
        f"LIBRARY: {n} approved clips.",
        "Categories: " + ", ".join(f"{k} ({v})" for k, v in cats.most_common()),
        "Actions: " + ", ".join(f"{k} ({v})" for k, v in actions.most_common()),
        "Locations: " + ", ".join(f"{k} ({v})" for k, v in locs.most_common()),
        "Shots: " + ", ".join(f"{k} ({v})" for k, v in shots.most_common()),
        "Only plan visuals that can be covered by these clips; if an idea has no matching clip, pick the closest "
        "everyday equivalent (hands, laptop, phone, coffee, walking, reaction).",
    ]
    if n <= max_listing:
        lines.append("Clips:")
        for a in assets:
            lines.append(
                f"  {a.id}: {a.description or a.file} [{a.action or '-'} | {a.location or '-'} | {a.shot or '-'} | {a.duration:.1f}s]"
            )
    return "\n".join(lines)
