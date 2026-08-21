"""Project orchestration: staged pipeline, versioned artifacts, regeneration controls (PRD §29, §43–45)."""
from __future__ import annotations

import json
import logging
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.catalog import library_summary
from app.assets.selector import extract_query_tags, find_candidates
from app.config.loaders import list_templates, load_caption_style, load_persona, load_template
from app.config.settings import get_settings
from app.content.asset_assignment import assign_assets
from app.content.scene_planner import heuristic_plan, normalize_plan
from app.content.script_generator import generate_script, shorten_script, target_word_range, words_of
from app.llm.base import LLMProvider, get_llm
from app.models import (
    Asset, AssetUsage, ProjectEvent, ProjectStatus, Render, VideoProject, VideoScene, VoiceGeneration, utcnow,
)
from app.renderer.ffmpeg import RenderOptions, render_video
from app.renderer.qc import run_qc
from app.schemas.configs import PersonaConfig, TemplateConfig
from app.schemas.pipeline import NormalizedScene, ScriptOutput, VideoJSON, VoiceResult, WordTiming
from app.voice.base import VoiceProvider, get_voice_provider

log = logging.getLogger(__name__)

MAX_REWRITES = 2
MIN_TARGET, MAX_TARGET = 15.0, 25.0

ProgressFn = Callable[[str, str], None]


class ProjectService:
    def __init__(self, session: Session, llm: LLMProvider | None = None, voice: VoiceProvider | None = None,
                 storage_dir: Path | None = None, assets_dir: Path | None = None, progress: ProgressFn | None = None,
                 render_preset: str | None = None, render_crf: int | None = None, configs_dir: Path | None = None):
        s = get_settings()
        self.session = session
        self.configs_dir = Path(configs_dir) if configs_dir else None
        self._llm = llm
        self._voice = voice
        self.storage_dir = Path(storage_dir or s.storage_dir)
        self.assets_dir = Path(assets_dir or s.assets_dir)
        self.progress = progress or (lambda stage, msg: None)
        self.render_options = RenderOptions(preset=render_preset or "veryfast", crf=render_crf or 20, threads=s.render_threads)

    # lazy providers so the fake/real choice happens at first use
    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = get_llm()
        return self._llm

    @property
    def voice(self) -> VoiceProvider:
        if self._voice is None:
            self._voice = get_voice_provider()
        return self._voice

    # ---------- paths / artifacts ----------

    def project_dir(self, project_id: str) -> Path:
        d = self.storage_dir / "projects" / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def renders_dir(self, project_id: str) -> Path:
        d = self.storage_dir / "renders" / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_script(self, project_id: str, version: int) -> ScriptOutput:
        return ScriptOutput.model_validate_json((self.project_dir(project_id) / f"script_v{version}.json").read_text())

    def load_words(self, project_id: str, voice_version: int) -> list[WordTiming]:
        data = json.loads((self.project_dir(project_id) / f"voice_v{voice_version}.words.json").read_text())
        return [WordTiming.model_validate(w) for w in data]

    def load_plan(self, project_id: str, version: int) -> VideoJSON:
        return VideoJSON.model_validate_json((self.project_dir(project_id) / f"plan_v{version}.json").read_text())

    # ---------- helpers ----------

    def _get(self, project_id: str) -> VideoProject:
        p = self.session.get(VideoProject, project_id)
        if p is None:
            raise KeyError(f"project not found: {project_id}")
        return p

    def _set_status(self, p: VideoProject, status: ProjectStatus, message: str | None = None) -> None:
        p.status = status.value
        p.stage_message = message
        if status != ProjectStatus.FAILED:
            p.error = None
        self.session.add(ProjectEvent(project_id=p.id, stage=status.value, message=message or status.value))
        self.session.commit()
        self.progress(status.value, message or "")

    def _fail(self, p: VideoProject, stage: str, exc: Exception) -> None:
        p.status = ProjectStatus.FAILED.value
        p.error = f"{stage}: {exc}"
        self.session.add(ProjectEvent(project_id=p.id, stage=stage, level="error", message=str(exc)))
        self.session.commit()
        self.progress("FAILED", p.error)

    def _configs(self, p: VideoProject) -> tuple[PersonaConfig, TemplateConfig]:
        return load_persona(p.persona_id, self.configs_dir), load_template(p.template_id, self.configs_dir)

    # ---------- project CRUD ----------

    def create_project(self, topic: str, template_id: str, persona_id: str | None = None, target_duration: float | None = None) -> VideoProject:
        persona = load_persona(persona_id or get_settings().default_persona, self.configs_dir)
        template = load_template(template_id, self.configs_dir)  # raises FileNotFoundError if unknown
        td = float(target_duration if target_duration is not None else persona.target_duration or template.duration.target)
        if not (MIN_TARGET <= td <= MAX_TARGET):
            raise ValueError(f"target_duration must be within {MIN_TARGET:.0f}-{MAX_TARGET:.0f} s")
        if not topic or not topic.strip():
            raise ValueError("topic is required")
        p = VideoProject(persona_id=persona.id, template_id=template.id, topic=topic.strip(), target_duration=td)
        self.session.add(p)
        self.session.commit()
        self.session.add(ProjectEvent(project_id=p.id, stage="DRAFT", message="project created"))
        self.session.commit()
        return p

    def get_project(self, project_id: str) -> VideoProject:
        return self._get(project_id)

    def list_projects(self, limit: int = 50) -> list[VideoProject]:
        return list(self.session.execute(select(VideoProject).order_by(VideoProject.created_at.desc()).limit(limit)).scalars())

    # ---------- stages ----------

    def run_script(self, project_id: str) -> ScriptOutput:
        p = self._get(project_id)
        persona, template = self._configs(p)
        self._set_status(p, ProjectStatus.GENERATING_SCRIPT, "Generating script...")
        try:
            script = generate_script(self.llm, persona, template, p.topic, p.target_duration)
        except Exception as exc:  # noqa: BLE001
            self._fail(p, "script", exc)
            raise
        self._save_script(p, script)
        return script

    def _save_script(self, p: VideoProject, script: ScriptOutput) -> None:
        p.script_version += 1
        p.script = script.full_text
        (self.project_dir(p.id) / f"script_v{p.script_version}.json").write_text(script.model_dump_json(indent=2))
        self.session.add(ProjectEvent(project_id=p.id, stage="SCRIPT", message=f"script v{p.script_version}: {len(words_of(script.full_text))} words"))
        self.session.commit()

    def run_voice(self, project_id: str) -> VoiceResult:
        """Synthesize voice; if longer than the template/persona max, shorten the script and retry (≤2)."""
        p = self._get(project_id)
        persona, template = self._configs(p)
        if p.script_version == 0:
            raise RuntimeError("run_script first")
        self._set_status(p, ProjectStatus.GENERATING_VOICE, "Generating voice...")
        max_dur = min(persona.max_duration, template.duration.max, MAX_TARGET)
        script = self.load_script(p.id, p.script_version)
        rewrites = 0
        try:
            while True:
                version = p.voice_version + 1
                out = self.project_dir(p.id) / f"voice_v{version}.mp3"
                res = self.voice.synthesize(text=script.for_speech().full_text, voice=persona.voice, out_path=out)
                p.voice_version = version
                (self.project_dir(p.id) / f"voice_v{version}.words.json").write_text(json.dumps([w.model_dump() for w in res.words]))
                vg = VoiceGeneration(project_id=p.id, version=version, script_version=p.script_version, provider=res.provider,
                                     audio_path=res.audio_path, alignment_path=res.alignment_path, duration=res.duration)
                self.session.add(vg)
                p.actual_duration = res.duration
                self.session.add(ProjectEvent(project_id=p.id, stage="VOICE", message=f"voice v{version}: {res.duration:.2f}s"))
                self.session.commit()
                self.progress("VOICE", f"Voice generated: {res.duration:.1f} sec")
                if res.duration <= max_dur:
                    return res
                if rewrites >= MAX_REWRITES:
                    raise RuntimeError(f"voice is {res.duration:.1f}s > max {max_dur:.0f}s after {MAX_REWRITES} rewrites")
                rewrites += 1
                ratio = max_dur / res.duration
                target_words = max(12, int(len(words_of(script.full_text)) * ratio * 0.92))
                self.progress("VOICE", f"Voice too long ({res.duration:.1f}s > {max_dur:.0f}s) — shortening script to ~{target_words} words")
                script = shorten_script(self.llm, persona, template, script, target_words, reason=f"{res.duration:.1f}s audio > {max_dur:.0f}s max")
                self._save_script(p, script)
        except Exception as exc:  # noqa: BLE001
            self._fail(p, "voice", exc)
            raise

    def run_plan(self, project_id: str, *, exclude_asset_ids: set[str] | None = None, seed: int | None = None,
                 fixed_assets: dict[int, str] | None = None, reuse_scenes: bool = False) -> VideoJSON:
        """Scene planning + asset selection + captions → validated Video JSON (plan_vN.json)."""
        p = self._get(project_id)
        persona, template = self._configs(p)
        if p.voice_version == 0:
            raise RuntimeError("run_voice first")
        self._set_status(p, ProjectStatus.PLANNING, "Planning scenes...")
        try:
            script = self.load_script(p.id, p.script_version).for_speech()  # spoken words == alignment words
            words = self.load_words(p.id, p.voice_version)
            vg = self._voice_row(p)
            scenes = None
            if reuse_scenes and p.plan_version:
                scenes = self._scenes_from_plan(p.id, p.plan_version, self.load_plan(p.id, p.plan_version), words)
            if scenes is None:
                try:
                    raw = self.llm.plan_scenes(persona=persona, template=template, topic=p.topic, script=script, words=words,
                                               voice_duration=vg.duration, library=library_summary(self.session))
                except Exception as exc:  # noqa: BLE001 — heuristic fallback keeps the pipeline alive
                    log.warning("LLM scene planning failed (%s); using heuristic planner", exc)
                    self.session.add(ProjectEvent(project_id=p.id, stage="PLANNING", level="warning", message=f"LLM plan failed, heuristic used: {exc}"))
                    raw = heuristic_plan(script, words, template)
                scenes = normalize_plan(raw, words, template, vg.duration)
            self.progress("PLANNING", f"{len(scenes)} scenes planned.")
            self._set_status(p, ProjectStatus.SELECTING_ASSETS, "Selecting B-roll...")
            style = load_caption_style(template.caption_style, self.configs_dir)
            new_seed = seed if seed is not None else random.randint(1, 2**31 - 1)
            music = self._pick_music(template, persona)
            video = assign_assets(session=self.session, llm=self.llm, persona=persona, template=template, topic=p.topic,
                                  scenes=scenes, words=words, voice_audio=Path(vg.audio_path).name, voice_duration=vg.duration,
                                  caption_style=style, seed=new_seed, exclude_asset_ids=exclude_asset_ids,
                                  fixed_assets=fixed_assets, music=music)
            self._set_status(p, ProjectStatus.GENERATING_CAPTIONS, "Generating captions...")
            p.plan_version += 1
            (self.project_dir(p.id) / f"plan_v{p.plan_version}.json").write_text(video.model_dump_json(indent=2))
            for sc, ns in zip(video.scenes, scenes):
                self.session.add(VideoScene(project_id=p.id, plan_version=p.plan_version, order=sc.order, asset_id=sc.asset_id,
                                            start_time=sc.start, end_time=sc.end, asset_start_time=sc.asset_start,
                                            overlay_text=sc.text, section=sc.section, intent=ns.intent, query_tags=ns.query_tags))
            self.session.add(ProjectEvent(project_id=p.id, stage="PLAN", message=f"plan v{p.plan_version}: {len(video.scenes)} scenes, assets {[s.asset_id for s in video.scenes]}"))
            self.session.commit()
            self.progress("ASSETS", "Assets selected: " + ", ".join(s.asset_id for s in video.scenes))
            return video
        except Exception as exc:  # noqa: BLE001
            self._fail(p, "plan", exc)
            raise

    def run_render(self, project_id: str) -> Render:
        p = self._get(project_id)
        persona, template = self._configs(p)
        if p.plan_version == 0:
            raise RuntimeError("run_plan first")
        self._set_status(p, ProjectStatus.RENDERING, "Rendering video...")
        video = self.load_plan(p.id, p.plan_version)
        vg = self._voice_row(p)
        version = p.render_version + 1
        r = Render(project_id=p.id, version=version, plan_version=p.plan_version, voice_version=p.voice_version, seed=video.seed, status="RUNNING")
        self.session.add(r)
        self.session.commit()
        out = self.renders_dir(p.id) / f"render_v{version}.mp4"
        work = self.storage_dir / "temp" / p.id / f"render_v{version}"
        try:
            style = load_caption_style(template.caption_style, self.configs_dir)
            music_path = (self.storage_dir / "music" / video.music) if video.music else None
            render_video(video, assets_dir=self.assets_dir, voice_path=Path(vg.audio_path), out_path=out, style=style,
                         work_dir=work, music_path=music_path, options=self.render_options)
            qc = run_qc(out, expected_duration=video.total_duration)
            r.qc = qc
            r.output_path = str(out)
            r.finished_at = utcnow()
            if not qc["passed"]:
                r.status = "FAILED"
                raise RuntimeError("render QC failed: " + "; ".join(qc["failures"]))
            r.status = "DONE"
            p.render_version = version
            p.current_render_id = r.id
            shutil.copyfile(out, self.project_dir(p.id) / "final.mp4")
            self._record_usage(p, video, r)
            self.session.commit()
            self._set_status(p, ProjectStatus.READY, f"Ready: {out}")
            shutil.rmtree(work, ignore_errors=True)
            return r
        except Exception as exc:  # noqa: BLE001
            r.status = "FAILED"
            r.error = str(exc)
            self.session.commit()
            self._fail(p, "render", exc)
            raise

    # ---------- full pipeline + controls ----------

    def generate(self, project_id: str) -> VideoProject:
        self.run_script(project_id)
        self.run_voice(project_id)
        self.run_plan(project_id)
        self.run_render(project_id)
        return self._get(project_id)

    def regenerate_script(self, project_id: str) -> VideoProject:
        """New hook/script → voice → plan → render (PRD §24)."""
        return self.generate(project_id)

    def change_assets(self, project_id: str) -> VideoProject:
        """Keep script + voice; re-plan with previously used assets excluded; render."""
        p = self._get(project_id)
        prev = {s.asset_id for s in self.load_plan(p.id, p.plan_version).scenes} if p.plan_version else set()
        self.run_plan(project_id, exclude_asset_ids=prev, reuse_scenes=True)
        self.run_render(project_id)
        return self._get(project_id)

    def render_again(self, project_id: str) -> VideoProject:
        """Same content + same assets; new seed → new start offsets / crop / zoom (PRD §24)."""
        p = self._get(project_id)
        if p.plan_version == 0:
            raise RuntimeError("nothing to re-render yet")
        old = self.load_plan(p.id, p.plan_version)
        fixed = {s.order: s.asset_id for s in old.scenes}
        seed = old.seed
        while seed == old.seed:
            seed = random.randint(1, 2**31 - 1)
        self.run_plan(project_id, seed=seed, fixed_assets=fixed, reuse_scenes=True)
        self.run_render(project_id)
        return self._get(project_id)

    def retry(self, project_id: str) -> VideoProject:
        """Resume a FAILED project from the first missing stage (stage-level retry, PRD §44)."""
        p = self._get(project_id)
        if p.script_version == 0:
            self.run_script(project_id)
        if p.voice_version == 0 or p.status == ProjectStatus.FAILED.value and (p.error or "").startswith("voice"):
            self.run_voice(project_id)
        if p.plan_version == 0 or (p.error or "").startswith("plan"):
            self.run_plan(project_id)
        self.run_render(project_id)
        return self._get(project_id)

    def approve(self, project_id: str) -> VideoProject:
        p = self._get(project_id)
        if p.status != ProjectStatus.READY.value:
            raise RuntimeError(f"only READY projects can be approved (status={p.status})")
        p.approved_at = datetime.now(timezone.utc)
        self._set_status(p, ProjectStatus.APPROVED, "Approved")
        return p

    def suggest_assets(self, project_id: str, scene_order: int, limit: int = 8) -> list[dict]:
        p = self._get(project_id)
        sc = self.session.execute(select(VideoScene).where(VideoScene.project_id == p.id, VideoScene.plan_version == p.plan_version,
                                                           VideoScene.order == scene_order)).scalar_one()
        tags = extract_query_tags(list(sc.query_tags or []) + [sc.intent or ""])
        current = {s.asset_id for s in self.session.execute(select(VideoScene).where(VideoScene.project_id == p.id, VideoScene.plan_version == p.plan_version)).scalars()}
        cands = find_candidates(self.session, tags, limit=limit, exclude_ids=current, min_relevance=-1.0)
        return [c.as_dict() for c in cands]

    def override_scene_asset(self, project_id: str, scene_order: int, asset_id: str) -> VideoProject:
        p = self._get(project_id)
        if self.session.get(Asset, asset_id) is None:
            raise ValueError(f"unknown asset {asset_id}")
        old = self.load_plan(p.id, p.plan_version)
        fixed = {s.order: s.asset_id for s in old.scenes}
        if scene_order not in fixed:
            raise ValueError(f"scene {scene_order} not in current plan")
        fixed[scene_order] = asset_id
        self.run_plan(project_id, seed=old.seed, fixed_assets=fixed, reuse_scenes=True)
        self.run_render(project_id)
        return self._get(project_id)

    # ---------- internals ----------

    def _voice_row(self, p: VideoProject) -> VoiceGeneration:
        return self.session.execute(select(VoiceGeneration).where(VoiceGeneration.project_id == p.id, VoiceGeneration.version == p.voice_version)).scalar_one()

    def _scenes_from_plan(self, project_id: str, plan_version: int, plan: VideoJSON, words: list[WordTiming]) -> list[NormalizedScene]:
        """Rebuild NormalizedScene objects (timings + intent/tags) from a stored plan so re-plans keep the same cut."""
        rows = {r.order: r for r in self.session.execute(select(VideoScene).where(
            VideoScene.project_id == project_id, VideoScene.plan_version == plan_version)).scalars()}
        scenes = []
        for s in plan.scenes:
            first = next((i for i, w in enumerate(words) if w.start >= s.start - 1e-6), 0)
            last = max(first, next((i for i in range(len(words) - 1, -1, -1) if words[i].end <= s.end + 1e-6), first))
            db = rows.get(s.order)
            scenes.append(NormalizedScene(order=s.order, section=s.section or "", start=s.start, end=s.end, first_word=first,
                                          last_word=last, intent=(db.intent if db and db.intent else s.section or ""),
                                          query_tags=list(db.query_tags) if db and db.query_tags else ["desk"], overlay_text=s.text))
        return scenes

    def _pick_music(self, template: TemplateConfig, persona: PersonaConfig) -> str | None:
        music_dir = self.storage_dir / "music"
        if not music_dir.is_dir():
            return None
        tracks = sorted(p.name for p in music_dir.iterdir() if p.suffix.lower() in {".mp3", ".m4a", ".wav", ".aac"})
        if not tracks:
            return None
        cat = template.music_category or persona.default_music_category or ""
        pool = [t for t in tracks if cat and t.startswith(cat)] or tracks
        return random.choice(pool)

    def _record_usage(self, p: VideoProject, video: VideoJSON, r: Render) -> None:
        now = datetime.now(timezone.utc)
        for s in video.scenes:
            a = self.session.get(Asset, s.asset_id)
            if a is None:
                continue
            a.usage_count = (a.usage_count or 0) + 1
            a.last_used_at = now
            a.last_used_project_id = p.id
            self.session.add(AssetUsage(asset_id=a.id, project_id=p.id, render_id=r.id, used_at=now))


def available_templates() -> list[TemplateConfig]:
    return list_templates()
