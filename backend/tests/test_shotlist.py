"""Persona B-roll shot list: AI generation, coverage %, clip matching, API."""

from __future__ import annotations

from app.assets.shotlist import coverage, generate_shotlist, match_assets
from app.llm.fake import FakeLLM
from app.models import Asset, ShotlistItem

from tests.test_api_ui import client  # noqa: F401


def test_generate_scales_counts_and_coverage_math(session, mini_assets):
    from app.assets.importer import import_assets

    import_assets(session, mini_assets, default_persona="young_professional")
    llm = FakeLLM()
    sl = generate_shotlist(session, llm, "young_professional", target_count=20)
    items = session.query(ShotlistItem).filter_by(persona_id="young_professional").all()
    assert sl.target_count == 20 and items and sum(i.count for i in items) == 20
    cov = coverage(session, "young_professional")
    assert cov["wanted"] == 20 and cov["filled"] == 0 and cov["percent"] == 0.0 and cov["library_count"] > 0
    # match: fake llm matches by action, heuristic by category; desk clips exist in mini_assets
    n = match_assets(session, llm, "young_professional")
    assert n >= 1
    cov = coverage(session, "young_professional")
    assert 0 < cov["percent"] <= 100 and cov["unassigned_count"] == cov["library_count"] - n
    # only approved clips count
    a = session.query(Asset).filter(Asset.shotlist_item_id.isnot(None)).first()
    a.approved = False
    session.commit()
    cov2 = coverage(session, "young_professional")
    assert cov2["filled"] <= cov["filled"]


def test_regenerate_keeps_assignments_by_action(session, mini_assets):
    from app.assets.importer import import_assets

    import_assets(session, mini_assets, default_persona="young_professional")
    llm = FakeLLM()
    generate_shotlist(session, llm, "young_professional", target_count=8)
    match_assets(session, llm, "young_professional")
    before = session.query(Asset).filter(Asset.shotlist_item_id.isnot(None)).count()
    generate_shotlist(session, llm, "young_professional", target_count=12, guidance="more cafe")
    after = session.query(Asset).filter(Asset.shotlist_item_id.isnot(None)).count()
    assert after == before  # re-attached to the regenerated items with the same action
    assert coverage(session, "young_professional")["wanted"] == 12


def test_shotlist_api(client):  # noqa: F811
    r = client.get("/personas/young_professional/shotlist")
    assert r.status_code == 200 and r.json()["items_total"] == 0 and r.json()["percent"] == 0.0
    r = client.post("/personas/young_professional/shotlist/generate", json={"target_count": 10, "guidance": "cafe life"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["wanted"] == 10 and d["items_total"] >= 1 and d["target_count"] == 10
    assert client.post("/personas/nobody/shotlist/generate", json={"target_count": 10}).status_code == 404
    assert client.post("/personas/young_professional/shotlist/generate", json={"target_count": 1}).status_code == 422
    # manual assignment through the asset PATCH
    item_id = d["items"][0]["id"]
    assets = client.get("/assets").json()
    a = next(x for x in assets if not x.get("shotlist_item_id"))
    r = client.patch(f"/assets/{a['id']}", json={"shotlist_item_id": item_id})
    assert r.status_code == 200 and r.json()["shotlist_item_id"] == item_id
    assert client.patch(f"/assets/{a['id']}", json={"shotlist_item_id": "shot_nope"}).status_code == 422
    r = client.post("/personas/young_professional/shotlist/match", json={"only_unassigned": True})
    assert r.status_code == 200 and "matched" in r.json()
    assert client.delete("/personas/young_professional/shotlist").status_code == 204
    assert client.get("/personas/young_professional/shotlist").json()["items_total"] == 0
