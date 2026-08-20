from app.assets.importer import import_assets
from app.assets.catalog import library_summary, candidate_limit_for
from app.assets.enrich import apply_enrichment
from app.llm.fake import FakeLLM
from app.models import Asset
from app.schemas.pipeline import AssetEnrichment, AssetEnrichOutput


def test_candidate_limit_sends_whole_small_library():
    assert candidate_limit_for(34) == 34
    assert candidate_limit_for(60) == 60
    assert candidate_limit_for(500) == 15


def test_library_summary_lists_counts_and_descriptions(session, mini_assets):
    import_assets(session, mini_assets)
    txt = library_summary(session)
    assert "6 approved clips" in txt
    assert "desk" in txt and "phone" in txt and "walking" in txt
    assert "asset_001" in txt and "typing clip" in txt  # per-clip one-liners for small libraries


def test_fake_llm_enrich_and_apply_merges_tags_without_dropping_existing(session, mini_assets):
    import_assets(session, mini_assets)
    a = session.get(Asset, "asset_001")
    out = AssetEnrichOutput(assets=[AssetEnrichment(asset_id="asset_001", tags=["keyboard", "focus"], action="typing_laptop",
                                                    location="cafe", mood="focused", shot="close")])
    n = apply_enrichment(session, out, overwrite=False)
    assert n == 1
    a = session.get(Asset, "asset_001")
    assert set(a.tags) >= {"typing", "laptop", "desk", "work", "keyboard", "focus"}
    assert a.action == "typing"              # existing value kept without --overwrite
    assert a.mood == "focused"               # was 'neutral' (default) → filled
    n2 = apply_enrichment(session, out, overwrite=True)
    assert session.get(Asset, "asset_001").action == "typing_laptop"


def test_fake_llm_enrich_returns_entry_per_asset(session, mini_assets):
    import_assets(session, mini_assets)
    rows = session.query(Asset).all()
    out = FakeLLM().enrich_assets(assets=[{"asset_id": a.id, "file": a.file, "description": a.description, "tags": a.tags} for a in rows])
    assert {e.asset_id for e in out.assets} == {a.id for a in rows}
