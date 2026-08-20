from datetime import datetime, timedelta, timezone
from pathlib import Path
import random

import pytest

from app.assets.metadata import probe_video
from app.assets.importer import import_assets, infer_semantics
from app.assets.selector import (
    freshness_multiplier,
    relevance_score,
    find_candidates,
    choose_segment,
    extract_query_tags,
)
from app.models import Asset
from tests.conftest import make_clip


def test_probe_video_reads_technical_metadata(tmp_path: Path):
    clip = make_clip(tmp_path / "c.mp4", seconds=2.0, size="360x640", fps=30)
    meta = probe_video(clip)
    assert meta.width == 360 and meta.height == 640
    assert meta.orientation == "vertical"
    assert abs(meta.fps - 30) < 0.01
    assert 1.9 < meta.duration < 2.2
    assert meta.codec == "h264"


def test_import_creates_assets_and_skips_service_dirs(session, mini_assets):
    report = import_assets(session, mini_assets)
    assert report.created == 6
    ids = {a.id for a in session.query(Asset).all()}
    assert ids == {f"asset_{i:03d}" for i in range(1, 7)}
    assert not any("_rejected" in a.file for a in session.query(Asset).all())


def test_import_fills_technical_and_semantic_metadata(session, mini_assets):
    import_assets(session, mini_assets)
    a = session.get(Asset, "asset_001")
    assert a.width == 360 and a.height == 640
    assert a.fps and a.duration > 2.9
    assert "typing" in a.tags
    assert a.action == "typing"
    assert a.shot == "close"
    assert a.approved is True  # seeded/curated assets are approved
    assert 0 <= a.usable_start < a.usable_end <= a.duration
    assert 0 < a.quality_score <= 1


def test_import_is_idempotent_and_keeps_edits(session, mini_assets):
    import_assets(session, mini_assets)
    a = session.get(Asset, "asset_001")
    a.mood = "focused"
    a.quality_score = 0.55
    session.commit()
    report = import_assets(session, mini_assets)
    assert report.created == 0 and report.updated == 6
    a = session.get(Asset, "asset_001")
    assert a.mood == "focused" and a.quality_score == 0.55


def test_import_new_unseeded_file_is_unapproved(session, mini_assets):
    make_clip(mini_assets / "desk" / "new_clip_01.mp4")
    import_assets(session, mini_assets)
    a = session.query(Asset).filter(Asset.file == "desk/new_clip_01.mp4").one()
    assert a.approved is False
    assert a.id.startswith("asset_")


def test_infer_semantics_from_filename_and_description():
    s = infer_semantics("phone/phone_scroll_03.mp4", "POV scrolling a phone at a cafe table", ["phone", "scrolling"])
    assert s["action"] == "phone_scroll"
    assert s["location"] == "cafe"
    assert s["mood"] in ("neutral", "relaxed")


@pytest.mark.parametrize(
    "days_ago,expected",
    [(None, 1.0), (0.2, 0.20), (2, 0.45), (5, 0.70), (10, 0.90)],
)
def test_freshness_multiplier_table(days_ago, expected):
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    last = None if days_ago is None else now - timedelta(days=days_ago)
    assert freshness_multiplier(last, now) == pytest.approx(expected)


def test_relevance_score_prefers_matching_tags():
    a = Asset(id="a", file="x", tags=["typing", "laptop", "desk"], action="typing", location="cafe", shot="close", description="typing on laptop")
    b = Asset(id="b", file="y", tags=["walking", "street"], action="walking", location="street", shot="wide", description="walking outside")
    q = ["typing", "laptop", "desk"]
    assert relevance_score(a, q) > relevance_score(b, q)
    assert relevance_score(b, ["coffee"]) == 0


def test_extract_query_tags_normalizes_and_expands():
    tags = extract_query_tags(["Typing", "laptops", "meeting notes"])
    assert "typing" in tags and "laptop" in tags and "note" in tags and "meeting" in tags


def test_find_candidates_ranks_by_score_and_respects_exclusions(session, mini_assets):
    import_assets(session, mini_assets)
    cands = find_candidates(session, ["typing", "laptop", "desk"], limit=3)
    assert cands[0].asset.id == "asset_001"
    cands2 = find_candidates(session, ["typing", "laptop", "desk"], limit=3, exclude_ids={"asset_001"})
    assert all(c.asset.id != "asset_001" for c in cands2)


def test_find_candidates_ignores_unapproved(session, mini_assets):
    import_assets(session, mini_assets)
    a = session.get(Asset, "asset_001")
    a.approved = False
    session.commit()
    cands = find_candidates(session, ["typing"], limit=5)
    assert all(c.asset.id != "asset_001" for c in cands)


def test_find_candidates_penalises_recent_use(session, mini_assets):
    import_assets(session, mini_assets)
    a = session.get(Asset, "asset_001")
    a.last_used_at = datetime.now(timezone.utc)
    session.commit()
    cands = find_candidates(session, ["typing", "laptop", "desk", "coffee"], limit=2)
    # coffee clip (never used) should now outrank the freshly-used typing clip
    assert cands[0].asset.id == "asset_002"


def test_choose_segment_stays_in_usable_range_and_varies():
    a = Asset(id="a", file="x", duration=8.0, usable_start=1.0, usable_end=7.5)
    starts = {choose_segment(a, 2.5, random.Random(seed)) for seed in range(20)}
    assert all(1.0 <= s <= 5.0 for s in starts)
    assert len(starts) > 3


def test_choose_segment_when_clip_too_short_returns_usable_start():
    a = Asset(id="a", file="x", duration=2.0, usable_start=0.2, usable_end=1.8)
    assert choose_segment(a, 2.5, random.Random(1)) == 0.2


def test_candidate_dict_flags_recently_used(session, mini_assets):
    import_assets(session, mini_assets)
    a = session.get(Asset, "asset_001")
    a.last_used_at = datetime.now(timezone.utc)
    session.commit()
    cands = {c.asset.id: c.as_dict() for c in find_candidates(session, ["typing", "coffee"], limit=10)}
    assert cands["asset_001"]["recently_used"] is True
    assert cands["asset_002"]["recently_used"] is False
