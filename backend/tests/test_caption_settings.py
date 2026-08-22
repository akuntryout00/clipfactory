"""Caption font/position settings: global (System) + per-project overrides, font listing."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.captions.settings import (
    CaptionOverrides,
    apply_overrides,
    font_family_from_file,
    list_fonts,
    resolve_caption_style,
    set_caption_settings,
)
from app.config.loaders import load_caption_style
from pydantic import ValidationError

from tests.test_api_ui import client  # noqa: F401 — reuse the API test app fixture

FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"


def test_apply_overrides_layers_later_wins():
    base = load_caption_style("dynamic_center")
    out = apply_overrides(base, CaptionOverrides(font_name="Poppins", font_size=90), {"font_name": "Anton", "vertical_anchor_ratio": 0.6})
    assert (out.font_name, out.font_size, out.vertical_anchor_ratio) == ("Anton", 90, 0.6)
    assert base.font_name == "DejaVu Sans"  # untouched copy
    assert apply_overrides(base, None, {}).model_dump() == base.model_dump()


def test_resolve_uses_global_then_project(session):
    base = load_caption_style("dynamic_center")
    set_caption_settings(session, CaptionOverrides(font_name="Montserrat", overlay_font_size=120))
    eff = resolve_caption_style(session, base, None)
    assert eff.font_name == "Montserrat" and eff.overlay.font_size == 120
    eff2 = resolve_caption_style(session, base, {"font_name": "Oswald"})
    assert eff2.font_name == "Oswald" and eff2.overlay.font_size == 120


def test_overrides_validation():
    with pytest.raises(ValidationError):
        CaptionOverrides(font_size=10)
    assert CaptionOverrides().is_empty()


def test_font_family_from_bundled_file():
    f = FONTS_DIR / "Poppins-Bold.ttf"
    if not f.exists():
        pytest.skip("bundled fonts missing")
    fam, _ = font_family_from_file(f)
    assert fam == "Poppins"


def test_list_fonts_includes_fonts_dir_files(tmp_path):
    (tmp_path / "MyFont-Bold.ttf").write_bytes(b"\x00\x01\x00\x00" + b"0" * 64)
    fonts = list_fonts(tmp_path, include_system=False)
    assert fonts == [{"family": "MyFont", "style": "Bold", "file": "MyFont-Bold.ttf", "source": "fonts_dir", "line_factor": None}]


def test_caption_settings_and_project_overrides_api(client):  # noqa: F811
    r = client.get("/settings/captions")
    assert r.status_code == 200 and r.json()["overrides"]["font_name"] is None and r.json()["defaults"]["font_size"] == 78
    r = client.put("/settings/captions", json={"overrides": {"font_name": "Poppins", "vertical_anchor_ratio": 0.8}})
    assert r.status_code == 200 and r.json()["overrides"]["font_name"] == "Poppins"
    assert client.put("/settings/captions", json={"overrides": {"font_size": 5}}).status_code == 422
    p = client.post("/projects", json={"topic": "Captions test topic", "template_id": "story_v1"}).json()
    assert p["caption_style"]["font_name"] == "Poppins" and p["caption_overrides"] is None
    r = client.put(f"/projects/{p['id']}/captions", json={"overrides": {"font_name": "Anton", "font_size": 96}})
    assert r.status_code == 200
    d = r.json()
    assert d["caption_overrides"] == {
        "font_name": "Anton",
        "font_size": 96,
        "bold": None,
        "vertical_anchor_ratio": None,
        "overlay_font_name": None,
        "overlay_font_size": None,
        "overlay_vertical_anchor_ratio": None,
    }
    assert d["caption_style"]["font_name"] == "Anton" and d["caption_style"]["vertical_anchor_ratio"] == 0.8
    r = client.put(f"/projects/{p['id']}/captions", json={"overrides": None})
    assert r.json()["caption_overrides"] is None and r.json()["caption_style"]["font_name"] == "Poppins"
    r = client.get("/fonts")
    assert r.status_code == 200 and isinstance(r.json()["fonts"], list)
