"""Photos in the library: import/upload images as kind=image, excluded from B-roll selection, thumbnails."""

from __future__ import annotations

import io

from app.assets.importer import import_assets
from app.assets.selector import find_candidates
from app.models import Asset
from PIL import Image

from tests.test_api_ui import client  # noqa: F401


def _jpg(color=(40, 120, 200), size=(600, 900)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_import_registers_images_as_photos(session, mini_assets):
    from app.personas.repo import seed_personas_from_configs

    seed_personas_from_configs(session)  # so assets/indie_maker/... is recognised as that persona's folder
    (mini_assets / "indie_maker" / "photos").mkdir(parents=True, exist_ok=True)
    (mini_assets / "indie_maker" / "photos" / "cafe_table_01.jpg").write_bytes(_jpg())
    import_assets(session, mini_assets, default_persona="young_professional")
    a = session.query(Asset).filter(Asset.file == "indie_maker/photos/cafe_table_01.jpg").one()
    assert a.kind == "image" and a.duration == 0 and a.width == 600 and a.height == 900 and a.orientation == "vertical"
    # photos never show up as B-roll candidates; videos never as photos
    a.approved = True
    a.tags = ["cafe", "table"]
    session.commit()
    assert all(c.asset.kind == "video" for c in find_candidates(session, ["cafe"], persona_id=None))
    photos = find_candidates(session, ["cafe"], persona_id="indie_maker", kind="image")
    assert photos and photos[0].asset.id == a.id


def test_upload_and_list_photos_api(client):  # noqa: F811
    r = client.post(
        "/assets/upload",
        files={"file": ("desk_wide.jpg", _jpg(), "image/jpeg")},
        data={
            "category": "photos",
            "persona_id": "young_professional",
            "description": "wide desk with a laptop and coffee",
            "tags": "desk,laptop",
            "approved": "true",
            "enrich": "false",
        },
    )
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["kind"] == "image" and a["file"].endswith("photos/desk_wide.jpg") and a["approved"] is True
    assert client.get(f"/assets/{a['id']}/thumbnail").headers["content-type"] == "image/jpeg"
    ids = {x["id"] for x in client.get("/assets?kind=image").json()}
    assert a["id"] in ids and all(x["kind"] == "image" for x in client.get("/assets?kind=image").json())
    assert a["id"] not in {x["id"] for x in client.get("/assets?kind=video").json()}
    r = client.post("/assets/analyze", files={"file": ("x.jpg", _jpg(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["description"]
