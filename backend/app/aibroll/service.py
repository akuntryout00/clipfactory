"""AI B-roll pipeline: scene text (+ optional persona photo) → keyframe (OpenAI images, identity-preserving edit) →
video model (fal.ai / Omni / Veo, single start frame) → normalized 1080×1920 clip → registered as an approved library asset
(assigned to the shot-list item it was created for)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.importer import register_asset_file
from app.config.settings import get_settings
from app.lab.providers import FalImageEdit, ImageGen, ImageModerationError, VideoGen, get_image_gen, get_video_gen, provider_meta
from app.models import AiBrollJob, Asset, ShotlistItem

log = logging.getLogger(__name__)

MIN_SECONDS, MAX_SECONDS = 3, 15
REFERENCE_MAX_PX = 1536
DEFAULT_PROVIDER = "fal:seedance-2.0"


def persona_image_path(storage_dir: Path, persona_id: str) -> Path:
    return Path(storage_dir) / "personas" / persona_id / "reference.png"


def _to_png(data: bytes, dest: Path) -> Path:
    from io import BytesIO

    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
    img.thumbnail((REFERENCE_MAX_PX, REFERENCE_MAX_PX))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return dest


def save_persona_image(storage_dir: Path, persona_id: str, data: bytes) -> Path:
    """Store the persona's reference photo as PNG (max 1536 px on the long side, EXIF-rotated)."""
    return _to_png(data, persona_image_path(storage_dir, persona_id))


class AiBrollService:
    def __init__(
        self,
        session: Session,
        *,
        storage_dir: Path | None = None,
        assets_dir: Path | None = None,
        image: ImageGen | None = None,
        video: VideoGen | None = None,
        image_fallback: ImageGen | None = None,
        progress=None,
    ):
        s = get_settings()
        self.session = session
        self.storage_dir = Path(storage_dir or s.storage_dir)
        self.assets_dir = Path(assets_dir or s.assets_dir)
        self._image = image
        self._video = video
        self._image_fallback = image_fallback
        self.progress = progress or (lambda job_id, stage, msg: None)

    # ---------------- helpers
    def job_dir(self, job_id: str) -> Path:
        d = self.storage_dir / "ai_broll" / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _image_gen(self) -> ImageGen:
        return self._image or get_image_gen()

    def _video_gen(self, provider: str) -> VideoGen:
        return self._video or get_video_gen(provider)

    def _get(self, job_id: str) -> AiBrollJob:
        j = self.session.get(AiBrollJob, job_id)
        if j is None:
            raise KeyError(f"job not found: {job_id}")
        return j

    def _set(self, j: AiBrollJob, status: str, msg: str | None = None) -> None:
        j.status = status
        j.stage_message = msg
        self.session.commit()
        self.progress(j.id, status, msg or "")

    # ---------------- create
    def create(
        self,
        *,
        persona_id: str,
        prompt: str,
        title: str | None = None,
        category: str = "ai",
        shot: str | None = None,
        action: str | None = None,
        location: str | None = None,
        mood: str | None = None,
        tags: list[str] | None = None,
        seconds: int = 5,
        video_provider: str | None = None,
        use_reference: bool = False,
        reference_bytes: bytes | None = None,
        shotlist_item_id: str | None = None,
    ) -> AiBrollJob:
        provider = video_provider or DEFAULT_PROVIDER
        meta = provider_meta(provider)  # raises for unknown providers
        secs = max(max(MIN_SECONDS, meta["min_seconds"]), min(min(MAX_SECONDS, meta["max_seconds"]), int(seconds)))
        if shotlist_item_id and self.session.get(ShotlistItem, shotlist_item_id) is None:
            raise ValueError("unknown shot-list item")
        cat = "".join(ch for ch in (category or "ai").lower().strip().replace(" ", "_") if ch.isalnum() or ch == "_") or "ai"
        j = AiBrollJob(
            persona_id=persona_id,
            shotlist_item_id=shotlist_item_id,
            title=(title or prompt.strip().split("\n")[0])[:128],
            prompt=prompt.strip(),
            category=cat,
            shot=shot or None,
            action=(action or "").strip().lower().replace(" ", "_")[:64] or None,
            location=location or None,
            mood=mood or None,
            tags=[t.strip().lower() for t in (tags or []) if t.strip()][:12],
            seconds=secs,
            video_provider=provider,
            use_reference=bool(use_reference),
        )
        self.session.add(j)
        self.session.flush()
        ref: Path | None = None
        if reference_bytes:
            ref = _to_png(reference_bytes, self.job_dir(j.id) / "reference.png")
            j.use_reference = True
        elif j.use_reference:
            pp = persona_image_path(self.storage_dir, persona_id)
            if not pp.is_file():
                raise ValueError("this persona has no photo yet — upload one or turn the face option off")
            ref = pp
        j.reference_path = str(ref) if ref else None
        self.session.commit()
        return j

    # ---------------- run
    def run(self, job_id: str) -> AiBrollJob:
        j = self._get(job_id)
        d = self.job_dir(j.id)
        try:
            self._set(j, "KEYFRAME", "Creating the start frame" + (" with the persona's face…" if j.reference_path else "…"))
            kf = d / "keyframe.png"
            ref = Path(j.reference_path) if j.reference_path else None
            scene = self._scene_prompt(j)
            if ref is not None and ref.is_file():
                self._identity_keyframe(j, scene, ref, kf)
            else:
                self._image_gen().generate(prompt=scene, out_path=kf)
            j.keyframe_path = str(kf)
            self.session.commit()
            self._set(j, "ANIMATING", f"Animating {j.seconds}s with {provider_meta(j.video_provider)['label']}…")
            clip = d / "clip.mp4"
            self._video_gen(j.video_provider).animate(first=kf, last=None, prompt=self._motion_prompt(j), seconds=j.seconds, out_path=clip)
            j.video_path = str(clip)
            self.session.commit()
            self._set(j, "IMPORTING", "Adding the clip to the B-roll library…")
            asset = self._import(j, clip)
            j.asset_id = asset.id
            self._set(j, "DONE", f"Ready — {asset.id} in assets/{j.persona_id}/{j.category}/")
        except Exception as exc:  # noqa: BLE001
            j.error = str(exc)[:2000]
            self._set(j, "FAILED", f"{type(exc).__name__}: {str(exc)[:300]}")
            log.exception("ai b-roll job %s failed", j.id)
            raise
        return j

    def _identity_keyframe(self, j: AiBrollJob, scene: str, ref: Path, kf: Path) -> None:
        """Face-consistent start frame: OpenAI edit (softened prompts) → on a safety refusal, fal nano-banana edit if a FAL key exists."""
        try:
            self._image_gen().generate(prompt=scene, out_path=kf, reference=ref, identity=True, quality="high")
            return
        except ImageModerationError as exc:
            fb = self._image_fallback or (FalImageEdit() if get_settings().fal_key else None)
            if fb is None:
                raise RuntimeError(
                    "the image provider refused to use this photo (safety system). Try a different photo (front-facing, neutral "
                    "background) or add a fal.ai key in Settings — then the face frame is made with Gemini image editing instead."
                ) from exc
            self._set(j, "KEYFRAME", "OpenAI refused the photo — placing the face into the scene with fal.ai (nano-banana)…")
            fb.generate(prompt=scene, out_path=kf, reference=ref, identity=True, quality="high")

    def _scene_prompt(self, j: AiBrollJob) -> str:
        bits = [j.prompt]
        if j.shot:
            bits.append(f"Framing: {j.shot} shot.")
        if j.location:
            bits.append(f"Place: {j.location}.")
        if j.mood:
            bits.append(f"Mood: {j.mood}.")
        bits.append("Realistic everyday B-roll for a vertical 9:16 video, natural light, candid, no text or logos.")
        return " ".join(bits)

    def _motion_prompt(self, j: AiBrollJob) -> str:
        base = f"{j.prompt}. Subtle, natural motion: the action continues smoothly; handheld-steady camera, no cuts, no text."
        if j.reference_path:
            base += " Keep the person's face exactly as in the start frame — same identity, sharp facial detail, no morphing."
        return base

    def _import(self, j: AiBrollJob, clip: Path) -> Asset:
        rel_dir = Path(j.persona_id) / j.category
        (self.assets_dir / rel_dir).mkdir(parents=True, exist_ok=True)
        name = f"ai_{j.id.split('_')[-1]}.mp4"
        dest = self.assets_dir / rel_dir / name
        shutil.copyfile(clip, dest)
        rel = (rel_dir / name).as_posix()
        tags = list(dict.fromkeys([*(j.tags or []), "ai", "generated"]))
        asset = register_asset_file(
            self.session,
            self.assets_dir,
            rel,
            description=j.prompt,
            tags=tags,
            approved=True,
            quality_score=0.8,
            action=j.action,
            location=j.location,
            shot=j.shot,
            mood=j.mood,
            persona_id=j.persona_id,
        )
        if j.shotlist_item_id:
            asset.shotlist_item_id = j.shotlist_item_id
        self.session.commit()
        return asset

    # ---------------- listing
    def list(self, persona_id: str | None = None, limit: int = 100) -> list[AiBrollJob]:
        q = select(AiBrollJob).order_by(AiBrollJob.created_at.desc()).limit(limit)
        if persona_id:
            q = q.where(AiBrollJob.persona_id == persona_id)
        return list(self.session.execute(q).scalars())

    def delete(self, job_id: str) -> None:
        j = self._get(job_id)
        shutil.rmtree(self.storage_dir / "ai_broll" / j.id, ignore_errors=True)
        self.session.delete(j)
        self.session.commit()

    def retry(self, job_id: str) -> AiBrollJob:
        j = self._get(job_id)
        j.error = None
        self._set(j, "QUEUED", "Queued again")
        return j


def estimate(provider: str, seconds: int, with_reference: bool) -> dict:
    meta = provider_meta(provider)
    secs = max(max(MIN_SECONDS, meta["min_seconds"]), min(min(MAX_SECONDS, meta["max_seconds"]), int(seconds)))
    video_cost = round(secs * float(meta["price_per_second"]), 2)
    q = (get_settings().openai_image_quality or "low").lower()
    image_cost = 0.19 if with_reference else {"low": 0.02, "medium": 0.07, "high": 0.19}.get(q, 0.02)
    return {
        "provider": meta["id"],
        "label": meta["label"],
        "seconds": secs,
        "video_cost": video_cost,
        "image_cost": image_cost,
        "total": round(video_cost + image_cost, 2),
        "note": "list prices; the start frame uses high quality when a face photo is given",
    }
