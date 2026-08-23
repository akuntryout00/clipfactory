"""Slideshow template: slides from the LLM, photos from the persona library, silent clock, rendered MP4 with text overlays."""

from __future__ import annotations

import io

import pytest
from app.assets.importer import import_assets
from app.config.loaders import load_template
from app.models import Asset, ProjectStatus, VideoProject
from app.projects.slideshow import n_slides_for
from PIL import Image

from tests.test_api_ui import client  # noqa: F401
from tests.test_service import svc  # noqa: F401


def _photos(root, persona="young_professional", n=6):
    d = root / persona / "photos"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        buf = io.BytesIO()
        Image.new("RGB", (720, 1280), (30 * i, 90, 200 - 20 * i)).save(buf, format="JPEG")
        (d / f"photo_{i:02d}.jpg").write_bytes(buf.getvalue())


def test_slideshow_template_loads_and_slide_count():
    t = load_template("slideshow_v1")
    assert t.kind == "slideshow" and t.voiceover is False and t.caption_style == "slideshow"
    assert n_slides_for(18) == 7 and n_slides_for(12) == 5 and n_slides_for(25) == 10


def test_slideshow_needs_photos(svc, session):  # noqa: F811
    p = svc.create_project(
        topic="Things nobody tells you about working from cafes", template_id="slideshow_v1", persona_id="young_professional"
    )
    with pytest.raises(RuntimeError, match="photos"):
        svc.generate(p.id)
    assert session.get(VideoProject, p.id).status == ProjectStatus.FAILED.value


def test_slideshow_generates_from_photos(svc, session, mini_assets):  # noqa: F811
    _photos(mini_assets)
    import_assets(session, mini_assets, default_persona="young_professional", approve_unseeded=True)
    for a in session.query(Asset).filter(Asset.kind == "image").all():
        a.approved, a.tags = True, ["cafe", "desk", "photo"]
    session.commit()
    p = svc.create_project(
        topic="Things nobody tells you about working from cafes",
        template_id="slideshow_v1",
        persona_id="young_professional",
        target_duration=18,
    )
    svc.generate(p.id)
    p = session.get(VideoProject, p.id)
    assert p.status == ProjectStatus.READY.value, p.error
    assert p.script_version == 1 and p.plan_version == 1 and p.voice_version == 0 and p.render_version == 1  # no voice: photos, not video
    from app.projects.slideshow import SlideshowPipeline

    pipe = SlideshowPipeline(svc)
    plan = pipe.load_photo_plan(p)
    assert len(plan) == 7 and all(sc["text"] for sc in plan) and len({sc["asset_file"] for sc in plan}) >= 5  # distinct photos preferred
    files = pipe.slide_files(p)
    assert len(files) == 7 and all(f.suffix == ".jpg" for f in files)
    from PIL import Image

    with Image.open(files[0]) as im:
        assert im.size == (1080, 1920)
    assert (files[0].parent / "slides.zip").is_file()
    # change photos keeps the slides, swaps photos, renders the images again; render again only re-renders
    svc.change_assets(p.id)
    p = session.get(VideoProject, p.id)
    assert p.plan_version == 2 and p.render_version == 2 and p.script_version == 1
    svc.render_again(p.id)
    assert session.get(VideoProject, p.id).render_version == 3


def test_slideshow_api_outputs(client):  # noqa: F811
    """Slideshow projects expose slide image URLs and a zip instead of a video."""
    import io as _io

    from PIL import Image as _Image

    for i in range(9):  # more photos than slides so suggestions have spares
        buf = _io.BytesIO()
        _Image.new("RGB", (600, 900), (50 * i, 100, 150)).save(buf, format="JPEG")
        r = client.post(
            "/assets/upload",
            files={"file": (f"p{i}.jpg", buf.getvalue(), "image/jpeg")},
            data={
                "category": "photos",
                "persona_id": "young_professional",
                "description": f"photo {i} desk cafe",
                "tags": "desk,cafe",
                "approved": "true",
                "enrich": "false",
            },
        )
        assert r.status_code == 201, r.text
    p = client.post(
        "/projects",
        json={
            "topic": "Things nobody tells you about cafes",
            "template_id": "slideshow_v1",
            "persona_id": "young_professional",
            "target_duration": 15,
        },
    ).json()
    assert p["kind"] == "slideshow"
    assert client.post(f"/projects/{p['id']}/generate").status_code == 202
    g = client.get(f"/projects/{p['id']}").json()
    assert g["status"] == "READY", g.get("error")
    assert g["video_url"] is None and len(g["slides"]) == 6 and g["slides_zip_url"] and g["post_caption"]
    assert client.get(g["slides"][0]).headers["content-type"] == "image/jpeg"
    assert client.get(g["slides_zip_url"]).headers["content-type"] == "application/zip"
    # per-slide photo override: suggestions are photos, picking one re-renders the images
    sug = client.get(f"/projects/{p['id']}/scenes/1/suggestions").json()
    assert sug and all(s["asset_id"] for s in sug)
    pick = next(s["asset_id"] for s in sug if s["asset_id"] != g["scenes"][1]["asset_id"])
    assert client.post(f"/projects/{p['id']}/scenes/1/asset", json={"asset_id": pick}).status_code == 202
    g2 = client.get(f"/projects/{p['id']}").json()
    assert g2["status"] == "READY" and g2["render_version"] == 2 and g2["scenes"][1]["asset_id"] == pick
