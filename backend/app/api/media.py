"""Media helpers for the UI: range-aware file responses and cached thumbnails."""
from __future__ import annotations

import mimetypes
import subprocess
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.config.settings import get_settings

CHUNK = 1024 * 1024


def ranged_file(path: Path, request: Request, media_type: str | None = None) -> Response:
    """Serve a file honouring HTTP Range (needed for <video>/<audio> seeking)."""
    if not path.is_file():
        raise HTTPException(404, "file not found")
    media_type = media_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    size = path.stat().st_size
    rng = request.headers.get("range")
    if not rng:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})
    try:
        units, spec = rng.split("=")
        start_s, end_s = spec.split("-")
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else size - 1
    except ValueError:
        raise HTTPException(416, "bad range")
    end = min(end, size - 1)
    if start > end or start >= size:
        raise HTTPException(416, "range not satisfiable")

    def iter_file():
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = f.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
    return StreamingResponse(iter_file(), status_code=206, media_type=media_type, headers=headers)


def thumbnail_for(video: Path, cache_dir: Path, key: str, at: float = 1.0, width: int = 360) -> Path:
    """Extract (once) a JPEG frame from a video; cached under storage/thumbs."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{key}.jpg"
    if out.is_file() and out.stat().st_mtime >= video.stat().st_mtime:
        return out
    cmd = [get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
           "-vf", f"scale={width}:-2", "-q:v", "4", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.is_file():
        # fall back to first frame
        subprocess.run(cmd[:4] + cmd[6:], capture_output=True, text=True)
    if not out.is_file():
        raise HTTPException(500, "thumbnail generation failed")
    return out
