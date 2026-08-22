"""Global + per-project caption overrides (font, size, position) applied on top of the template's caption style,
and the list of fonts available to libass."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import AppSetting
from app.schemas.configs import CaptionStyleConfig

SETTINGS_KEY = "captions"
FONT_EXT = (".ttf", ".otf")


class CaptionOverrides(BaseModel):
    """Every field optional: None = keep what the template's caption style says."""

    font_name: str | None = Field(default=None, max_length=80, description="caption font family, e.g. 'Montserrat'")
    font_size: int | None = Field(default=None, ge=30, le=160)
    bold: bool | None = None
    vertical_anchor_ratio: float | None = Field(
        default=None, ge=0.2, le=0.95, description="0 = top, 1 = bottom; caption block bottom anchor"
    )
    overlay_font_name: str | None = Field(default=None, max_length=80)
    overlay_font_size: int | None = Field(default=None, ge=30, le=200)
    overlay_vertical_anchor_ratio: float | None = Field(default=None, ge=0.05, le=0.8)

    def is_empty(self) -> bool:
        return all(v is None for v in self.model_dump().values())


def get_caption_settings(session: Session) -> CaptionOverrides:
    row = session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        return CaptionOverrides()
    return CaptionOverrides.model_validate(row.value or {})


def set_caption_settings(session: Session, ov: CaptionOverrides) -> CaptionOverrides:
    row = session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY, value={})
        session.add(row)
    row.value = ov.model_dump()
    session.commit()
    return ov


def apply_overrides(style: CaptionStyleConfig, *layers: CaptionOverrides | dict | None) -> CaptionStyleConfig:
    """Return a copy of `style` with each non-None field of the layers applied in order (later wins)."""
    out = style.model_copy(deep=True)
    for layer in layers:
        if layer is None:
            continue
        ov = layer if isinstance(layer, CaptionOverrides) else CaptionOverrides.model_validate(layer)
        if ov.font_name:
            out.font_name = ov.font_name
        if ov.font_size is not None:
            out.font_size = ov.font_size
        if ov.bold is not None:
            out.bold = ov.bold
        if ov.vertical_anchor_ratio is not None:
            out.vertical_anchor_ratio = ov.vertical_anchor_ratio
        if ov.overlay_font_name:
            out.overlay.font_name = ov.overlay_font_name
        if ov.overlay_font_size is not None:
            out.overlay.font_size = ov.overlay_font_size
        if ov.overlay_vertical_anchor_ratio is not None:
            out.overlay.vertical_anchor_ratio = ov.overlay_vertical_anchor_ratio
    return out


def resolve_caption_style(session: Session, style: CaptionStyleConfig, project_overrides: dict | None) -> CaptionStyleConfig:
    """template style → global settings → project overrides."""
    return apply_overrides(style, get_caption_settings(session), project_overrides)


# ---------------------------------------------------------------- fonts


def _fc(cmd: list[str]) -> list[str]:
    exe = shutil.which(cmd[0])
    if not exe:
        return []
    try:
        res = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return []
    return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]


def font_family_from_file(path: Path) -> tuple[str, str]:
    """(family, style) read with fontconfig's fc-scan; falls back to the file name ('Montserrat-ExtraBold' → 'Montserrat', 'ExtraBold')."""
    lines = _fc(["fc-scan", "--format", "%{family}|%{style}\n", str(path)])
    if lines and "|" in lines[0]:
        fam, sty = lines[0].split("|", 1)
        return fam.split(",")[0].strip(), sty.split(",")[0].strip()
    stem = path.stem
    fam, _, sty = stem.partition("-")
    return fam.replace("_", " ").strip() or stem, sty or "Regular"


def list_fonts(fonts_dir: Path | None, include_system: bool = True) -> list[dict]:
    """Fonts offered in the UI: files in fonts_dir (bundled/user) + families fontconfig knows (system)."""
    out: list[dict] = []
    seen: set[str] = set()
    if fonts_dir and Path(fonts_dir).is_dir():
        for f in sorted(Path(fonts_dir).iterdir()):
            if f.suffix.lower() not in FONT_EXT or f.name.startswith("."):
                continue
            fam, sty = font_family_from_file(f)
            out.append({"family": fam, "style": sty, "file": f.name, "source": "fonts_dir"})
            seen.add(fam)
    if include_system:
        for fam in sorted({ln.split(",")[0].strip() for ln in _fc(["fc-list", ":", "family"])}):
            if fam and fam not in seen and not fam.startswith("."):
                out.append({"family": fam, "style": None, "file": None, "source": "system"})
                seen.add(fam)
    return out


def save_font_file(fonts_dir: Path, filename: str, data: bytes) -> dict:
    name = Path(filename).name
    if Path(name).suffix.lower() not in FONT_EXT:
        raise ValueError("only .ttf / .otf fonts are supported")
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise ValueError("file does not look like a TrueType/OpenType font")
    fonts_dir.mkdir(parents=True, exist_ok=True)
    dest = fonts_dir / name
    dest.write_bytes(data)
    fam, sty = font_family_from_file(dest)
    return {"family": fam, "style": sty, "file": name, "source": "fonts_dir"}
