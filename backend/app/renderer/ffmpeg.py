"""Deterministic Video JSON → MP4 renderer (two stages, PRD §18/§19)."""

from __future__ import annotations

import random
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.config.settings import get_settings
from app.renderer.audio import build_audio_graph
from app.renderer.filters import OUT_FPS, pick_look, scene_vf
from app.renderer.subtitles import ass_filter_arg, build_ass_for_video
from app.schemas.configs import CaptionStyleConfig
from app.schemas.pipeline import VideoJSON


class RenderError(RuntimeError):
    pass


@dataclass
class RenderOptions:
    preset: str = "veryfast"
    crf: int = 20
    music_db: float = -20.0
    keep_work_dir: bool = False
    threads: int = 0


@dataclass
class RenderResult:
    output_path: str
    scene_clips: list[str] = field(default_factory=list)
    ass_path: str | None = None
    commands: list[list[str]] = field(default_factory=list)


def _run(cmd: list[str], commands: list[list[str]]) -> None:
    commands.append(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-25:]
        raise RenderError("ffmpeg failed:\n" + " ".join(cmd) + "\n" + "\n".join(tail))


def render_scene_clip(ffmpeg: str, src: Path, start: float, duration: float, out: Path, look, options: RenderOptions, commands) -> None:
    vf = scene_vf(look, duration)
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(src),
        "-an",
        "-vf",
        vf,
        "-r",
        str(OUT_FPS),
        "-c:v",
        "libx264",
        "-preset",
        options.preset,
        "-crf",
        str(max(options.crf - 2, 10)),
        "-pix_fmt",
        "yuv420p",
        "-video_track_timescale",
        "15360",
    ]
    if options.threads:
        cmd += ["-threads", str(options.threads)]
    cmd.append(str(out))
    _run(cmd, commands)


def render_video(
    video: VideoJSON,
    *,
    assets_dir: Path,
    voice_path: Path,
    out_path: Path,
    style: CaptionStyleConfig,
    work_dir: Path,
    music_path: Path | None = None,
    options: RenderOptions | None = None,
    fonts_dir: Path | None = None,
) -> RenderResult:
    settings = get_settings()
    options = options or RenderOptions(threads=settings.render_threads)
    ffmpeg = settings.ffmpeg_bin
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = RenderResult(output_path=str(out_path))
    rng = random.Random(video.seed)

    # ---- stage 1: per-scene intermediate clips (trim, cover-scale, jitter crop, subtle zoom, 30 fps)
    clips: list[Path] = []
    for i, sc in enumerate(video.scenes):
        src = assets_dir / sc.asset_file
        if not src.is_file():
            raise RenderError(f"asset file missing: {src}")
        dur = round(sc.end - sc.start, 3)
        look = pick_look(rng, i)
        clip = work_dir / f"scene_{sc.order:02d}.mp4"
        render_scene_clip(ffmpeg, src, sc.asset_start, dur, clip, look, options, result.commands)
        clips.append(clip)
        result.scene_clips.append(str(clip))

    # ---- stage 2: concat + subtitles/overlays + audio mix + encode
    concat_list = work_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    ass_path = build_ass_for_video(video, style, work_dir / "captions.ass")
    result.ass_path = str(ass_path)
    total = video.total_duration

    if fonts_dir is None and style.font_file:
        fonts_dir = Path(style.font_file).parent
    if fonts_dir is None and settings.font_file:
        fonts_dir = Path(settings.font_file).parent

    inputs = ["-f", "concat", "-safe", "0", "-i", str(concat_list), "-i", str(voice_path)]
    has_music = bool(music_path and Path(music_path).is_file())
    if has_music:
        inputs += ["-i", str(music_path)]
    audio_graph, aout = build_audio_graph(
        has_music, voice_idx=1, music_idx=2 if has_music else None, music_db=options.music_db, total_duration=total
    )
    vf = f"[0:v]{ass_filter_arg(ass_path, fonts_dir)},format=yuv420p[vout]"
    filter_complex = f"{vf};{audio_graph}"
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        aout,
        "-t",
        f"{total:.3f}",
        "-r",
        str(OUT_FPS),
        "-c:v",
        "libx264",
        "-preset",
        options.preset,
        "-crf",
        str(options.crf),
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-ac",
        "2",
    ]
    if options.threads:
        cmd += ["-threads", str(options.threads)]
    cmd.append(str(out_path))
    _run(cmd, result.commands)

    if not options.keep_work_dir:
        for c in clips:
            c.unlink(missing_ok=True)
        concat_list.unlink(missing_ok=True)
    return result


def cleanup_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


_FILTER_CACHE: dict[str, bool] = {}


def ffmpeg_has_filter(name: str) -> bool:
    """Detect whether the local ffmpeg build provides a filter (e.g. 'ass' needs libass)."""
    if name not in _FILTER_CACHE:
        try:
            out = subprocess.run([get_settings().ffmpeg_bin, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        except Exception:  # noqa: BLE001
            out = ""
        _FILTER_CACHE[name] = any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())
    return _FILTER_CACHE[name]


def check_render_capabilities() -> list[str]:
    """Return a list of missing capabilities (empty = ready)."""
    missing = []
    if not ffmpeg_has_filter("ass"):
        missing.append("ffmpeg built without libass ('ass' filter) — captions cannot be burned in")
    return missing
