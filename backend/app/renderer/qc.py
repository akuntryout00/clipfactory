"""Post-render quality checks (PRD §41)."""

from __future__ import annotations

from pathlib import Path

from app.assets.metadata import ffprobe_json

MIN_DURATION, MAX_DURATION = 10.0, 30.0
MIN_BYTES = 300_000


def run_qc(path: Path, expected_duration: float | None = None) -> dict:
    failures: list[str] = []
    info: dict = {}
    if not Path(path).is_file():
        return {"passed": False, "failures": ["file missing"], "info": info}
    size = Path(path).stat().st_size
    info["size_bytes"] = size
    if size < MIN_BYTES:
        failures.append(f"file size too small ({size} bytes)")
    try:
        data = ffprobe_json(Path(path))
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "failures": [f"ffprobe failed: {exc}"], "info": info}
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0)
    info["duration"] = duration
    if v is None:
        failures.append("no video stream")
    else:
        info.update(width=v.get("width"), height=v.get("height"), codec=v.get("codec_name"))
        if (v.get("width"), v.get("height")) != (1080, 1920):
            failures.append(f"resolution {v.get('width')}x{v.get('height')} != 1080x1920")
        fr = v.get("avg_frame_rate") or "0/1"
        n, d = fr.split("/") if "/" in fr else (fr, "1")
        fps = float(n) / float(d) if float(d) else 0
        info["fps"] = fps
        if not (29.5 <= fps <= 30.5):
            failures.append(f"fps {fps:.2f} invalid")
        if v.get("codec_name") != "h264":
            failures.append(f"video codec {v.get('codec_name')} != h264")
    if a is None:
        failures.append("no audio stream")
    elif a.get("codec_name") != "aac":
        failures.append(f"audio codec {a.get('codec_name')} != aac")
    if not (MIN_DURATION < duration < MAX_DURATION):
        failures.append(f"duration {duration:.2f}s outside ({MIN_DURATION}, {MAX_DURATION})")
    if expected_duration and abs(duration - expected_duration) > 0.6:
        failures.append(f"duration {duration:.2f}s differs from plan {expected_duration:.2f}s")
    return {"passed": not failures, "failures": failures, "info": info}
