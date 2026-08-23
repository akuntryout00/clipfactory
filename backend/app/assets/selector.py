"""Asset candidate search + scoring (relevance × quality × freshness) + segment choice."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset

# PRD §32 freshness table
FRESHNESS_TABLE = [
    (1.0, 0.20),  # used within last day
    (3.0, 0.45),  # 1-3 days
    (7.0, 0.70),  # 3-7 days
    (float("inf"), 0.90),  # 7+ days
]

_STOP = {"a", "an", "the", "of", "to", "in", "on", "at", "and", "or", "for", "with", "is", "are", "it", "this", "that", "you", "your", "my"}
_SYNONYMS = {
    "laptop": ["macbook", "computer", "notebook"],
    "typing": ["keyboard", "type"],
    "phone": ["smartphone", "iphone", "mobile"],
    "scrolling": ["scroll", "swipe", "feed"],
    "walking": ["walk", "commute", "street"],
    "coffee": ["cafe", "cup", "latte"],
    "stressed": ["frustrated", "overwhelmed", "tired"],
    "meeting": ["call", "zoom", "conversation"],
    "notes": ["notebook", "writing", "typing"],
    "work": ["working", "desk", "office"],
    "ai": ["assistant", "chat", "screen"],
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def normalize_tag(t: str) -> str:
    return _singular(re.sub(r"[^a-z0-9]+", "", t.lower().strip()))


def extract_query_tags(raw: list[str]) -> list[str]:
    """Normalize free-text scene hints into a flat tag list (split phrases, singularize, expand synonyms)."""
    out: list[str] = []
    for item in raw:
        for w in re.split(r"[\s,/→\-]+", item.lower()):
            w = normalize_tag(w)
            if not w or w in _STOP:
                continue
            out.append(w)
            for syn in _SYNONYMS.get(w, []):
                out.append(normalize_tag(syn))
    # de-dup, keep order
    seen, result = set(), []
    for w in out:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result


def freshness_multiplier(last_used_at: datetime | None, now: datetime | None = None) -> float:
    if last_used_at is None:
        return 1.0
    now = now or datetime.now(UTC)
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=UTC)
    days = (now - last_used_at).total_seconds() / 86400.0
    for limit, mult in FRESHNESS_TABLE:
        if days < limit:
            return mult
    return 0.90


def relevance_score(asset: Asset, query_tags: list[str]) -> float:
    """0..1 — weighted overlap between query tags and asset tags/action/location/shot/description."""
    if not query_tags:
        return 0.0
    asset_tags = {normalize_tag(t) for t in (asset.tags or [])}
    strong = set(asset_tags)
    for f in (asset.action, asset.location, asset.shot, asset.mood):
        if f:
            strong.update(normalize_tag(p) for p in re.split(r"[_\s]+", f))
    weak = {normalize_tag(w) for w in re.findall(r"[a-zA-Z]+", asset.description or "")}
    q = [normalize_tag(t) for t in query_tags]
    score = 0.0
    for i, t in enumerate(q):
        # earlier query tags matter slightly more (primary concepts first)
        w = 1.0 if i < 3 else 0.7
        if t in strong:
            score += w
        elif t in weak:
            score += 0.5 * w
    denom = sum(1.0 if i < 3 else 0.7 for i in range(len(q)))
    return min(1.0, score / denom) if denom else 0.0


@dataclass
class Candidate:
    asset: Asset
    relevance: float
    freshness: float
    score: float

    def as_dict(self) -> dict:
        a = self.asset
        return {
            "asset_id": a.id,
            "description": a.description,
            "tags": a.tags,
            "action": a.action,
            "location": a.location,
            "shot": a.shot,
            "mood": a.mood,
            "duration": round(a.duration, 2),
            "score": round(self.score, 3),
            "recently_used": self.freshness < 1.0,
        }


def find_candidates(
    session: Session,
    query_tags: list[str],
    limit: int = 15,
    exclude_ids: set[str] | None = None,
    min_duration: float = 0.0,
    now: datetime | None = None,
    min_relevance: float = 0.0,
    persona_id: str | None = None,
    kind: str | None = "video",
) -> list[Candidate]:
    exclude_ids = exclude_ids or set()
    q = select(Asset).where(Asset.approved.is_(True))
    if persona_id:
        q = q.where(Asset.persona_id == persona_id)
    if kind:
        q = q.where(Asset.kind == kind)
    assets = session.execute(q).scalars().all()
    cands: list[Candidate] = []
    for a in assets:
        if a.id in exclude_ids:
            continue
        usable = (a.usable_end or a.duration) - (a.usable_start or 0)
        if min_duration and usable < min_duration * 0.8:  # allow slight stretch
            continue
        rel = relevance_score(a, query_tags)
        if rel <= min_relevance:
            continue
        fresh = freshness_multiplier(a.last_used_at, now)
        score = rel * (a.quality_score or 0.5) * fresh
        cands.append(Candidate(asset=a, relevance=rel, freshness=fresh, score=score))
    cands.sort(key=lambda c: (-c.score, c.asset.usage_count, c.asset.id))
    return cands[:limit]


def choose_segment(asset: Asset, needed: float, rng: random.Random) -> float:
    """Pick a start offset inside [usable_start, usable_end - needed] (PRD §33)."""
    us = asset.usable_start or 0.0
    ue = asset.usable_end or asset.duration or 0.0
    latest = ue - needed
    if latest <= us:
        return round(us, 2)
    return round(rng.uniform(us, latest), 2)
