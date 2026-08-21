"""AI Lab orchestration: plan → images → animate → concat. Independent of the content-factory pipeline."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.lab.models import LabKeyframe, LabSegment, LabVideo
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

    def _status(self, v: LabVideo, status: str, message: str | None = None) -> None:
        v.status, v.stage_message = status, message
        if status != "FAILED":
            v.error = None
        self.session.commit()
        self.progress(status, message or "")

    def _fail(self, v: LabVideo, stage: str, exc: Exception) -> None:
        v.status, v.error = "FAILED", f"{stage}: {exc}"
        self.session.commit()
        self.progress("FAILED", v.error)

    # ---------- step 0: create + plan ----------
    def create(self, prompt: str, target_duration: float, style: str | None = None) -> LabVideo:
        if not prompt or len(prompt.strip()) < 5:
            raise ValueError("describe the video you want (at least a few words)")
        if not (MIN_TARGET <= target_duration <= MAX_TARGET):
            raise ValueError(f"target_duration must be {MIN_TARGET:.0f}-{MAX_TARGET:.0f} s")
        n, seg = segment_plan(target_duration)
        v = LabVideo(prompt=prompt.strip(), style=style, target_duration=target_duration, n_segments=n, segment_seconds=seg,
                     image_model=getattr(self.image, "model", None) if self._image else get_settings().openai_image_model,
                     video_model=getattr(self.video, "model", None) if self._video else get_settings().google_video_model)
        self.session.add(v)
        self.session.commit()
        try:
            plan = self.planner.plan(prompt=v.prompt, n_keyframes=n + 1, segment_seconds=seg, style=style)
        except Exception as exc:  # noqa: BLE001
            self._fail(v, "plan", exc)
            raise
        v.style_guide = plan.style_guide
        for k in plan.keyframes:
            self.session.add(LabKeyframe(video_id=v.id, index=k.index, prompt=k.prompt, caption=k.caption))
        for i in range(n):
            motion = plan.keyframes[i].motion_to_next if i < len(plan.keyframes) else None
            self.session.add(LabSegment(video_id=v.id, index=i, from_index=i, to_index=i + 1, prompt=motion))
        self._status(v, "PLANNED", f"{n + 1} keyframes planned")
        return v

    # ---------- step 1: images ----------
    def _image_prompt(self, v: LabVideo, k: LabKeyframe) -> str:
        return f"{k.prompt}\n\nSTYLE (keep identical across frames): {v.style_guide or ''}\nVertical 9:16 portrait composition, no text, no watermark."

    def generate_images(self, video_id: str, only_missing: bool = False) -> LabVideo:
        v = self.get(video_id)
        self._status(v, "GENERATING_IMAGES", "Generating keyframe images...")
        try:
            for k in self.keyframes(video_id):
                if only_missing and k.status == "DONE" and k.image_path and Path(k.image_path).is_file():
                    continue
                self._gen_keyframe(v, k)
            self._status(v, "IMAGES_READY", "Keyframes ready — review, then animate")
        except Exception as exc:  # noqa: BLE001
            self._fail(v, "images", exc)
            raise
        return v

    def _gen_keyframe(self, v: LabVideo, k: LabKeyframe) -> None:
        k.status = "GENERATING"
        self.session.commit()
        k.version += 1
        out = self.dir(v.id) / f"kf_{k.index:02d}_v{k.version}.png"
        try:
            self.image.generate(prompt=self._image_prompt(v, k), out_path=out)
        except Exception as exc:  # noqa: BLE001
            k.status, k.error = "FAILED", str(exc)
            self.session.commit()
            raise
        k.image_path, k.status, k.error = str(out), "DONE", None
        self.session.commit()
        self.progress("IMAGE", f"keyframe {k.index} ready")

    def regenerate_keyframe(self, video_id: str, index: int, prompt: str | None = None) -> LabVideo:
        v = self.get(video_id)
        k = next((x for x in self.keyframes(video_id) if x.index == index), None)
        if k is None:
            raise KeyError(f"keyframe {index} not found")
        if prompt:
            k.prompt = prompt.strip()
        self._status(v, "GENERATING_IMAGES", f"Regenerating keyframe {index}...")
        try:
            self._gen_keyframe(v, k)
            # segments touching this frame must be re-animated
            for s in self.segments(video_id):
                if index in (s.from_index, s.to_index):
                    s.status, s.video_path = "PENDING", None
            v.final_path = None
            all_done = all(x.status == "DONE" for x in self.keyframes(video_id))
            self._status(v, "IMAGES_READY" if all_done else "PLANNED", "Keyframes ready — review, then animate" if all_done else None)
        except Exception as exc:  # noqa: BLE001
            self._fail(v, "images", exc)
            raise
        return v

    # ---------- step 2: animate ----------
    def animate(self, video_id: str) -> LabVideo:
        v = self.get(video_id)
        kfs = {k.index: k for k in self.keyframes(video_id)}
        if not kfs or any(k.status != "DONE" or not k.image_path for k in kfs.values()):
            raise RuntimeError("generate all keyframe images first")
        self._status(v, "ANIMATING", "Animating segments...")
        try:
            segs = self.segments(video_id)
            for s in segs:
                if s.status == "DONE" and s.video_path and Path(s.video_path).is_file():
                    continue
                s.status = "GENERATING"
                self.session.commit()
                out = self.dir(v.id) / f"seg_{s.index:02d}.mp4"
                first, last = Path(kfs[s.from_index].image_path), Path(kfs[s.to_index].image_path)
                motion = s.prompt or "smooth natural motion between the two frames"
                prompt = f"{motion}. {v.style_guide or ''} Vertical 9:16 video, cinematic, no text."
                try:
                    self.video.animate(first=first, last=last, prompt=prompt, seconds=v.segment_seconds, out_path=out)
                except Exception as exc:  # noqa: BLE001
                    s.status, s.error = "FAILED", str(exc)
                    self.session.commit()
                    raise
                s.video_path, s.duration, s.status, s.error = str(out), float(v.segment_seconds), "DONE", None
                self.session.commit()
                self.progress("SEGMENT", f"segment {s.index + 1}/{len(segs)} ready")
            final = self.dir(v.id) / "final.mp4"
            self._concat([Path(s.video_path) for s in self.segments(video_id)], final)
            v.final_path = str(final)
            v.final_duration = _duration(final)
            self._status(v, "DONE", f"Ready: {final}")
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
