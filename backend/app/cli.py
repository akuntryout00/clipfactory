"""ttcf — command line interface (PRD §46). Works without the API server."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings

app = typer.Typer(help="TikTok Content Factory CLI", no_args_is_help=True, add_completion=False)
assets_app = typer.Typer(help="Asset library commands", no_args_is_help=True)
projects_app = typer.Typer(help="Project commands", no_args_is_help=True)
app.add_typer(assets_app, name="assets")
app.add_typer(projects_app, name="projects")

# overridable in tests
SESSION_FACTORY: sessionmaker | None = None
SERVICE_KWARGS: dict = {}


def _factory() -> sessionmaker:
    global SESSION_FACTORY
    if SESSION_FACTORY is None:
        from app.db import get_sessionmaker, init_db

        init_db()
        get_settings().ensure_dirs()
        SESSION_FACTORY = get_sessionmaker()
    return SESSION_FACTORY


def _service(session, progress=None):
    from app.projects.service import ProjectService

    return ProjectService(session, progress=progress, **SERVICE_KWARGS)


def _progress(stage: str, msg: str) -> None:
    if msg:
        typer.echo(f"  {msg}")


def _print_plan(svc, project_id: str) -> None:
    p = svc.get_project(project_id)
    plan = svc.load_plan(project_id, p.plan_version)
    typer.echo(f"\nScene plan v{p.plan_version} — {len(plan.scenes)} scenes, {plan.total_duration:.2f}s, seed={plan.seed}")
    for s in plan.scenes:
        ov = f'  overlay="{s.text}"' if s.text else ""
        typer.echo(f"  SCENE {s.order} [{s.start:5.2f}-{s.end:5.2f}] {s.section or '':<12} {s.asset_id} ({s.asset_file} @ {s.asset_start:.2f}){ov}")


# ---------- top-level ----------

@app.command()
def generate(template: str = typer.Option(..., "--template", "-t", help="template id, e.g. story_v1"),
             topic: str = typer.Option(..., "--topic", help="video topic"),
             duration: Optional[float] = typer.Option(None, "--duration", "-d", help="target seconds (15-25)"),
             persona: Optional[str] = typer.Option(None, "--persona"),
             plan_only: bool = typer.Option(False, "--plan-only", help="stop after the Video JSON (no render)")):
    """Topic + template → TikTok-ready MP4 (full pipeline)."""
    with _factory()() as s:
        svc = _service(s, progress=_progress)
        typer.echo("Creating project...")
        p = svc.create_project(topic=topic, template_id=template, persona_id=persona, target_duration=duration)
        typer.echo(f"  {p.id}")
        try:
            script = svc.run_script(p.id)
            typer.echo(f"Script generated ({len(script.full_text.split())} words).")
            svc.run_voice(p.id)
            video = svc.run_plan(p.id)
            typer.echo(f"{len(video.scenes)} scenes generated.")
            typer.echo("Assets selected.")
            _print_plan(svc, p.id)
            if plan_only:
                typer.echo(f"\nPlan saved: {svc.project_dir(p.id) / f'plan_v{svc.get_project(p.id).plan_version}.json'}")
                return
            typer.echo("Rendering...")
            r = svc.run_render(p.id)
            typer.echo(f"\n✓ {svc.project_dir(p.id) / 'final.mp4'}")
            typer.echo(f"  render: {r.output_path}  qc: {'passed' if r.qc and r.qc.get('passed') else 'FAILED'}")
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"\n✗ FAILED: {exc}", err=True)
            raise typer.Exit(code=1)


@app.command()
def templates():
    """List available templates."""
    from app.config.loaders import list_templates

    for t in list_templates():
        typer.echo(f"{t.id:<22} {t.name:<18} {t.duration.min:.0f}-{t.duration.max:.0f}s  sections={[s.type for s in t.sections]}")


@app.command()
def batch(file: Path = typer.Argument(..., help="JSON list of {topic, template_id, target_duration?}"),
          continue_on_error: bool = typer.Option(True)):
    """Generate many videos (PRD §51 30-video validation). Writes a review template per project."""
    items = json.loads(Path(file).read_text())
    ok = fail = 0
    with _factory()() as s:
        svc = _service(s, progress=lambda st, m: None)
        for i, it in enumerate(items, 1):
            typer.echo(f"[{i}/{len(items)}] {it['template_id']}: {it['topic']}")
            try:
                p = svc.create_project(topic=it["topic"], template_id=it["template_id"], target_duration=it.get("target_duration"))
                svc.generate(p.id)
                review = svc.project_dir(p.id) / "review.json"
                review.write_text(json.dumps({"project_id": p.id, "topic": it["topic"], "template": it["template_id"],
                                              "script": None, "broll": None, "voice": None, "captions": None, "edit": None,
                                              "would_post": None, "manual_changes": 0, "notes": ""}, indent=2))
                typer.echo(f"   ✓ {svc.project_dir(p.id) / 'final.mp4'}")
                ok += 1
            except Exception as exc:  # noqa: BLE001
                fail += 1
                typer.echo(f"   ✗ {exc}")
                if not continue_on_error:
                    raise typer.Exit(code=1)
    typer.echo(f"done: {ok} ok, {fail} failed")


@app.command()
def doctor():
    """Check ffmpeg capabilities, providers and directories."""
    from app.renderer.ffmpeg import check_render_capabilities

    s = get_settings()
    typer.echo(f"llm_provider={s.llm_provider}  openai_key={'set' if s.openai_api_key else 'MISSING'}  model={s.openai_model}")
    typer.echo(f"voice_provider={s.voice_provider}  elevenlabs_key={'set' if s.elevenlabs_api_key else 'MISSING'}  voice_id={'set' if s.elevenlabs_voice_id else 'MISSING'}")
    typer.echo(f"assets_dir={s.assets_dir} exists={s.assets_dir.is_dir()}  storage_dir={s.storage_dir}")
    typer.echo(f"database_url={s.database_url}")
    missing = check_render_capabilities()
    typer.echo("render: " + ("OK" if not missing else "; ".join(missing)))


# ---------- assets ----------

@assets_app.command("import")
def assets_import(approve_unseeded: bool = typer.Option(False, help="approve new files that have no seed metadata")):
    """Scan the assets folder, extract ffprobe metadata and seed semantic metadata."""
    from app.assets.importer import import_assets

    assets_dir = Path(SERVICE_KWARGS.get("assets_dir") or get_settings().assets_dir)
    with _factory()() as s:
        rep = import_assets(s, assets_dir, approve_unseeded=approve_unseeded)
    typer.echo(f"import done: created={rep.created} updated={rep.updated} errors={len(rep.errors)}")
    for e in rep.errors:
        typer.echo(f"  ! {e}")


@assets_app.command("list")
def assets_list(approved_only: bool = typer.Option(False)):
    from sqlalchemy import select

    from app.models import Asset

    with _factory()() as s:
        q = select(Asset).order_by(Asset.id)
        if approved_only:
            q = q.where(Asset.approved.is_(True))
        for a in s.execute(q).scalars():
            typer.echo(f"{a.id:<10} {a.file:<34} {a.duration:5.1f}s {a.width}x{a.height} {a.shot or '-':<7} {a.action or '-':<18} "
                       f"q={a.quality_score:.2f} used={a.usage_count} {'✓' if a.approved else '✗'} tags={','.join(a.tags or [])}")


@assets_app.command("search")
def assets_search(query: list[str] = typer.Argument(..., help="tags, e.g. typing desk close"), limit: int = 10):
    from app.assets.selector import extract_query_tags, find_candidates

    with _factory()() as s:
        cands = find_candidates(s, extract_query_tags(query), limit=limit)
        typer.echo(f"{'asset':<10} {'score':>6} {'rel':>5} {'fresh':>5}  file")
        for c in cands:
            typer.echo(f"{c.asset.id:<10} {c.score:6.3f} {c.relevance:5.2f} {c.freshness:5.2f}  {c.asset.file}")


@assets_app.command("set")
def assets_set(asset_id: str, approved: Optional[bool] = None, quality: Optional[float] = None, mood: Optional[str] = None,
               location: Optional[str] = None, action: Optional[str] = None, shot: Optional[str] = None,
               tags: Optional[str] = typer.Option(None, help="comma separated")):
    """Edit semantic metadata of an asset."""
    from app.models import Asset

    with _factory()() as s:
        a = s.get(Asset, asset_id)
        if a is None:
            raise typer.BadParameter(f"unknown asset {asset_id}")
        for k, v in dict(approved=approved, quality_score=quality, mood=mood, location=location, action=action, shot=shot).items():
            if v is not None:
                setattr(a, k, v)
        if tags is not None:
            a.tags = [t.strip() for t in tags.split(",") if t.strip()]
        s.commit()
        typer.echo(f"updated {a.id}")


# ---------- projects ----------

@projects_app.command("create")
def projects_create(template: str = typer.Option(..., "--template", "-t"), topic: str = typer.Option(..., "--topic"),
                    duration: Optional[float] = typer.Option(None, "--duration", "-d")):
    with _factory()() as s:
        p = _service(s).create_project(topic=topic, template_id=template, target_duration=duration)
        typer.echo(p.id)


@projects_app.command("list")
def projects_list(limit: int = 30):
    with _factory()() as s:
        for p in _service(s).list_projects(limit):
            typer.echo(f"{p.id:<17} {p.status:<18} {p.template_id:<20} s{p.script_version}/v{p.voice_version}/p{p.plan_version}/r{p.render_version}  {p.topic[:50]}")


@projects_app.command("show")
def projects_show(project_id: str):
    with _factory()() as s:
        svc = _service(s)
        p = svc.get_project(project_id)
        typer.echo(f"{p.id}  status={p.status}  template={p.template_id}  persona={p.persona_id}")
        typer.echo(f"topic: {p.topic}")
        typer.echo(f"target={p.target_duration}s actual={p.actual_duration}s versions: script={p.script_version} voice={p.voice_version} plan={p.plan_version} render={p.render_version}")
        if p.error:
            typer.echo(f"error: {p.error}")
        if p.script:
            typer.echo(f"script:\n  {p.script}")
        if p.plan_version:
            _print_plan(svc, p.id)
        if p.current_render_id:
            typer.echo(f"video: {svc.project_dir(p.id) / 'final.mp4'}")


def _control(project_id: str, action: str):
    with _factory()() as s:
        svc = _service(s, progress=_progress)
        try:
            getattr(svc, action)(project_id)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"✗ {exc}", err=True)
            raise typer.Exit(code=1)
        p = svc.get_project(project_id)
        if p.plan_version:
            _print_plan(svc, p.id)
        typer.echo(f"status={p.status}")
        if p.current_render_id:
            typer.echo(f"✓ {svc.project_dir(p.id) / 'final.mp4'}")


@projects_app.command("generate")
def projects_generate(project_id: str):
    """Run the full pipeline for an existing project."""
    _control(project_id, "generate")


@projects_app.command("regenerate-script")
def projects_regenerate_script(project_id: str):
    _control(project_id, "regenerate_script")


@projects_app.command("change-assets")
def projects_change_assets(project_id: str):
    _control(project_id, "change_assets")


@projects_app.command("render")
def projects_render(project_id: str):
    """Render again with new visual variation (same script/voice/assets)."""
    _control(project_id, "render_again")


@projects_app.command("retry")
def projects_retry(project_id: str):
    _control(project_id, "retry")


@projects_app.command("approve")
def projects_approve(project_id: str):
    _control(project_id, "approve")


@projects_app.command("suggest")
def projects_suggest(project_id: str, scene: int):
    with _factory()() as s:
        for c in _service(s).suggest_assets(project_id, scene):
            typer.echo(f"{c['asset_id']:<10} score={c['score']:.3f} {c.get('action')}/{c.get('location')}/{c.get('shot')}  {c.get('description')}")


@projects_app.command("set-asset")
def projects_set_asset(project_id: str, scene: int, asset_id: str):
    """Manually override the B-roll of one scene and re-render."""
    with _factory()() as s:
        svc = _service(s, progress=_progress)
        svc.override_scene_asset(project_id, scene, asset_id)
        _print_plan(svc, project_id)
        typer.echo(f"✓ {svc.project_dir(project_id) / 'final.mp4'}")


if __name__ == "__main__":
    app()
