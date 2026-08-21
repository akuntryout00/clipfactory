"""Technical metadata extraction via ffprobe."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import get_settings


@dataclass
class VideoMeta:
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    has_audio: bool

    @property
    def orientation(self) -> str:
        if self.height > self.width:
            return "vertical"
        if self.width > self.height:
            return "horizontal"
        return "square"


def _parse_fps(rate: str) -> float:
    if "/" in rate:
        n, d = rate.split("/")
        return float(n) / float(d) if float(d) else 0.0
    return float(rate or 0)


def ffprobe_json(path: Path) -> dict:
    cmd = [
        get_settings().ffprobe_bin, "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def probe_video(path: Path) -> VideoMeta:
    data = ffprobe_json(path)
    vstreams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    astreams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not vstreams:
        raise ValueError(f"no video stream in {path}")
    v = vstreams[0]
    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0.0)
    width, height = int(v["width"]), int(v["height"])
    # honour rotation metadata (phones / DJI store rotated streams)
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    tags_rot = (v.get("tags") or {}).get("rotate")
    if tags_rot:
        rot = int(tags_rot)
    if abs(rot) % 180 == 90:
        width, height = height, width
    return VideoMeta(
        duration=duration,
        width=width,
        height=height,
        fps=_parse_fps(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0"),
        codec=v.get("codec_name", ""),
        has_audio=bool(astreams),
    )
