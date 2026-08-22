"""Per-persona target B-roll shot list: generate with AI, coverage %, match clips."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import cfg_dir, get_db
from app.assets.shotlist import DEFAULT_TARGET, MAX_TARGET, coverage, generate_shotlist, match_assets
from app.llm.base import get_llm
from app.models import Asset, ShotlistItem

router = APIRouter(tags=["shotlist"])


def _llm(request: Request):
    return request.app.state.service_kwargs.get("llm") or get_llm()


class ShotlistGenerate(BaseModel):
    target_count: int = Field(default=DEFAULT_TARGET, ge=5, le=MAX_TARGET)
    guidance: str | None = Field(default=None, max_length=2000)
    match_existing: bool = True  # assign the persona's current clips to the new items right away


@router.get("/personas/{persona_id}/shotlist")
def shotlist_get(persona_id: str, db: Session = Depends(get_db)):
    return coverage(db, persona_id)


@router.post("/personas/{persona_id}/shotlist/generate")
def shotlist_generate(persona_id: str, body: ShotlistGenerate, request: Request, db: Session = Depends(get_db)):
    try:
        generate_shotlist(
            db, _llm(request), persona_id, target_count=body.target_count, guidance=body.guidance, configs_dir=cfg_dir(request)
        )
    except FileNotFoundError:
        raise HTTPException(404, "persona not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"AI shot list failed: {exc}")
    if body.match_existing:
        with contextlib.suppress(Exception):  # best effort: the list is useful even if matching fails
            match_assets(db, _llm(request), persona_id)
    return coverage(db, persona_id)


class ShotlistMatch(BaseModel):
    asset_ids: list[str] | None = None
    only_unassigned: bool = True


@router.post("/personas/{persona_id}/shotlist/match")
def shotlist_match(persona_id: str, body: ShotlistMatch, request: Request, db: Session = Depends(get_db)):
    n = match_assets(db, _llm(request), persona_id, body.asset_ids, only_unassigned=body.only_unassigned)
    out = coverage(db, persona_id)
    out["matched"] = n
    return out


@router.delete("/personas/{persona_id}/shotlist", status_code=204)
def shotlist_delete(persona_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import delete, select, update

    from app.models import Shotlist

    db.execute(update(Asset).where(Asset.persona_id == persona_id).values(shotlist_item_id=None))
    db.execute(delete(ShotlistItem).where(ShotlistItem.persona_id == persona_id))
    if (sl := db.get(Shotlist, persona_id)) is not None:
        db.delete(sl)
    db.commit()
    _ = select  # noqa: F841
