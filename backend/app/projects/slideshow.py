"""Slideshow generation (TikTok photo-mode): the LLM writes the slides → one photo per slide is picked from the persona's
photo library → each slide is rendered as a 1080×1920 JPG with the text burned in (+ a zip of all slides). These are posted as a
photo carousel, not as a video — so no voice, no MP4."""

from __future__ import annotations

import json
import random
import zipfile
from pathlib import Path

from sqlalchemy import select

from app.assets.selector import find_candidates
from app.models import Asset, ProjectEvent, ProjectStatus, Render, VideoProject, VideoScene
from app.schemas.configs import PersonaConfig, TemplateConfig
from app.schemas.pipeline import ScriptOutput, ScriptSection, SlideshowScript

MIN_SLIDES, MAX_SLIDES = 5, 10


def n_slides_for(target_duration: float) -> int:
    return max(MIN_SLIDES, min(MAX_SLIDES, int(round(target_duration / 2.6))))


def _photo_tags(session, persona_id: str, limit: int = 60) -> list[str]:
    rows = session.execute(select(Asset.tags).where(Asset.persona_id == persona_id, Asset.kind == "image", Asset.approved.is_(True))).all()
    seen: dict[str, int] = {}
    for (tags,) in rows:
        for t in tags or []:
            seen[t] = seen.get(t, 0) + 1
    return [t for t, _ in sorted(seen.items(), key=lambda x: -x[1])][:limit]


def _cover(im, w: int, h: int):
    """Scale+centre-crop a PIL image to w×h."""
    from PIL import ImageOps

    return ImageOps.fit(im.convert("RGB"), (w, h), method=3, centering=(0.5, 0.45))


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_slide(
    photo: Path, text: str, out: Path, *, font_file: Path | None, font_size: int, anchor: float, outline: int, w: int = 1080, h: int = 1920
) -> Path:
    """One TikTok photo-mode slide: the photo cover-cropped to 1080×1920 with one bold, outlined text block."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    with Image.open(photo) as src:
        im = _cover(ImageOps.exif_transpose(src), w, h)
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype(str(font_file), font_size) if font_file else ImageFont.load_default(size=font_size)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default(size=font_size)
    max_w = int(w * 0.84)
    lines = _wrap(draw, text, font, max_w)
    # shrink until it fits in 4 lines / width
    while (len(lines) > 4 or any(draw.textlength(ln, font=font) > max_w for ln in lines)) and font_size > 48:
        font_size -= 6
        try:
            font = ImageFont.truetype(str(font_file), font_size) if font_file else ImageFont.load_default(size=font_size)
        except Exception:  # noqa: BLE001
            font = ImageFont.load_default(size=font_size)
        lines = _wrap(draw, text, font, max_w)
    line_h = int(font_size * 1.18)
    block_h = line_h * len(lines)
    y = int(h * anchor) - block_h // 2
    y = max(int(h * 0.08), min(y, h - block_h - int(h * 0.12)))
    # soft dark band behind the text for readability on busy photos
    band = Image.new("RGBA", (w, block_h + int(font_size * 0.9)), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rounded_rectangle([int(w * 0.04), 0, int(w * 0.96), band.height], radius=int(font_size * 0.35), fill=(0, 0, 0, 70))
    im.paste(band, (0, y - int(font_size * 0.45)), band)
    draw = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        tw = draw.textlength(ln, font=font)
        draw.text(((w - tw) / 2, y + i * line_h), ln, font=font, fill=(255, 255, 255), stroke_width=max(2, outline), stroke_fill=(0, 0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, format="JPEG", quality=92)
    return out


class SlideshowPipeline:
    """Runs on top of a ProjectService instance (uses its session, llm, storage, status helpers)."""

    def __init__(self, svc):
        self.svc = svc
        self.session = svc.session

    # ---------------- step 1: slides (script)
    def run_slides(self, p: VideoProject, persona: PersonaConfig, template: TemplateConfig) -> SlideshowScript:
        self.svc._set_status(p, ProjectStatus.GENERATING_SCRIPT, "Writing the slides...")
        n = n_slides_for(p.target_duration)
        try:
            out = self.svc.llm.generate_slides(
                persona=persona, template=template, topic=p.topic, n_slides=n, photo_tags=_photo_tags(self.session, persona.id)
            )
        except Exception as exc:  # noqa: BLE001
            self.svc._fail(p, "script", exc)
            raise
        slides = [s for s in out.slides if s.text.strip()][:MAX_SLIDES]
        if len(slides) < 2:
            exc = RuntimeError("the model returned too few slides")
            self.svc._fail(p, "script", exc)
            raise exc
        for i, s in enumerate(slides):
            s.index = i
            s.seconds = float(max(2.0, min(4.5, s.seconds or 2.8)))
        out.slides = slides
        # persist as the project's script (so the Script tab / regenerate work) + the raw slides JSON
        script = ScriptOutput(
            hook=slides[0].text,
            sections=[
                ScriptSection(type="hook" if i == 0 else "closing" if i == len(slides) - 1 else "slides", text=s.text)
                for i, s in enumerate(slides)
            ],
            notes=f"slideshow · post caption: {out.post_caption}",
        )
        self.svc._save_script(p, script)
        (self.svc.project_dir(p.id) / f"slides_v{p.script_version}.json").write_text(out.model_dump_json(indent=2))
        self.session.add(
            ProjectEvent(project_id=p.id, stage="SCRIPT", message=f"{len(slides)} slides · post caption: {out.post_caption[:120]}")
        )
        self.session.commit()
        return out

    def load_slides(self, p: VideoProject) -> SlideshowScript:
        return SlideshowScript.model_validate_json((self.svc.project_dir(p.id) / f"slides_v{p.script_version}.json").read_text())

    # ---------------- step 2: photos + plan (+ silent voice)
    def run_photos(
        self,
        p: VideoProject,
        persona: PersonaConfig,
        template: TemplateConfig,
        *,
        exclude_asset_ids: set[str] | None = None,
        seed: int | None = None,
    ) -> list[dict]:
        """Pick one library photo per slide → plan_v{n}.json [{order, asset_id, asset_file, text, section, tags}] + VideoScene rows."""
        slides = self.load_slides(p).slides
        self.svc._set_status(p, ProjectStatus.SELECTING_ASSETS, "Picking photos...")
        exclude = set(exclude_asset_ids or set())
        rng = random.Random(seed if seed is not None else random.randint(1, 2**31 - 1))
        have = (
            self.session.execute(select(Asset).where(Asset.persona_id == persona.id, Asset.kind == "image", Asset.approved.is_(True)))
            .scalars()
            .all()
        )
        if not have:
            exc = RuntimeError("no approved photos in this persona's library — upload photos on the B-roll page (Photos) first")
            self.svc._fail(p, "plan", exc)
            raise exc
        used: set[str] = set()
        plan: list[dict] = []
        for s in slides:
            cands = find_candidates(self.session, s.query_tags, limit=12, exclude_ids=exclude | used, persona_id=persona.id, kind="image")
            if not cands:
                cands = find_candidates(
                    self.session,
                    s.query_tags or ["photo"],
                    limit=12,
                    exclude_ids=used,
                    persona_id=persona.id,
                    kind="image",
                    min_relevance=-1.0,
                )
            if cands:
                top = cands[: min(3, len(cands))]
                pick = top[0].asset if len(top) == 1 else rng.choice(top).asset
            else:  # fewer photos than slides → allow repeats, prefer least used
                pick = min(have, key=lambda a: (a.id in used, a.usage_count, rng.random()))
            used.add(pick.id)
            plan.append(
                {
                    "order": len(plan),
                    "asset_id": pick.id,
                    "asset_file": pick.file,
                    "text": s.text,
                    "section": "hook" if s.index == 0 else "closing" if s.index == len(slides) - 1 else "slides",
                    "intent": s.photo_intent,
                    "tags": s.query_tags,
                }
            )
        p.plan_version += 1
        (self.svc.project_dir(p.id) / f"plan_v{p.plan_version}.json").write_text(
            json.dumps({"kind": "slideshow", "seed": rng.randint(1, 2**31 - 1), "slides": plan}, indent=2, ensure_ascii=False)
        )
        for sc in plan:
            self.session.add(
                VideoScene(
                    project_id=p.id,
                    plan_version=p.plan_version,
                    order=sc["order"],
                    asset_id=sc["asset_id"],
                    start_time=float(sc["order"]),
                    end_time=float(sc["order"] + 1),
                    asset_start_time=0.0,
                    overlay_text=sc["text"],
                    section=sc["section"],
                    intent=sc["intent"],
                    query_tags=sc["tags"],
                )
            )
        for a in self.session.execute(select(Asset).where(Asset.id.in_(used))).scalars():
            a.usage_count = (a.usage_count or 0) + 1
        p.actual_duration = None
        self.session.add(ProjectEvent(project_id=p.id, stage="PLANNING", message=f"{len(plan)} slides · {len(used)} photos"))
        self.session.commit()
        return plan

    def load_photo_plan(self, p: VideoProject) -> list[dict]:
        return json.loads((self.svc.project_dir(p.id) / f"plan_v{p.plan_version}.json").read_text())["slides"]

    # ---------------- step 3: render the slides as images (+ zip)
    def run_render(self, p: VideoProject, persona: PersonaConfig, template: TemplateConfig) -> Render:
        from app.captions.fonts import find_font_file
        from app.models import Render, utcnow

        plan = self.load_photo_plan(p)
        self.svc._set_status(p, ProjectStatus.RENDERING, "Rendering slides...")
        style = self.svc.caption_style_for(p, template)
        ov = style.overlay
        font_file = find_font_file(ov.font_name, ov.bold, self.svc.fonts_dir if self.svc.fonts_dir.is_dir() else None)
        version = p.render_version + 1
        r = Render(project_id=p.id, version=version, plan_version=p.plan_version, voice_version=p.voice_version, seed=0, status="RUNNING")
        self.session.add(r)
        self.session.commit()
        out_dir = self.svc.renders_dir(p.id) / f"slides_v{version}"
        try:
            files: list[Path] = []
            for sc in plan:
                src = self.svc.assets_dir / sc["asset_file"]
                if not src.is_file():
                    raise RuntimeError(f"photo missing: {sc['asset_file']}")
                out = out_dir / f"slide_{sc['order'] + 1:02d}.jpg"
                render_slide(
                    src,
                    sc["text"],
                    out,
                    font_file=font_file,
                    font_size=int(ov.font_size),
                    anchor=float(ov.vertical_anchor_ratio),
                    outline=int(ov.outline),
                )
                files.append(out)
            zip_path = out_dir / "slides.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(f, arcname=f.name)
            r.output_path, r.status, r.finished_at = str(zip_path), "DONE", utcnow()
            r.qc = {"passed": True, "slides": len(files), "width": 1080, "height": 1920}
            p.render_version = version
            p.current_render_id = r.id
            self.svc._set_status(p, ProjectStatus.READY, f"Ready: {len(files)} slides ({zip_path.name})")
            self.session.add(ProjectEvent(project_id=p.id, stage="RENDER", message=f"{len(files)} slides rendered as 1080×1920 JPG"))
            self.session.commit()
        except Exception as exc:  # noqa: BLE001
            r.status, r.error = "FAILED", str(exc)
            self.session.commit()
            self.svc._fail(p, "render", exc)
            raise
        return r

    def slide_files(self, p: VideoProject) -> list[Path]:
        d = self.svc.renders_dir(p.id) / f"slides_v{p.render_version}"
        return sorted(d.glob("slide_*.jpg")) if p.render_version and d.is_dir() else []

    # ---------------- full run
    def generate(self, p: VideoProject, persona: PersonaConfig, template: TemplateConfig) -> None:
        self.run_slides(p, persona, template)
        self.run_photos(p, persona, template)
        self.run_render(p, persona, template)

    def change_photos(self, p: VideoProject, persona: PersonaConfig, template: TemplateConfig) -> None:
        prev = self.load_photo_plan(p) if p.plan_version else []
        self.run_photos(p, persona, template, exclude_asset_ids={sc["asset_id"] for sc in prev})
        self.run_render(p, persona, template)

    def set_slide_photo(self, p: VideoProject, persona: PersonaConfig, template: TemplateConfig, order: int, asset_id: str) -> None:
        """Manual override: use a specific photo for one slide (new plan version, images re-rendered)."""
        a = self.session.get(Asset, asset_id)
        if a is None or a.kind != "image":
            raise ValueError("pick a photo from the library")
        plan = self.load_photo_plan(p)
        if not any(sc["order"] == order for sc in plan):
            raise ValueError(f"no slide {order}")
        for sc in plan:
            if sc["order"] == order:
                sc["asset_id"], sc["asset_file"] = a.id, a.file
        p.plan_version += 1
        (self.svc.project_dir(p.id) / f"plan_v{p.plan_version}.json").write_text(
            json.dumps({"kind": "slideshow", "seed": 0, "slides": plan}, indent=2, ensure_ascii=False)
        )
        for sc in plan:
            self.session.add(
                VideoScene(
                    project_id=p.id,
                    plan_version=p.plan_version,
                    order=sc["order"],
                    asset_id=sc["asset_id"],
                    start_time=float(sc["order"]),
                    end_time=float(sc["order"] + 1),
                    asset_start_time=0.0,
                    overlay_text=sc["text"],
                    section=sc["section"],
                    intent=sc.get("intent"),
                    query_tags=sc.get("tags") or [],
                )
            )
        a.usage_count = (a.usage_count or 0) + 1
        self.session.commit()
        self.run_render(p, persona, template)

    def render_again(self, p: VideoProject, persona: PersonaConfig, template: TemplateConfig) -> None:
        if not p.plan_version:
            raise RuntimeError("generate first")
        self.run_render(p, persona, template)
