"""Font metrics + width-aware caption wrapping."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.captions.fonts import TextMeasurer, find_font_file, font_metrics
from app.captions.generator import _fit, write_ass
from app.config.loaders import load_caption_style
from app.schemas.pipeline import CaptionChunk

FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"
needs_fonts = pytest.mark.skipif(not (FONTS_DIR / "Poppins-Bold.ttf").exists(), reason="bundled fonts missing")


@needs_fonts
def test_font_metrics_and_lookup():
    f = find_font_file("Poppins", True, FONTS_DIR)
    assert f is not None and f.name == "Poppins-Bold.ttf"
    m = font_metrics(str(f))
    assert m is not None and m.units_per_em == 1000 and 1.0 < m.line_factor < 2.0
    assert find_font_file("NoSuchFamilyXYZ", True, FONTS_DIR) is None


@needs_fonts
def test_measurer_narrow_font_fits_more_text():
    wide = TextMeasurer("Poppins", True, 78, FONTS_DIR)
    narrow = TextMeasurer("Bebas Neue", True, 78, FONTS_DIR)
    assert wide.exact and narrow.exact
    assert narrow.width("you opened your laptop") < wide.width("you opened your laptop")


@needs_fonts
def test_fit_does_not_shrink_when_lines_fit():
    m = TextMeasurer("Bebas Neue", True, 78, FONTS_DIR)
    words = ["PRODUCTIVITY", "EXPECTATIONS"]  # 25 chars > max_chars 16 → old code shrank; width-based: two lines, 100 %
    lines, pct = _fit(words, m.width, 900, 16, 2)
    assert pct == 100 and 1 <= len(lines) <= 2  # Bebas is narrow enough for one line; no shrink either way
    lines2, pct2 = _fit(words, m.width, 400, 16, 2)
    assert pct2 == 100 and len(lines2) == 2  # narrower box → wraps instead of shrinking


@needs_fonts
def test_fit_shrinks_only_when_a_single_word_overflows():
    m = TextMeasurer("Poppins", True, 78, FONTS_DIR)
    lines, pct = _fit(["Supercalifragilisticexpialidocious"], m.width, 300, 16, 2)
    assert len(lines) == 1 and 60 <= pct < 100


def test_fit_fallback_without_font():
    lines, pct = _fit(["a", "very", "long", "caption", "line", "with", "many", "words"], None, 900, 16, 2)
    assert len(lines) == 2 and pct <= 100


@needs_fonts
def test_write_ass_uses_fonts_dir(tmp_path):
    style = load_caption_style("dynamic_center").model_copy(update={"font_name": "Bebas Neue"})
    chunks = [CaptionChunk(start=0, end=1, text="PRODUCTIVITY EXPECTATIONS", emphasis_index=None)]
    out = write_ass(chunks, [(0, 1, "ONE THING")], style, tmp_path / "c.ass", fonts_dir=FONTS_DIR)
    txt = out.read_text()
    assert "\\fscx" not in txt.split("[Events]")[1].replace("\\fscx80\\fscy80\\t(0,120,\\fscx100\\fscy100)", "")
