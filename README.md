# TikTok Content Factory — MVP

> Give it a **topic** and a **template**; get a TikTok-ready 1080×1920 video made from **your own B-roll**, an **AI script**, **ElevenLabs voice** and **dynamic captions**.

Principle (PRD §3): **the LLM never produces video — it produces a validated `Video JSON` plan; FFmpeg renders it deterministically.**
The real ElevenLabs audio duration is the master clock for every scene.

```
Topic + Template → Script → ElevenLabs voice (+alignment) → Scene plan → B-roll selection → Video JSON → Captions → FFmpeg → MP4
```

## Stack
Backend: Python 3.12 · FastAPI · SQLAlchemy/PostgreSQL · FFmpeg (libass captions) · OpenAI (structured outputs) · ElevenLabs (timestamps).
Frontend: React 19 + TypeScript (Vite) · Tailwind v4 · shadcn/ui · TanStack Query — separate `frontend/` app served by nginx, proxying `/api` → backend.
Docker Compose runs `db` + `api` (:8000) + `web` (:3000). CLI `ttcf` works without the UI.

## Quick start
```bash
cp .env.example .env           # fill OPENAI_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
make build && make up          # db + api + web → UI http://localhost:3000 · API docs http://localhost:8000/docs
make import                    # scan ./assets → metadata (ffprobe + assets/broll_database.json)
make doctor                    # keys / ffmpeg / dirs check
make generate TEMPLATE=list_v1 TOPIC="3 productivity habits that waste your time"
# ✓ /app/storage/projects/proj_xxx/final.mp4   (→ ./storage/projects/proj_xxx/final.mp4 on the host)
```
Dry run without any API keys: set `LLM_PROVIDER=fake` and `VOICE_PROVIDER=fake` in `.env` (deterministic offline providers, beep voice).

## CLI (`docker compose run --rm api ttcf ...`)
| command | what |
|---|---|
| `generate --template story_v1 --topic "..." [--duration 18] [--plan-only]` | full pipeline (PRD §46) |
| `templates` · `doctor` | list templates · environment check |
| `assets import [--approve-unseeded]` · `assets enrich [--overwrite]` · `assets list` · `assets search typing desk close` · `assets set asset_001 --quality 0.9 --tags a,b` | asset library (`enrich` = LLM-assisted tags/action/location/mood from descriptions) |
| `projects create/list/show/generate` | project CRUD |
| `projects regenerate-script ID` · `projects change-assets ID` · `projects render ID` · `projects approve ID` · `projects retry ID` | regeneration controls (PRD §24) |
| `projects suggest ID SCENE` · `projects set-asset ID SCENE ASSET_ID` | manual B-roll override (PRD §49) |
| `batch /app/configs/batch_30.json` | 30-video validation batch (PRD §51); writes `review.json` per project |

## Web UI (http://localhost:3000)
| screen | what you can do |
|---|---|
| **Projects** | every project with status, template, length, version counters (script/voice/plan/render), filters, delete |
| **Generate** | pick template (structure + closing shown), topic, 15–25 s target → starts the background job and opens the project |
| **Project** | 9:16 player + download, voice player, stage progress (live), **timeline** drawn from the Video JSON (scene widths = durations, overlay markers, caption chunks, playhead synced with the player), scenes list with per-scene **Change** (suggested clips with thumbnails → re-render), script versions, renders + QC, event log, raw Video JSON; buttons Regenerate script / Change assets / Render again / Retry / Approve |
| **B-roll** | grid with thumbnails, usage counts, category filter, search; **Add video** (upload one clip into a category with description/tags/approval and a **usable-range trimmer**: drag start/end handles on the preview, “Set start/end here”, “Preview range”; the new clip is **auto-enriched with AI** right after upload); click a clip → same trimmer + edit tags/action/location/shot/mood/quality/approved, or delete it; Import folder, Enrich with AI |
| **Templates** | **create / edit / delete templates** in a form editor (id, name, description, ordered sections with weights that must sum to 100 %, duration min/target/max, shot length, overlays, closing rule, caption style, music, voice-over) — saved to `configs/templates/*.json`; personas shown read-only (identity, pillars, tone, tools, products policy, voice) |
| **System** | providers/keys, ffmpeg + libass, library counts, music tracks, paths |

Dev: `make web-dev` (Vite on :3000 proxying to the api container on :8000).

## AI Lab (separate module, http://localhost:3000/lab)
Fully AI-generated vertical videos, isolated from the content factory (own tables `lab_*`, own storage `storage/lab/`, own routes `/lab/*`, own UI section).
1. **Describe** the video + length (15–25 s) + optional style → an LLM writes a storyboard: a *style guide* for character/wardrobe/palette consistency and N keyframes (N = segments + 1; segments are 4–8 s each).
2. **Keyframes (OpenAI `gpt-image-2`)** — each keyframe is generated as a portrait image and cropped/scaled to exactly 1080×1920. Review; edit any prompt and regenerate a single frame (segments touching it are reset).
3. **Animate (Google Veo via google-genai, default `veo-3.1-fast-generate-preview`; `gemini-omni-*` models only support generateContent, not video)** — every consecutive frame pair (first → last frame) becomes one 9:16 clip of `segment_seconds`; clips are normalised (1080×1920/30fps/h264) and concatenated into `final.mp4`.
Env: `GOOGLE_API_KEY`, `GOOGLE_VIDEO_MODEL`, `OPENAI_IMAGE_MODEL` (+ `LAB_*_PROVIDER=fake` for offline runs). API: `POST/GET /lab/videos`, `GET/DELETE /lab/videos/{id}`, `POST …/generate-images | keyframes/{i}/regenerate | animate`, `GET …/keyframes/{i}/image | segments/{i}/video | video`.

## REST API (PRD §47)
`POST /projects` · `GET /projects[/{id}]` · `DELETE /projects/{id}` · `GET /projects/{id}/artifacts | voice | renders/{v}/video` · `POST /assets/upload` (multipart) · `DELETE /assets/{id}` · `GET /assets/{id}/file | thumbnail` · `POST /assets/enrich` · `GET /system` · · `POST /projects/{id}/generate | regenerate-script | change-assets | render | retry` (202, background job) · `POST /projects/{id}/approve` · `GET /projects/{id}/video | plan` · `GET /projects/{id}/scenes/{n}/suggestions` · `POST /projects/{id}/scenes/{n}/asset` · `GET/PATCH /assets[/{id}]` · `GET /assets/search?q=` · `POST /assets/import` · `GET/POST /templates` · `PUT/DELETE /templates/{id}` · `GET /caption-styles` · `POST /assets/analyze` (AI autocomplete) · `GET /personas` · `GET /health`

Statuses: `DRAFT → GENERATING_SCRIPT → GENERATING_VOICE → PLANNING → SELECTING_ASSETS → GENERATING_CAPTIONS → RENDERING → READY → APPROVED` (or `FAILED`, with `error` = `stage: reason`; `retry` resumes from that stage).

## Layout
```
backend/app/
  config/      settings (.env) + JSON config loaders        configs/
  schemas/     pydantic: configs, script, VideoJSON…          personas/young_professional.json
  assets/      ffprobe metadata, importer, selector (scoring)  templates/{story,list,pov,problem_solution}_v1.json
  llm/         base | openai_provider | fake | prompts         captions/dynamic_center.json
  voice/       base | elevenlabs | fake | alignment            batch_30.json
  content/     script_generator, scene_planner, asset_assignment
  captions/    chunking + ASS writer (safe zones)            storage/   voices/ renders/ projects/<id>/ temp/ music/
  renderer/    ffmpeg (2-stage), filters, audio, subtitles, qc   assets/    your B-roll (+ broll_database.json seed)
  projects/    service (pipeline, versioned artifacts, controls), jobs
  api/         FastAPI app      cli.py  (typer)
```

Per project `storage/projects/<id>/` keeps every artifact version: `script_vN.json`, `voice_vN.mp3` + `.words.json`, `plan_vN.json` (Video JSON), `final.mp4` (latest good render); renders live in `storage/renders/<id>/render_vN.mp4`.

## How selection & rendering work
* **Assets**: `assets import` reads technical metadata with ffprobe and semantic metadata from `assets/broll_database.json` (description/tags/shot) + cheap inference (action from filename, location/mood from text). Seeded clips are `approved=true`; new unseeded files are unapproved until you `assets set ... --approved true`.
* **Selection** (PRD §9/§31/§32): scene → query tags (+synonyms) → candidates from DB with `relevance × quality × freshness` (freshness 1.0 / 0.9 / 0.7 / 0.45 / 0.2 by last use) → for libraries ≤60 clips the **whole catalog** goes to the LLM ranker (top-15 otherwise) → validated unique pick → random segment inside `usable_start..usable_end` (seeded; *Render Again* changes the seed). The scene planner also receives a **library summary** so it only plans visuals the footage can cover.
* **Scene planning** (PRD §17/§30): the LLM returns word-index ranges + visual intent + tags + optional overlay; the backend snaps them to the **real word timestamps**, merges <1.5 s shots, splits >4 s shots, caps overlays to 1–3 and makes scenes contiguous up to voice end + 0.35 s. Heuristic planner is the fallback.
* **Render** (PRD §18/§19): stage 1 per scene — trim, cover-scale, jittered crop, subtle 2.5–5 % zoom in/out, 30 fps; stage 2 — concat, burn ASS captions (2–5 word chunks, emphasised word, pop animation, TikTok safe zones) + overlays, voice `loudnorm`, optional music at −20 dB with sidechain ducking, H.264/AAC, `+faststart`. Then QC (PRD §41): 1080×1920, 30 fps, h264/aac, 10–30 s, size.
* **Duration control** (PRD §39): word budget ≈ 2.5 words/s; if the synthesized voice exceeds the template/persona max, the script is shortened and re-voiced (max 2 rewrites).

## Growing the B-roll library
The planner can only show what you filmed. Current coverage: desk, phone, walking, reaction, product. Scenes that come up often in this persona's scripts and have **no footage yet**: laptop video call / meeting, notebook + handwriting, scrolling a long document on the laptop, recording a voice memo, calendar/to-do app on phone, AI app on laptop, walking into an office, coworker conversation. Drop new clips in a category folder, run `assets import` (+ `assets enrich`), then `assets set <id> --approved true`.

## Music
Drop royalty-free `<category>_NN.mp3` files into `storage/music/` (`upbeat_01.mp3`, `productivity_soft_01.mp3`, `minimal_01.mp3`…). Templates choose a category; empty folder = voice-only.

## Tests
`make test` runs the whole suite in the container (ffmpeg with libass). Locally `backend/.venv/bin/pytest` runs everything except libass-dependent renders.
