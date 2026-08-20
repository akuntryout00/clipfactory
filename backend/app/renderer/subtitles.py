"""Subtitle/overlay sidecar generation for the renderer."""
from __future__ import annotations

from pathlib import Path

from app.captions.generator import write_ass
from app.schemas.configs import CaptionStyleConfig
from app.schemas.pipeline import VideoJSON


def build_ass_for_video(video: VideoJSON, style: CaptionStyleConfig, out_path: Path) -> Path:
    overlays = [(s.start + 0.05, s.end - 0.05, s.text) for s in video.scenes if s.text]
    return write_ass(video.captions, overlays, style, out_path)


def ass_filter_arg(path: Path, fonts_dir: Path | None = None) -> str:
    """Escape a path for use inside an ffmpeg filter option value."""
    p = str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    arg = f"ass=filename='{p}'"
    if fonts_dir:
        fd = str(fonts_dir).replace("\\", "/").replace(":", "\\:")
        arg += f":fontsdir='{fd}'"
    return arg
