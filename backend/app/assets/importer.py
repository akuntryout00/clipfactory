"""Scan the asset folder, extract ffprobe metadata, seed semantic metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.metadata import media_kind, probe_media
from app.models import Asset

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MEDIA_EXT = VIDEO_EXT | IMAGE_EXT
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
        if not p.is_file() or p.suffix.lower() not in MEDIA_EXT:
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts):
            continue
        yield p


def _persona_ids(session: Session) -> set[str]:
    from app.models import Persona

    return {pid for (pid,) in session.execute(select(Persona.id)).all()}


def persona_for_path(rel: str, persona_ids: set[str], default_persona: str | None) -> str | None:
    """assets/<persona>/<category>/file → persona; legacy assets/<category>/file → default persona."""
    first = rel.split("/")[0] if "/" in rel else ""
    return first if first in persona_ids else default_persona


def import_assets(session: Session, assets_dir: Path, approve_unseeded: bool = False, default_persona: str | None = None) -> ImportReport:
    report = ImportReport()
    seed = _load_seed(assets_dir)
    existing = {a.file: a for a in session.execute(select(Asset)).scalars().all()}
    reserved = {d["id"] for d in seed.values() if "id" in d}
    personas = _persona_ids(session)
    if default_persona is None:
        from app.config.settings import get_settings

        default_persona = get_settings().default_persona
    for path in iter_asset_files(assets_dir):
        rel = path.relative_to(assets_dir).as_posix()
        try:
            meta = probe_media(path)
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
        asset.kind = media_kind(rel)
        asset.duration = round(meta.duration, 3)
        asset.width, asset.height, asset.fps = meta.width, meta.height, round(meta.fps, 3)
        asset.orientation, asset.codec = meta.orientation, meta.codec
        if not asset.persona_id:
            asset.persona_id = persona_for_path(rel, personas, default_persona)
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
    persona_id: str | None = None,
) -> Asset:
    """Create one Asset row for a file already placed under assets_dir (used by single-file upload)."""
    meta = probe_media(assets_dir / rel)
    tags = [t.strip().lower() for t in (tags or []) if t.strip()]
    sem = infer_semantics(rel, description, tags)
    margin = min(0.2, meta.duration * 0.05)
    us = round(margin, 2) if usable_start is None else round(min(max(0.0, usable_start), meta.duration), 2)
    ue = round(max(meta.duration - margin, margin), 2) if usable_end is None else round(min(max(usable_end, us + 0.1), meta.duration), 2)
    asset = Asset(
        id=_next_asset_id(session, set()),
        file=rel,
        kind=media_kind(rel),
        persona_id=persona_id or persona_for_path(rel, _persona_ids(session), None),
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


def migrate_assets_to_persona(session: Session, assets_dir: Path, persona_id: str) -> int:
    """One-off: move legacy `assets/<category>/file` clips under `assets/<persona>/<category>/file` and set persona_id."""
    import shutil

    personas = _persona_ids(session) | {persona_id}
    moved = 0
    for a in session.execute(select(Asset)).scalars().all():
        first = a.file.split("/")[0]
        if first in personas:
            if not a.persona_id:
                a.persona_id = first
            continue
        src = assets_dir / a.file
        new_rel = f"{persona_id}/{a.file}"
        dst = assets_dir / new_rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        a.file, a.persona_id = new_rel, persona_id
        moved += 1
    session.commit()
    return moved
