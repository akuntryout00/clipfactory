"""Scene → B-roll assignment (PRD §9, §31, §32, §33) producing a validated Video JSON."""
from __future__ import annotations

import random

from sqlalchemy.orm import Session

from sqlalchemy import func, select

from app.assets.catalog import candidate_limit_for
from app.assets.selector import Candidate, choose_segment, extract_query_tags, find_candidates
from app.captions.generator import build_caption_chunks
from app.llm.base import LLMProvider
from app.models import Asset
from app.schemas.configs import CaptionStyleConfig, PersonaConfig, TemplateConfig
from app.schemas.pipeline import NormalizedScene, VideoJSON, VideoJSONScene, VoiceoverSpec, WordTiming

CANDIDATES_PER_SCENE = 12


def select_assets_for_scenes(
    session: Session, llm: LLMProvider, topic: str, scenes: list[NormalizedScene],
    exclude_asset_ids: set[str] | None = None,
) -> dict[int, Asset]:
    """Backend filtering → LLM ranking → validated, unique asset per scene (fallback: best score)."""
    exclude = set(exclude_asset_ids or ())
    n_approved = session.execute(select(func.count()).select_from(Asset).where(Asset.approved.is_(True))).scalar_one()
    limit = candidate_limit_for(n_approved)
    small = limit >= n_approved  # whole catalog goes to the LLM (PRD §9 small-library mode)
    candidates: dict[int, list[Candidate]] = {}
    for sc in scenes:
        tags = extract_query_tags(sc.query_tags + [sc.intent])
        cands = find_candidates(session, tags, limit=limit, exclude_ids=exclude, min_duration=sc.duration,
                                min_relevance=-1.0 if small else 0.0)
        if not cands:  # relax: any approved asset long enough, then any at all
            cands = find_candidates(session, tags, limit=limit, exclude_ids=exclude, min_relevance=-1.0)
        if not cands:
            cands = find_candidates(session, tags, limit=limit, min_relevance=-1.0)
        if not cands:
            raise RuntimeError("no approved assets available — import and approve assets first")
        candidates[sc.order] = cands

    llm_choice: dict[int, str] = {}
    try:
        ranked = llm.rank_assets(topic=topic, scenes=scenes, candidates={k: [c.as_dict() for c in v] for k, v in candidates.items()})
        llm_choice = {c.scene_order: c.asset_id for c in ranked.choices}
    except Exception:  # noqa: BLE001 — ranking is best-effort; scoring fallback below
        llm_choice = {}

    chosen: dict[int, Asset] = {}
    used: set[str] = set()
    for sc in scenes:
        cands = candidates[sc.order]
        by_id = {c.asset.id: c for c in cands}
        pick = llm_choice.get(sc.order)
        asset = by_id[pick].asset if pick in by_id and pick not in used else None
        if asset is None:
            for c in cands:
                if c.asset.id not in used:
                    asset = c.asset
                    break
        if asset is None:  # every candidate already used → widen the search before allowing a repeat
            wider = find_candidates(session, extract_query_tags(sc.query_tags + [sc.intent]), limit=50,
                                    exclude_ids=exclude | used, min_relevance=-1.0)
            asset = wider[0].asset if wider else cands[0].asset
        used.add(asset.id)
        chosen[sc.order] = asset
    return chosen


def assign_assets(
    *, session: Session, llm: LLMProvider, persona: PersonaConfig, template: TemplateConfig, topic: str,
    scenes: list[NormalizedScene], words: list[WordTiming], voice_audio: str, voice_duration: float,
    caption_style: CaptionStyleConfig, seed: int = 0, exclude_asset_ids: set[str] | None = None,
    fixed_assets: dict[int, str] | None = None, music: str | None = None,
) -> VideoJSON:
    """Build the Video JSON. `fixed_assets` pins scene_order → asset_id (manual override / render-again)."""
    rng = random.Random(seed)
    fixed_assets = fixed_assets or {}
    need = [s for s in scenes if s.order not in fixed_assets]
    chosen: dict[int, Asset] = {}
    for order, aid in fixed_assets.items():
        a = session.get(Asset, aid)
        if a is None:
            raise ValueError(f"unknown asset {aid}")
        chosen[order] = a
    if need:
        exclude = set(exclude_asset_ids or ()) | {a.id for a in chosen.values()}
        chosen.update(select_assets_for_scenes(session, llm, topic, need, exclude_asset_ids=exclude))

    vscenes = []
    for sc in scenes:
        a = chosen[sc.order]
        vscenes.append(VideoJSONScene(
            order=sc.order, start=sc.start, end=sc.end, asset_id=a.id, asset_file=a.file,
            asset_start=choose_segment(a, sc.duration, rng), text=sc.overlay_text, section=sc.section,
        ))
    captions = build_caption_chunks(words, caption_style) if template.voiceover else []
    total = vscenes[-1].end
    for c in captions:
        c.end = min(c.end, total)
    return VideoJSON(
        persona=persona.id, template=template.id, topic=topic,
        voiceover=VoiceoverSpec(text=" ".join(w.word for w in words), audio=voice_audio, duration=voice_duration),
        scenes=vscenes, caption_style=caption_style.id, music=music, captions=captions, seed=seed,
    )
