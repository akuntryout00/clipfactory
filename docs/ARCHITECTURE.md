# Architecture

ClipFactory has two independent subsystems that share only infrastructure (FastAPI app, SQLAlchemy/Postgres, storage dir, job runner class, ffmpeg helpers):

1. **Content factory** — turns *topic + template* into a vertical video from **your own B-roll**.
2. **AI Lab** — turns a *prompt* into a **fully AI-generated** vertical video (own tables `lab_*`, own storage `storage/lab/`, own routes `/lab/*`, own UI section).

```
┌──────────────────────── backend (FastAPI, Python 3.12) ────────────────────────┐
│ api/            routers: meta/system, assets, projects      lab/api.py: /lab/*   │
│ projects/service.py content-factory pipeline + controls      lab/service.py     │
│ projects/jobs.py    thread-pool job runner (1 job per id)    lab/providers.py   │
│ llm/ voice/ content/ captions/ renderer/ assets/             lab/pricing.py     │
│ db.py models/ schemas/ config/                               lab/models.py      │
└──────────────────────────────────────────────────────────────────────────────────┘
┌──── frontend (React 19 + Vite + Tailwind + shadcn) ────┐   ┌── infra (compose) ──┐
│ /projects /generate /projects/:id /assets /templates     │   │ db: postgres:16      │
│ /system /lab /lab/:id   — talks to /api → nginx → api    │   │ api: python+ffmpeg   │
└──────────────────────────────────────────────────────────┘   │ web: nginx (static)  │
                                                               └──────────────────────┘
```

## Content factory pipeline

Principle: **the LLM never produces video — it produces a validated `Video JSON`; FFmpeg renders it deterministically.** The real voice duration is the master clock.

```
create project (topic, template, persona)
 → run_script     LLM → ScriptOutput (sections in template order, word budget from persona speech rate)
 → run_voice      TTS (ElevenLabs convert_with_timestamps) → mp3 + word timings; if longer than max → shorten_script ≤2× and re-voice
 → run_plan       LLM plans scenes as word-index ranges (library-aware prompt) → normalize_plan snaps to word times,
                  merges <min shots / splits >max shots, caps overlays → assign_assets: candidates (relevance×quality×freshness)
                  → LLM ranks → unique clip per scene → random usable-range offset (seeded) → caption chunks → Video JSON (validated)
 → run_render     2-stage ffmpeg: per-scene clip (trim, cover-scale, jitter crop, subtle zoom, 30 fps) → concat + ASS captions/overlays
                  + loudnorm (+ music ducking) → H.264/AAC 1080×1920 → QC (resolution, fps, codecs, duration, size)
```

Every stage persists a versioned artifact under `storage/projects/<id>/` (`script_vN.json`, `voice_vN.mp3` + `.words.json`, `plan_vN.json`, `final.mp4`) and rows in `video_projects / video_scenes / voice_generations / renders / project_events`. Controls only re-run downstream stages:

| control | script | voice | plan | render |
|---|---|---|---|---|
| regenerate-script | new | new | new | new |
| change-assets | keep | keep | new (same cut, previous clips excluded) | new |
| render-again | keep | keep | new seed (same clips) | new |
| scene override | keep | keep | new (one clip pinned) | new |
| retry | resumes from the failed stage | | | |

Statuses: `DRAFT → GENERATING_SCRIPT → GENERATING_VOICE → PLANNING → SELECTING_ASSETS → GENERATING_CAPTIONS → RENDERING → READY → APPROVED | FAILED`.

Key modules: `content/script_generator.py` (word budget, shorten loop), `voice/alignment.py` (chars → words), `voice/normalize.py` (what TTS should say, e.g. no "POV:"), `content/scene_planner.py` (`heuristic_plan`, `normalize_plan`), `assets/selector.py` (scoring), `assets/catalog.py` (library summary for the planner), `content/asset_assignment.py`, `captions/generator.py` (chunking + ASS), `renderer/*` (ffmpeg graph, audio, QC).

## Asset library

`assets/importer.py` scans `assets/<persona>/<category>/**` (skipping `_originals`, `_rejected`; a first path segment that is not a persona id is treated as a legacy category and assigned to `DEFAULT_PERSONA`), probes with ffprobe, seeds semantic metadata from `assets/broll_database.json` and heuristics; `assets/enrich.py` asks the LLM for richer tags; `assets/frames.py` samples frames for **AI autocomplete** on single-file upload (`POST /assets/analyze`, vision). Assets carry `usable_start/usable_end`, `quality_score`, `usage_count`, `last_used_at`, `approved`.

## AI Lab

```
create (instant) → job: plan (LLM storyboard: style guide + N keyframes + motion per segment)
                       → keyframe images (OpenAI; each frame uses the previous one as reference via images.edit)
user reviews keyframes (edit & redo any) → animate: for each consecutive pair → video provider → normalise → concat → final.mp4
```
- `lab/planning.py`: `segment_plan(target, max_seg, min_seg)` → clips ≤10 s (storyboard granularity) and ≥ the model's minimum; 3 s videos are one clip.
- `lab/providers.py`: `Planner`, `ImageGen`, `VideoGen` protocols; `OmniVideoGen` (Gemini Interactions API, FIRST_FRAME + IMAGE_REF tags, conversational edit), `GoogleVideoGen` (Veo, true first/last frame), `FalVideoGen` (registry `FAL_MODELS`), fakes for tests. The provider is **per video** (`lab_videos.video_provider`).
- `lab/service.py`: events log (`lab_events`), retry from the failed step, per-segment redo/edit, length change, clone (for A/B), `lab/pricing.py` estimate.
- Statuses: `PLANNING → PLANNED → GENERATING_IMAGES → IMAGES_READY → ANIMATING → DONE | FAILED`.

## Jobs & concurrency
`projects/jobs.py` — a small thread pool; at most one running job per project/video id (409 otherwise). Long work never blocks requests; the UI polls. Provider calls are synchronous inside the job.

## Configuration
Provider keys/models can be set in the UI: `config/store.py` keeps them in `app_settings` (key `providers`), exports them to the process environment and clears the cached `Settings` (UI > env > .env > defaults); applied at API startup and by the CLI. All behaviour that should change without code lives in `configs/` (templates, caption styles, persona seeds) and `.env` (providers/models/keys). Templates are editable from the UI and validated by `schemas/configs.py`. **Personas** are rows in the `personas` table (`app/personas/repo.py`: get/list/upsert/delete, `seed_personas_from_configs`, `persona_or_config` = DB first then JSON); `Asset.persona_id` and `Project.persona_id` scope the B-roll library, selection (`find_candidates(..., persona_id)`), library summary and project listing to one persona. API: `/personas` CRUD, `?persona=` filters on `/assets`, `/assets/search`, `/projects`, `persona_id` form field on upload.

## Database
SQLAlchemy 2.0, Postgres in compose, SQLite in tests. `db.init_db()` creates tables and applies a tiny forward-only column migration (`_ensure_columns`) for fields added after first release. (Alembic is a planned improvement.)

## Testing
`backend/tests` — unit tests with fake providers + ffmpeg-generated synthetic clips; renderer/QC and end-to-end tests need ffmpeg with **libass** (run `make test` in Docker if your local ffmpeg lacks it). Frontend is type-checked (`tsc -b`) and built.

## Caption settings

`captions/settings.py`: `CaptionOverrides` (font, size, bold, vertical anchor for captions and overlays) stored globally in the `app_settings` table (key `captions`, API `GET/PUT /settings/captions`) and per project in `video_projects.caption_overrides` (`PUT /projects/{id}/captions`). `ProjectService.caption_style_for()` resolves template caption style → global → project before caption generation and rendering; `render_video(..., fonts_dir=)` passes `fonts/` to libass as `fontsdir`. `GET /fonts` lists `fonts/*.ttf|otf` (family read with `fc-scan`) plus fontconfig system families; `POST /fonts/upload` adds a file.

## Shot list & batches

`assets/shotlist.py`: `Shotlist`/`ShotlistItem` per persona (AI `generate_shotlist`, counts scaled to the target), `coverage()` (filled = min(approved assigned clips, count) per item), `match_assets()` (LLM `match_shotlist` in chunks of 40 with an action/category/tag heuristic fallback) — used on upload, on demand and after regeneration. `projects/batch.py`: `Batch` + `VideoProject.batch_id`; topics from `LLM.generate_topics` (PRD §51 template mix via `split_counts`) or user list; projects created up-front, generated sequentially in one JobRunner job; cancel flag checked between items; resume re-runs DRAFT/FAILED.

## AI B-roll

`aibroll/service.py`: `AiBrollJob` → keyframe via `OpenAIImageGen.generate(identity=True, quality='high')` when a persona/clip photo is given (prompt asks for high-fidelity identity), else a plain keyframe → `VideoGen.animate(first, last=None, …)` (providers accept a single start frame; fal args drop `end_image_url`) → `_normalize_segment` → copied to `assets/<persona>/<category>/ai_<id>.mp4` and registered approved with the shot's metadata (`Asset.shotlist_item_id`). Persona reference photo: `storage/personas/<id>/reference.png` (`PUT/GET/DELETE /ai-broll/personas/{id}/image`). Jobs run on the Lab job runner.
