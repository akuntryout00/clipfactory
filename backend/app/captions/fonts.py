"""Font lookup + text measurement for captions (Pillow/FreeType), so wrapping and the UI preview match what libass renders.

ASS/libass semantics: `Fontsize` is the *line height* (ascender + descender) in script pixels, not the em size. So an ASS size S
renders glyphs at em = S * units_per_em / (ascender + descender) px. We expose that factor (`line_factor`) to the UI preview and use
the same font file to measure real line widths when wrapping captions.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FONT_EXT = (".ttf", ".otf")


@dataclass(frozen=True)
class FontMetrics:
    file: str
    family: str
    units_per_em: int
    ascent: int  # OS/2 usWinAscent (fallback hhea ascender), font units
    descent: int  # OS/2 usWinDescent (fallback |hhea descender|), font units

    @property
    def line_factor(self) -> float:
        """(ascent + descent) / units_per_em — ASS size = em px × line_factor."""
        return (self.ascent + self.descent) / float(self.units_per_em or 1000)

    def em_px(self, ass_size: float) -> float:
        return ass_size / self.line_factor


def _fc(args: list[str]) -> str:
    exe = shutil.which(args[0])
    if not exe:
        return ""
    try:
        return subprocess.run([exe, *args[1:]], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _families_of(path: Path) -> list[str]:
    out = _fc(["fc-scan", "--format", "%{family}", str(path)])
    fams = [f.strip() for f in out.split(",") if f.strip()] if out else []
    if not fams:
        fams = [path.stem.split("-")[0].replace("_", " ")]
    return fams


def _style_of(path: Path) -> str:
    out = _fc(["fc-scan", "--format", "%{style}", str(path)])
    return out.split(",")[0].strip() if out else path.stem.partition("-")[2] or "Regular"


@lru_cache(maxsize=64)
def _dir_index(fonts_dir: str) -> list[tuple[Path, list[str], str]]:
    d = Path(fonts_dir)
    if not d.is_dir():
        return []
    return [(f, _families_of(f), _style_of(f)) for f in sorted(d.iterdir()) if f.suffix.lower() in FONT_EXT and not f.name.startswith(".")]


def find_font_file(family: str, bold: bool = True, fonts_dir: Path | None = None) -> Path | None:
    """File libass will most likely use for `family`: fonts_dir first (prefers a Bold style when bold), then fontconfig."""
    fam_l = family.strip().lower()
    if fonts_dir:
        cands = [(f, sty) for f, fams, sty in _dir_index(str(fonts_dir)) if any(x.lower() == fam_l for x in fams)]
        if cands:
            if bold:
                for f, sty in cands:
                    if "bold" in sty.lower() or "black" in sty.lower() or "heavy" in sty.lower():
                        return f
            return cands[0][0]
    out = _fc(["fc-match", "-f", "%{file}|%{family}", f"{family}:weight={'bold' if bold else 'regular'}"])
    if out and "|" in out:
        file, fam = out.split("|", 1)
        # only accept a real match for this family; fontconfig falls back to a default font for unknown names
        if fam_l in [x.strip().lower() for x in fam.split(",")] and Path(file).is_file():
            return Path(file)
    return None


@lru_cache(maxsize=128)
def font_metrics(path: str) -> FontMetrics | None:
    """Read units_per_em / hhea ascent / descent straight from the TTF/OTF tables (no dependency)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    import struct

    def u16(o):
        return struct.unpack(">H", data[o : o + 2])[0]

    def s16(o):
        return struct.unpack(">h", data[o : o + 2])[0]

    def u32(o):
        return struct.unpack(">I", data[o : o + 4])[0]

    try:
        off = 0
        if data[:4] == b"ttcf":  # collection: first font
            off = u32(12)
        num_tables = u16(off + 4)
        if num_tables > 512:
            return None
        tables = {}
        for i in range(num_tables):
            rec = off + 12 + 16 * i
            tag = data[rec : rec + 4].decode("latin-1")
            tables[tag] = (u32(rec + 8), u32(rec + 12))
        if "head" not in tables or "hhea" not in tables:
            return None
        upm = u16(tables["head"][0] + 18) or 1000
        hh = tables["hhea"][0]
        asc, desc = s16(hh + 4), abs(s16(hh + 6))
        # libass emulates VSFilter/GDI: the ASS font size equals usWinAscent + usWinDescent (OS/2), not the hhea metrics
        if "OS/2" in tables and tables["OS/2"][1] >= 78:
            o = tables["OS/2"][0]
            wa, wd = u16(o + 74), u16(o + 76)
            if wa + wd > 0:
                asc, desc = wa, wd
    except (struct.error, IndexError, UnicodeDecodeError):
        return None
    if asc + desc <= 0:
        return None
    fam = _families_of(Path(path))[0]
    return FontMetrics(file=str(path), family=fam, units_per_em=upm, ascent=asc, descent=desc)


def resolve(family: str, bold: bool, fonts_dir: Path | None) -> FontMetrics | None:
    f = find_font_file(family, bold, fonts_dir)
    return font_metrics(str(f)) if f else None


class TextMeasurer:
    """Measures rendered line widths (px at the ASS script resolution) for one style; falls back to a per-char estimate."""

    def __init__(self, family: str, bold: bool, ass_size: float, fonts_dir: Path | None):
        self.metrics = resolve(family, bold, fonts_dir)
        self.ass_size = ass_size
        self._font = None
        if self.metrics is not None:
            try:
                from PIL import ImageFont

                self._font = ImageFont.truetype(self.metrics.file, max(1, round(self.metrics.em_px(ass_size))))
            except Exception:  # noqa: BLE001 — Pillow missing or font unreadable → estimate
                self._font = None

    @property
    def exact(self) -> bool:
        return self._font is not None

    def width(self, text: str) -> float:
        if self._font is not None:
            try:
                return float(self._font.getlength(text))
            except Exception:  # noqa: BLE001
                pass
        # estimate: average glyph ≈ 0.55 em (bold sans), space ≈ 0.3 em
        em = self.metrics.em_px(self.ass_size) if self.metrics else self.ass_size / 1.17
        return sum(0.3 * em if ch == " " else 0.55 * em for ch in text)
