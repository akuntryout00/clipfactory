"""Trend analysis pipeline. Downloading uses yt-dlp (public videos); the file stays under storage/trends/<id>/ for the preview and
re-analysis. You are responsible for respecting the platforms' terms — this is for studying structure, not redistribution."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.frames import extract_frames
from app.config.loaders import list_templates
from app.config.settings import get_settings
from app.llm.base import LLMProvider, get_llm
from app.models import TrendAnalysis
from app.personas.repo import persona_or_config

log = logging.getLogger(__name__)

Downloader = Callable[[str, Path], dict]  # (url, dest_dir) -> metadata dict incl. "file"
Transcriber = Callable[[Path], str | None]  # (audio/video path) -> transcript text


def detect_platform(url: str) -> str:
    u = url.lower()
    if "tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return "other"


def ytdlp_download(url: str, dest_dir: Path) -> dict:
    """Download the video with yt-dlp (best mp4 ≤1080p) and return its metadata."""
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 2,
        "writethumbnail": False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    files = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError("yt-dlp finished without a file")
    src = files[0]
    if src.suffix.lower() != ".mp4":  # normalise container for ffmpeg/browser
        mp4 = dest_dir / "source.mp4"
        subprocess.run([get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(src), "-c", "copy", str(mp4)], check=True)
        src = mp4
    keep = (
        "title",
        "uploader",
        "uploader_id",
        "channel",
        "duration",
        "view_count",
        "like_count",
        "comment_count",
        "repost_count",
        "description",
        "upload_date",
        "webpage_url",
        "extractor_key",
        "tags",
    )
    meta = {k: info.get(k) for k in keep if info.get(k) is not None}
    meta["file"] = str(src)
    return meta


def openai_transcribe(path: Path) -> str | None:
    """Transcribe the audio track with OpenAI (gpt-4o-mini-transcribe, falls back to whisper-1). None if no speech/no key."""
    s = get_settings()
    if not s.openai_api_key:
        return None
    from openai import OpenAI

    audio = path.with_suffix(".m4a")
    subprocess.run(
        [
            s.ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "48k",
            str(audio),
        ],
        check=True,
    )
    client = OpenAI(api_key=s.openai_api_key)
    for model in ("gpt-4o-mini-transcribe", "whisper-1"):
        try:
            with audio.open("rb") as fh:
                res = client.audio.transcriptions.create(model=model, file=fh, response_format="text")
            text = res if isinstance(res, str) else getattr(res, "text", "")
            return (text or "").strip() or None
        except Exception as exc:  # noqa: BLE001
            log.warning("transcription with %s failed: %s", model, exc)
    return None


class TrendService:
    def __init__(
        self,
        session: Session,
        *,
        storage_dir: Path | None = None,
        configs_dir: Path | None = None,
        llm: LLMProvider | None = None,
        downloader: Downloader | None = None,
        transcriber: Transcriber | None = None,
        progress=None,
    ):
        s = get_settings()
        self.session = session
        self.storage_dir = Path(storage_dir or s.storage_dir)
        self.configs_dir = Path(configs_dir) if configs_dir else None
        self._llm = llm
        self.download = downloader or ytdlp_download
        self.transcribe = transcriber or openai_transcribe
        self.progress = progress or (lambda tid, stage, msg: None)

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = get_llm()
        return self._llm

    def dir(self, tid: str) -> Path:
        d = self.storage_dir / "trends" / tid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _get(self, tid: str) -> TrendAnalysis:
        t = self.session.get(TrendAnalysis, tid)
        if t is None:
            raise KeyError(f"trend analysis not found: {tid}")
        return t

    def _set(self, t: TrendAnalysis, status: str, msg: str | None = None) -> None:
        t.status = status
        t.stage_message = msg
        self.session.commit()
        self.progress(t.id, status, msg or "")

    # ---------------- create / run
    def create(self, *, url: str, persona_id: str | None) -> TrendAnalysis:
        url = url.strip()
        if not re.match(r"^https?://", url):
            raise ValueError("paste a full http(s) URL")
        t = TrendAnalysis(url=url, platform=detect_platform(url), persona_id=persona_id)
        self.session.add(t)
        self.session.commit()
        return t

    def run(self, tid: str) -> TrendAnalysis:
        t = self._get(tid)
        d = self.dir(t.id)
        try:
            self._set(t, "DOWNLOADING", "Fetching the video…")
            meta = self.download(t.url, d)
            src = Path(meta.pop("file"))
            t.video_path = str(src)
            t.title = (meta.get("title") or "")[:500] or None
            t.uploader = (meta.get("uploader") or meta.get("channel") or "")[:256] or None
            t.duration = float(meta.get("duration") or 0) or None
            t.meta = meta
            self.session.commit()
            # thumbnail + frames
            thumb = d / "thumb.jpg"
            subprocess.run(
                [
                    get_settings().ffmpeg_bin,
                    "-y",
                    "-loglevel",
                    "error",
                    "-ss",
                    "1",
                    "-i",
                    str(src),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=360:-1",
                    str(thumb),
                ],
                check=False,
            )
            if thumb.is_file():
                t.thumbnail_path = str(thumb)
            self._set(t, "TRANSCRIBING", "Transcribing the audio…")
            try:
                t.transcript = self.transcribe(src)
            except Exception as exc:  # noqa: BLE001 — analysis still works from frames + metadata
                log.warning("transcription failed for %s: %s", t.id, exc)
                t.transcript = None
            self.session.commit()
            self._set(t, "ANALYZING", "Reading frames and reverse-engineering the structure…")
            frames = extract_frames(src, n=10, width=512)
            persona = persona_or_config(self.session, t.persona_id or get_settings().default_persona, self.configs_dir)
            tids = [x.id for x in list_templates(self.configs_dir)]
            meta_for_llm = {"platform": t.platform, **(t.meta or {})}
            if t.duration:
                meta_for_llm["duration"] = t.duration
            out = self.llm.analyze_trend(persona=persona, meta=meta_for_llm, transcript=t.transcript, frames=frames, template_ids=tids)
            t.analysis = json.loads(out.model_dump_json())
            self._set(t, "DONE", "Analysis ready")
        except Exception as exc:  # noqa: BLE001
            t.error = str(exc)[:2000]
            self._set(t, "FAILED", f"{type(exc).__name__}: {str(exc)[:300]}")
            log.exception("trend analysis %s failed", t.id)
            raise
        return t

    def retry(self, tid: str) -> TrendAnalysis:
        t = self._get(tid)
        t.error = None
        self._set(t, "QUEUED", "Queued again")
        return t

    def delete(self, tid: str) -> None:
        t = self._get(tid)
        shutil.rmtree(self.storage_dir / "trends" / t.id, ignore_errors=True)
        self.session.delete(t)
        self.session.commit()

    def list(self, persona_id: str | None = None, limit: int = 100) -> list[TrendAnalysis]:
        q = select(TrendAnalysis).order_by(TrendAnalysis.created_at.desc()).limit(limit)
        if persona_id:
            q = q.where((TrendAnalysis.persona_id == persona_id) | (TrendAnalysis.persona_id.is_(None)))
        return list(self.session.execute(q).scalars())

    # ---------------- template from proposal
    @staticmethod
    def template_from_proposal(analysis: dict, overrides: dict | None = None) -> dict:
        """Turn the LLM proposal into a TemplateConfig-shaped dict (section weights from the analysed timestamps)."""
        p = dict(analysis.get("template_proposal") or {})
        secs = p.get("sections") or analysis.get("structure") or []
        total = sum(max(0.0, float(s["end"]) - float(s["start"])) for s in secs) or 1.0
        sections = []
        seen: set[str] = set()
        for s in secs:
            w = max(0.0, float(s["end"]) - float(s["start"])) / total
            if w <= 0:
                continue
            typ = re.sub(r"[^a-z0-9_]+", "_", str(s.get("label", "part")).lower()).strip("_") or "part"
            base, n = typ, 2
            while typ in seen:
                typ, n = f"{base}_{n}", n + 1
            seen.add(typ)
            sections.append({"type": typ, "weight": round(w, 3), "guidance": s.get("purpose") or ""})
        if sections:  # make weights sum to exactly 1
            diff = round(1.0 - sum(x["weight"] for x in sections), 3)
            sections[-1]["weight"] = round(sections[-1]["weight"] + diff, 3)
        dmin, dtar, dmax = float(p.get("duration_min") or 15), float(p.get("duration_target") or 18), float(p.get("duration_max") or 22)
        dmin, dmax = max(10.0, min(dmin, dtar)), max(dtar, dmax)
        tpl = {
            "id": re.sub(r"[^a-z0-9_-]+", "_", str(p.get("id") or "trend_v1").lower()).strip("_")[:40] or "trend_v1",
            "name": (p.get("name") or "Trend remix")[:128],
            "description": (p.get("description") or analysis.get("summary") or "")[:500],
            "duration": {"min": dmin, "target": dtar, "max": dmax},
            "sections": sections
            or [
                {"type": "hook", "weight": 0.2, "guidance": "Open strong"},
                {"type": "body", "weight": 0.6, "guidance": "Substance"},
                {"type": "ending", "weight": 0.2, "guidance": "Close"},
            ],
            "voiceover": bool(p.get("voiceover", True)),
            "caption_style": "dynamic_center",
            "music_category": None,
            "closing": p.get("closing") or None,
            "shot_duration": {"min": float(p.get("shot_min") or 1.5), "max": float(p.get("shot_max") or 4.0)},
            "overlays": {"min": int(p.get("overlays_min") or 1), "max": int(p.get("overlays_max") or 3)},
        }
        if tpl["shot_duration"]["min"] > tpl["shot_duration"]["max"]:
            tpl["shot_duration"] = {"min": 1.5, "max": 4.0}
        if tpl["overlays"]["min"] > tpl["overlays"]["max"]:
            tpl["overlays"] = {"min": 1, "max": 3}
        if overrides:
            tpl.update({k: v for k, v in overrides.items() if v is not None})
        return tpl
