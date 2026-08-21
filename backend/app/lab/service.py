"""AI Lab orchestration: plan → images → animate → concat. Independent of the content-factory pipeline."""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.lab.models import LabEvent, LabKeyframe, LabSegment, LabVideo
from app.lab.planning import segment_plan
from app.lab.providers import ImageGen, Planner, VideoGen, get_image_gen, get_planner, get_video_gen

log = logging.getLogger(__name__)
MIN_TARGET, MAX_TARGET = 15.0, 25.0


class LabService:
    def __init__(self, session: Session, image: ImageGen | None = None, video: VideoGen | None = None, planner: Planner | None = None,
                 storage_dir: Path | None = None, progress: Callable[[str, str], None] | None = None):
        self.session = session
        self._image, self._video, self._planner = image, video, planner
        self.storage_dir = Path(storage_dir or get_settings().storage_dir) / "lab"
        self.progress = progress or (lambda st, m: None)

    @property
    def image(self) -> ImageGen:
        if self._image is None:
            self._image = get_image_gen()
        return self._image

    @property
    def video(self) -> VideoGen:
        if self._video is None:
            self._video = get_video_gen()
        return self._video

    @property
    def planner(self) -> Planner:
        if self._planner is None:
            self._planner = get_planner()
        return self._planner

    # ---------- queries ----------
    def dir(self, video_id: str) -> Path:
        d = self.storage_dir / video_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get(self, video_id: str) -> LabVideo:
        v = self.session.get(LabVideo, video_id)
        if v is None:
            raise KeyError(f"lab video not found: {video_id}")
        return v

    def list(self, limit: int = 100) -> list[LabVideo]:
        return list(self.session.execute(select(LabVideo).order_by(LabVideo.created_at.desc()).limit(limit)).scalars())

    def keyframes(self, video_id: str) -> list[LabKeyframe]:
        return list(self.session.execute(select(LabKeyframe).where(LabKeyframe.video_id == video_id).order_by(LabKeyframe.index)).scalars())

    def segments(self, video_id: str) -> list[LabSegment]:
        return list(self.session.execute(select(LabSegment).where(LabSegment.video_id == video_id).order_by(LabSegment.index)).scalars())

    def events(self, video_id: str) -> list[LabEvent]:
        return list(self.session.execute(select(LabEvent).where(LabEvent.video_id == video_id).order_by(LabEvent.id)).scalars())

    def _log(self, v: LabVideo, stage: str, message: str, level: str = "info") -> None:
        self.session.add(LabEvent(video_id=v.id, stage=stage, level=level, message=message))
        v.stage_message = message
        self.session.commit()
        self.progress(stage, message)

    def _status(self, v: LabVideo, status: str, message: str | None = None, level: str = "info") -> None:
        v.status = status
        if status != "FAILED":
            v.error = None
        self._log(v, status, message or status.replace("_", " ").title(), level=level)

    def _fail(self, v: LabVideo, stage: str, exc: Exception) -> None:
        v.status, v.error = "FAILED", f"{stage}: {exc}"
        self._log(v, "FAILED", f"{stage} failed: {exc}", level="error")

    # ---------- step 0: create (instant) ----------
    def create(self, prompt: str, target_duration: float, style: str | None = None) -> LabVideo:
        if not prompt or len(prompt.strip()) < 5:
            raise ValueError("describe the video you want (at least a few words)")
        if not (MIN_TARGET <= target_duration <= MAX_TARGET):
            raise ValueError(f"target_duration must be {MIN_TARGET:.0f}-{MAX_TARGET:.0f} s")
        n, seg = segment_plan(target_duration, max_seg=getattr(self.video, "max_seconds", 8))
        v = LabVideo(prompt=prompt.strip(), style=style, target_duration=target_duration, n_segments=n, segment_seconds=seg,
                     image_model=getattr(self.image, "model", None), video_model=getattr(self.video, "model", None), status="PLANNING")
        self.session.add(v)
        self.session.commit()
        self._log(v, "CREATED", f"Video created · {n + 1} keyframes planned as {n} × {seg}s clips (target {target_duration:.0f}s)")
        return v

    # ---------- step 1: storyboard plan (LLM) ----------
    def plan(self, video_id: str) -> LabVideo:
        v = self.get(video_id)
        n = v.n_segments
        self._status(v, "PLANNING", f"Planning storyboard with {getattr(self.planner, 'name', 'llm')} ({n + 1} keyframes)…")
        try:
            plan = self.planner.plan(prompt=v.prompt, n_keyframes=n + 1, segment_seconds=v.segment_seconds, style=v.style)
        except Exception as exc:  # noqa: BLE001
            self._fail(v, "plan", exc)
            raise
        for old in self.keyframes(video_id):
            self.session.delete(old)
        for old in self.segments(video_id):
            self.session.delete(old)
        v.style_guide = plan.style_guide
        for k in plan.keyframes:
            self.session.add(LabKeyframe(video_id=v.id, index=k.index, prompt=k.prompt, caption=k.caption))
        for i in range(n):
            motion = plan.keyframes[i].motion_to_next if i < len(plan.keyframes) else None
            self.session.add(LabSegment(video_id=v.id, index=i, from_index=i, to_index=i + 1, prompt=motion))
        self.session.commit()
        self._status(v, "PLANNED", f"Storyboard ready: {len(plan.keyframes)} keyframes — " + " · ".join(k.caption for k in plan.keyframes), level="success")
        return v

    def run_to_images(self, video_id: str) -> LabVideo:
        """Background job after create: plan → keyframe images."""
        self.plan(video_id)
        return self.generate_images(video_id)

    def retry(self, video_id: str) -> LabVideo:
        """Resume a FAILED video from the first incomplete step."""
        v = self.get(video_id)
        self._log(v, "RETRY", "Retrying from the last incomplete step…")
        if not self.keyframes(video_id):
            self.plan(video_id)
        kfs = self.keyframes(video_id)
        if any(k.status != "DONE" or not k.image_path for k in kfs):
            return self.generate_images(video_id, only_missing=True)
        if any(s.status != "DONE" for s in self.segments(video_id)) or not v.final_path:
            return self.animate(video_id)
        self._status(v, "DONE", "Nothing to retry — video is complete", level="success")
        return v

    # ---------- step 1: images ----------
    def _image_prompt(self, v: LabVideo, k: LabKeyframe) -> str:
        return f"{k.prompt}\n\nSTYLE (keep identical across frames): {v.style_guide or ''}\nVertical 9:16 portrait composition, no text, no watermark."

    def generate_images(self, video_id: str, only_missing: bool = False) -> LabVideo:
        """Generate keyframe images in order; each frame receives the previous frame as a reference for continuity."""
        v = self.get(video_id)
        kfs = self.keyframes(video_id)
        if not kfs:
            raise RuntimeError("plan the storyboard first")
        total = len(kfs)
        model = getattr(self.image, "model", "image model")
        self._status(v, "GENERATING_IMAGES", f"Generating {total} keyframe images with {model}, one after another (each uses the previous frame as reference)…")
        try:
            prev: Path | None = None
            for k in kfs:
                if only_missing and k.status == "DONE" and k.image_path and Path(k.image_path).is_file():
                    prev = Path(k.image_path)
                    continue
                self._gen_keyframe(v, k, total, reference=prev)
                prev = Path(k.image_path) if k.image_path else prev
            self._status(v, "IMAGES_READY", "All keyframes ready — review them, then press Animate", level="success")
        except Exception as exc:  # noqa: BLE001
            self._fail(v, "images", exc)
            raise
        return v

    def _gen_keyframe(self, v: LabVideo, k: LabKeyframe, total: int | None = None, reference: Path | None = None) -> None:
        total = total or len(self.keyframes(v.id))
        model = getattr(self.image, "model", "image model")
        k.status = "GENERATING"
        self.session.commit()
        k.version += 1
        ref_note = f" (reference: keyframe {k.index})" if reference else ""
        self._log(v, "IMAGE", f"Keyframe {k.index + 1}/{total} “{k.caption or ''}”: generating with {model}{ref_note}…")
        out = self.dir(v.id) / f"kf_{k.index:02d}_v{k.version}.png"
        t0 = time.time()
        try:
            self.image.generate(prompt=self._image_prompt(v, k), out_path=out, reference=reference)
        except Exception as exc:  # noqa: BLE001
            k.status, k.error = "FAILED", str(exc)
            self.session.commit()
            self._log(v, "IMAGE", f"Keyframe {k.index + 1}/{total} failed: {exc}", level="error")
            raise
        k.image_path, k.status, k.error = str(out), "DONE", None
        self.session.commit()
        self._log(v, "IMAGE", f"Keyframe {k.index + 1}/{total} ready ({time.time() - t0:.0f}s)", level="success")

    def regenerate_keyframe(self, video_id: str, index: int, prompt: str | None = None) -> LabVideo:
        v = self.get(video_id)
        k = next((x for x in self.keyframes(video_id) if x.index == index), None)
        if k is None:
            raise KeyError(f"keyframe {index} not found")
        if prompt:
            k.prompt = prompt.strip()
        self._status(v, "GENERATING_IMAGES", f"Regenerating keyframe {index + 1}…")
        prev_k = next((x for x in self.keyframes(video_id) if x.index == index - 1), None)
        reference = Path(prev_k.image_path) if prev_k and prev_k.image_path and Path(prev_k.image_path).is_file() else None
        try:
            self._gen_keyframe(v, k, reference=reference)
            # segments touching this frame must be re-animated
            for s in self.segments(video_id):
                if index in (s.from_index, s.to_index):
                    s.status, s.video_path = "PENDING", None
            v.final_path = None
            all_done = all(x.status == "DONE" for x in self.keyframes(video_id))
            self._status(v, "IMAGES_READY" if all_done else "PLANNED", "All keyframes ready — review them, then press Animate" if all_done else "Some keyframes still missing", level="success" if all_done else "info")
        except Exception as exc:  # noqa: BLE001
            self._fail(v, "images", exc)
            raise
        return v

    # ---------- step 2: animate ----------
    def animate(self, video_id: str, force: bool = False) -> LabVideo:
        """Animate every segment that is not done yet (force=True re-animates all, e.g. after changing provider/model)."""
        v = self.get(video_id)
        kfs = {k.index: k for k in self.keyframes(video_id)}
        if not kfs or any(k.status != "DONE" or not k.image_path for k in kfs.values()):
            raise RuntimeError("generate all keyframe images first")
        v.video_model = getattr(self.video, "model", None) or v.video_model
        segs = self.segments(video_id)
        self._status(v, "ANIMATING", f"Animating {len(segs)} segments with {v.video_model} ({v.segment_seconds}s each)…")
        try:
            for s in segs:
                if not force and s.status == "DONE" and s.video_path and Path(s.video_path).is_file():
                    continue
                s.status = "GENERATING"
                self.session.commit()
                self._log(v, "SEGMENT", f"Segment {s.index + 1}/{len(segs)} (frames {s.from_index}→{s.to_index}): generating with {v.video_model} (≈1–3 min)…")
                t0 = time.time()
                out = self.dir(v.id) / f"seg_{s.index:02d}.mp4"
                first, last = Path(kfs[s.from_index].image_path), Path(kfs[s.to_index].image_path)
                motion = s.prompt or "smooth natural motion between the two frames"
                builder = getattr(self.video, "build_prompt", None)
                prompt = builder(motion, v.segment_seconds, v.style_guide or "") if builder else f"{motion}. {v.style_guide or ''} Vertical 9:16 video, cinematic, no text."
                try:
                    self.video.animate(first=first, last=last, prompt=prompt, seconds=v.segment_seconds, out_path=out)
                except Exception as exc:  # noqa: BLE001
                    s.status, s.error = "FAILED", str(exc)
                    self.session.commit()
                    self._log(v, "SEGMENT", f"Segment {s.index + 1}/{len(segs)} failed: {exc}", level="error")
                    raise
                s.video_path, s.duration, s.status, s.error = str(out), _duration(out), "DONE", None
                self.session.commit()
                self._log(v, "SEGMENT", f"Segment {s.index + 1}/{len(segs)} ready ({time.time() - t0:.0f}s, {s.duration:.1f}s clip)", level="success")
            self._log(v, "CONCAT", "Joining segments into the final 1080×1920 video…")
            final = self.dir(v.id) / "final.mp4"
            self._concat([Path(s.video_path) for s in self.segments(video_id)], final)
            v.final_path = str(final)
            v.final_duration = _duration(final)
            self._status(v, "DONE", f"Video ready · {v.final_duration:.1f}s", level="success")
        except Exception as exc:  # noqa: BLE001
            self._fail(v, "animate", exc)
            raise
        return v

    def _concat(self, parts: list[Path], out: Path) -> None:
        lst = out.parent / "concat.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
        cmd = [get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        lst.unlink(missing_ok=True)

    def delete(self, video_id: str) -> None:
        v = self.get(video_id)
        self.session.delete(v)
        self.session.commit()
        shutil.rmtree(self.storage_dir / video_id, ignore_errors=True)


def _duration(path: Path) -> float:
    from app.assets.metadata import ffprobe_json

    return round(float(ffprobe_json(path).get("format", {}).get("duration") or 0), 3)
