"""Frame sampling for AI clip analysis."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.assets.metadata import probe_video
from app.config.settings import get_settings


def extract_frames(video: Path, n: int = 6, width: int = 512) -> list[bytes]:
    """Sample n JPEG frames evenly across the clip (skipping the very first/last 5 %)."""
    meta = probe_video(video)
    dur = max(meta.duration, 0.2)
    pad = dur * 0.05
    times = [pad + (dur - 2 * pad) * i / max(n - 1, 1) for i in range(n)] if n > 1 else [dur / 2]
    out: list[bytes] = []
    with tempfile.TemporaryDirectory() as td:
        for i, t in enumerate(times):
            p = Path(td) / f"f{i:02d}.jpg"
            cmd = [
                get_settings().ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:-2",
                "-q:v",
                "5",
                str(p),
            ]
            subprocess.run(cmd, capture_output=True, text=True)
            if p.is_file():
                out.append(p.read_bytes())
    return out
