"""Per-persona target B-roll shot list: AI-generated plan of what to film, coverage from the uploaded library, clip ↔ item matching."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.models import Asset, Shotlist, ShotlistItem
from app.personas.repo import persona_or_config

log = logging.getLogger(__name__)

DEFAULT_TARGET = 100
MAX_TARGET = 400


def _items(session: Session, persona_id: str) -> list[ShotlistItem]:
    return list(session.execute(select(ShotlistItem).where(ShotlistItem.persona_id == persona_id).order_by(ShotlistItem.order)).scalars())


def get_shotlist(session: Session, persona_id: str) -> Shotlist | None:
    return session.get(Shotlist, persona_id)


def generate_shotlist(
    session: Session,
    llm: LLMProvider,
    persona_id: str,
    *,
    target_count: int = DEFAULT_TARGET,
    guidance: str | None = None,
    configs_dir: Path | None = None,
    keep_assignments: bool = True,
) -> Shotlist:
    """(Re)generate the list with AI. Existing clip assignments are re-matched by action/category when keep_assignments."""
    target_count = max(5, min(MAX_TARGET, int(target_count)))
    persona = persona_or_config(session, persona_id, configs_dir)
    cats = sorted({(a.file.split("/")[1] if a.file.count("/") >= 2 else a.file.split("/")[0]) for a in _assets(session, persona_id)})
    out = llm.generate_shotlist(persona=persona, target_count=target_count, existing_categories=cats, guidance=guidance)
    old_assign = {a.id: session.get(ShotlistItem, a.shotlist_item_id) for a in _assets(session, persona_id) if a.shotlist_item_id}
    session.execute(delete(ShotlistItem).where(ShotlistItem.persona_id == persona_id))
    new_items: list[ShotlistItem] = []
    for i, it in enumerate(out.items):
        cat = "".join(ch for ch in it.category.lower().strip().replace(" ", "_") if ch.isalnum() or ch == "_") or "misc"
        new_items.append(
            ShotlistItem(
                persona_id=persona_id,
                order=i,
                category=cat,
                title=it.title.strip()[:128],
                description=it.description.strip(),
                shot=it.shot or None,
                action=(it.action or "").strip().lower().replace(" ", "_")[:64] or None,
                location=it.location or None,
                mood=it.mood or None,
                tags=[t.strip().lower() for t in it.tags if t.strip()][:10],
                count=max(1, min(8, int(it.count or 1))),
            )
        )
    session.add_all(new_items)
    # scale counts to the requested total (the model usually hits it, but make the % meaningful either way)
    total = sum(x.count for x in new_items) or 1
    if new_items and total != target_count:
        scale = target_count / total
        for x in new_items:
            x.count = max(1, round(x.count * scale))
    sl = session.get(Shotlist, persona_id) or Shotlist(persona_id=persona_id)
    sl.target_count = target_count
    sl.guidance = guidance
    sl.model = getattr(llm, "model", None) or getattr(llm, "name", None)
    sl.generated_at = datetime.now(UTC)
    session.add(sl)
    session.flush()
    # re-attach clips that were assigned before: same action (+ category) wins
    for aid, old in old_assign.items():
        a = session.get(Asset, aid)
        if a is None:
            continue
        a.shotlist_item_id = None
        if keep_assignments and old is not None:
            match = next((x for x in new_items if x.action == old.action and x.category == old.category), None) or next(
                (x for x in new_items if x.action == old.action), None
            )
            if match:
                a.shotlist_item_id = match.id
    session.commit()
    return sl


def _assets(session: Session, persona_id: str) -> list[Asset]:
    return list(session.execute(select(Asset).where(Asset.persona_id == persona_id)).scalars())


def coverage(session: Session, persona_id: str) -> dict:
    """Coverage = filled clips / wanted clips, where each item counts at most `count` approved clips."""
    items = _items(session, persona_id)
    sl = get_shotlist(session, persona_id)
    assets = _assets(session, persona_id)
    by_item: dict[str, list[Asset]] = defaultdict(list)
    for a in assets:
        if a.shotlist_item_id:
            by_item[a.shotlist_item_id].append(a)
    wanted = sum(i.count for i in items)
    filled = 0
    rows = []
    for it in items:
        clips = sorted(by_item.get(it.id, []), key=lambda a: (not a.approved, a.id))
        approved = [a for a in clips if a.approved]
        f = min(len(approved), it.count)
        filled += f
        rows.append(
            {
                "id": it.id,
                "order": it.order,
                "category": it.category,
                "title": it.title,
                "description": it.description,
                "shot": it.shot,
                "action": it.action,
                "location": it.location,
                "mood": it.mood,
                "tags": it.tags or [],
                "count": it.count,
                "filled": f,
                "assets": [{"id": a.id, "file": a.file, "approved": a.approved} for a in clips],
                "done": f >= it.count,
            }
        )
    unassigned = [a.id for a in assets if not a.shotlist_item_id]
    return {
        "persona_id": persona_id,
        "target_count": sl.target_count if sl else None,
        "generated_at": sl.generated_at if sl else None,
        "guidance": sl.guidance if sl else None,
        "model": sl.model if sl else None,
        "wanted": wanted,
        "filled": filled,
        "percent": round(100 * filled / wanted, 1) if wanted else 0.0,
        "items_total": len(items),
        "items_done": sum(1 for r in rows if r["done"]),
        "library_count": len(assets),
        "unassigned_count": len(unassigned),
        "unassigned_asset_ids": unassigned,
        "items": rows,
    }


def _asset_dict(a: Asset) -> dict:
    return {
        "asset_id": a.id,
        "file": a.file,
        "description": a.description,
        "tags": a.tags or [],
        "action": a.action,
        "location": a.location,
        "shot": a.shot,
        "mood": a.mood,
    }


def _item_dict(it: ShotlistItem) -> dict:
    return {
        "id": it.id,
        "category": it.category,
        "title": it.title,
        "description": it.description,
        "action": it.action,
        "tags": it.tags or [],
    }


def match_assets(
    session: Session, llm: LLMProvider | None, persona_id: str, asset_ids: list[str] | None = None, *, only_unassigned: bool = True
) -> int:
    """Assign clips to shot-list items. LLM when available (batched), else action/category heuristic. Returns number assigned."""
    items = _items(session, persona_id)
    if not items:
        return 0
    assets = _assets(session, persona_id)
    if asset_ids is not None:
        assets = [a for a in assets if a.id in set(asset_ids)]
    if only_unassigned:
        assets = [a for a in assets if not a.shotlist_item_id]
    if not assets:
        return 0
    idict = [_item_dict(i) for i in items]
    assigned = 0
    for start in range(0, len(assets), 40):
        chunk = assets[start : start + 40]
        result: dict[str, int | None] = {}
        if llm is not None:
            try:
                out = llm.match_shotlist(items=idict, assets=[_asset_dict(a) for a in chunk])
                result = {x.asset_id: x.item_index for x in out.assignments}
            except Exception as exc:  # noqa: BLE001 — fall back to the heuristic
                log.warning("shotlist LLM match failed: %s", exc)
        for a in chunk:
            idx = result.get(a.id)
            if idx is None and a.id not in result:
                idx = _heuristic(a, items)
            if idx is not None and 0 <= idx < len(items):
                a.shotlist_item_id = items[idx].id
                assigned += 1
    session.commit()
    return assigned


def _heuristic(a: Asset, items: list[ShotlistItem]) -> int | None:
    cat = a.file.split("/")[1] if a.file.count("/") >= 2 else a.file.split("/")[0]
    for i, it in enumerate(items):
        if a.action and it.action == a.action and it.category == cat:
            return i
    for i, it in enumerate(items):
        if a.action and it.action == a.action:
            return i
    tags = set(a.tags or [])
    best, best_n = None, 1
    for i, it in enumerate(items):
        n = len(tags & set(it.tags or [])) + (1 if it.category == cat else 0)
        if n > best_n:
            best, best_n = i, n
    return best
