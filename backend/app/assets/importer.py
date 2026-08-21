"""Scan the asset folder, extract ffprobe metadata, seed semantic metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.metadata import probe_video
from app.models import Asset

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv"}
SKIP_DIRS = {"_originals", "_rejected", "_tmp"}
SEED_FILENAME = "broll_database.json"

_LOCATION_HINTS = [
    ("cafe", ["cafe", "coffee shop", "café"]),
    ("office", ["office", "desk"]),
    ("street", ["street", "sidewalk", "outside", "city", "crosswalk"]),
    ("home", ["home", "couch", "kitchen", "bed"]),
    ("store", ["store", "shelf", "shop", "counter"]),
]
_MOOD_HINTS = [
    ("stressed", ["stressed", "frustrated", "annoyed", "overwhelmed", "tired"]),
    ("happy", ["smile", "laugh", "happy", "excited"]),
    ("focused", ["focus", "typing", "working", "concentrat"]),
    ("relaxed", ["relax", "calm", "slow", "chill", "leisure"]),
]


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def infer_semantics(rel_file: str, description: str | None, tags: list[str]) -> dict:
    """Infer action / location / mood from filename + description + tags (cheap heuristics)."""
    stem = Path(rel_file).stem.lower()
    action = re.sub(r"_?\d+$", "", stem)  # phone_scroll_03 -> phone_scroll
    text = f"{description or ''} {' '.join(tags)} {rel_file}".lower()
    location = None
    for name, hints in _LOCATION_HINTS:
        if any(h in text for h in hints):
            location = name
            break
    mood = "neutral"
    for name, hints in _MOOD_HINTS:
        if any(h in text for h in hints):
            mood = name
            break
    return {"action": action or None, "location": location, "mood": mood}


def _load_seed(root: Path) -> dict[str, dict]:
    seed_path = root / SEED_FILENAME
    if not seed_path.is_file():
        return {}
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    return {d["file"]: d for d in data if "file" in d}


def _next_asset_id(session: Session, reserved: set[str]) -> str:
    ids = {a for (a,) in session.execute(select(Asset.id)).all()} | reserved
    nums = [int(m.group(1)) for i in ids if (m := re.match(r"asset_(\d+)$", i))]
    new = f"asset_{(max(nums) + 1 if nums else 1):03d}"
    reserved.add(new)
    return new


def iter_asset_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts):
            continue
        yield p


def import_assets(session: Session, assets_dir: Path, approve_unseeded: bool = False) -> ImportReport:
    report = ImportReport()
    seed = _load_seed(assets_dir)
    existing = {a.file: a for a in session.execute(select(Asset)).scalars().all()}
    reserved = {d["id"] for d in seed.values() if "id" in d}
    for path in iter_asset_files(assets_dir):
        rel = path.relative_to(assets_dir).as_posix()
        try:
            meta = probe_video(path)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{rel}: {exc}")
            continue
        s = seed.get(rel, {})
        asset = existing.get(rel)
        is_new = asset is None
        if is_new:
            asset = Asset(id=s.get("id") or _next_asset_id(session, reserved), file=rel)
            session.add(asset)
            session.flush()
            existing[rel] = asset
        # technical metadata always refreshed
        asset.duration = round(meta.duration, 3)
        asset.width, asset.height, asset.fps = meta.width, meta.height, round(meta.fps, 3)
        asset.orientation, asset.codec = meta.orientation, meta.codec
        if is_new:
            tags = list(s.get("tags") or [])
            desc = s.get("description")
            sem = infer_semantics(rel, desc, tags)
            asset.description = desc
            asset.tags = tags
            asset.shot = s.get("shot")
            asset.action = s.get("action") or sem["action"]
            asset.location = s.get("location") or sem["location"]
            asset.mood = s.get("mood") or sem["mood"]
            asset.quality_score = float(s.get("quality_score", 0.8))
            margin = min(0.2, meta.duration * 0.05)
            asset.usable_start = float(s.get("usable_start", round(margin, 2)))
            asset.usable_end = float(s.get("usable_end", round(max(meta.duration - margin, margin), 2)))
            asset.approved = bool(s.get("approved", bool(s) or approve_unseeded))
            report.created += 1
        else:
            # keep user edits; only clamp usable range to real duration
            asset.usable_end = min(asset.usable_end or meta.duration, meta.duration)
            report.updated += 1
    session.commit()
    return report


def register_asset_file(
    session: Session,
    assets_dir: Path,
    rel: str,
    *,
    description: str | None = None,
    tags: list[str] | None = None,
    approved: bool = False,
    quality_score: float = 0.8,
    usable_start: float | None = None,
    usable_end: float | None = None,
    action: str | None = None,
    location: str | None = None,
    shot: str | None = None,
    mood: str | None = None,
) -> Asset:
    """Create one Asset row for a file already placed under assets_dir (used by single-file upload)."""
    meta = probe_video(assets_dir / rel)
    tags = [t.strip().lower() for t in (tags or []) if t.strip()]
    sem = infer_semantics(rel, description, tags)
    margin = min(0.2, meta.duration * 0.05)
    us = round(margin, 2) if usable_start is None else round(min(max(0.0, usable_start), meta.duration), 2)
    ue = round(max(meta.duration - margin, margin), 2) if usable_end is None else round(min(max(usable_end, us + 0.1), meta.duration), 2)
    asset = Asset(
        id=_next_asset_id(session, set()),
        file=rel,
        description=description,
        tags=tags,
        action=action or sem["action"],
        location=location or sem["location"],
        mood=mood or sem["mood"],
        shot=shot or None,
        duration=round(meta.duration, 3),
        width=meta.width,
        height=meta.height,
        fps=round(meta.fps, 3),
        orientation=meta.orientation,
        codec=meta.codec,
        usable_start=us,
        usable_end=ue,
        quality_score=quality_score,
        approved=approved,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset
