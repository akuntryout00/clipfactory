# ClipFactory

> Give it a **topic** and a **template**; get a short-form vertical video (9:16, 1080×1920 — TikTok / Reels / Shorts) made from **your own B-roll**, an **AI script**, an **AI voice** and synced captions. Plus an isolated **AI Lab** that turns a sentence into a fully AI-generated vertical video.

ClipFactory is a self-hosted content pipeline you run on your own machine (Docker). It **does not post anything anywhere** — you review every video and publish it yourself. It is **not affiliated with TikTok, Meta or Google.**

- License: **Elastic License 2.0** — free to use and modify for yourself or your company; **not** to be offered to others as a hosted/managed service. Videos you generate are yours, no restrictions. See [LICENSE](LICENSE).
- Docs: [Architecture](docs/ARCHITECTURE.md) · [Providers & models](docs/PROVIDERS.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md)

## What it does

**Content factory** (PRD-driven core): `Topic + Template → Script (LLM) → Voice (ElevenLabs, real duration = master clock) → Scene plan → B-roll selection from your library → Video JSON (validated) → Captions → FFmpeg render → QC`. Every artifact is versioned; you can regenerate the script, swap B-roll, re-render with new visual variation, override a single scene, and approve.

**AI Lab** (separate module, own tables/storage/routes): `Prompt → storyboard (LLM) → keyframe images (OpenAI, each chained to the previous frame) → per-segment animation by the video model you choose (Gemini Omni, Veo 3.1, or via fal.ai: Seedance 2.0/2.5, MiniMax H3, Kling 3.0) → concatenated 9:16 MP4`, with per-segment redo/edit, length change, clones for A/B comparison and a price estimate before you start.

## Requirements

- Docker Desktop (or Docker Engine + Compose v2)
- **Your own B-roll clips** (vertical, any codec ffmpeg reads) placed under `assets/<persona>/<category>/…` — ClipFactory ships no footage; the content factory needs at least a handful of approved clips to select from (see “B-roll library” below).
- API keys for the providers you want to use (see table). Nothing works without an LLM key + a voice key for the content factory; the AI Lab additionally needs an image provider and a video provider.

| Feature | Provider | Env var(s) |
|---|---|---|
| Script / scene planning / B-roll ranking / asset enrichment | OpenAI (structured outputs) | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| Voice-over + word timestamps | ElevenLabs | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` |
| AI Lab keyframe images | OpenAI Images (`gpt-image-2`) | `OPENAI_API_KEY`, `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_QUALITY` |
| AI Lab video (Gemini Omni / Veo) | Google Gemini API | `GOOGLE_API_KEY`, `GOOGLE_VIDEO_MODEL`, `GOOGLE_VEO_MODEL` |
| AI Lab video (Seedance, MiniMax H3, Kling, …) | fal.ai | `FAL_KEY`, `LAB_FAL_MODEL` |
| Offline dry run (tests/demo without any key) | built-in fakes | `LLM_PROVIDER=fake`, `VOICE_PROVIDER=fake`, `LAB_*_PROVIDER=fake` |

## Quick start

```bash
cp .env.example .env           # fill the keys you have
mkdir -p assets/desk assets/phone   # drop your vertical B-roll here (any categories you like)
make build && make up          # db + api + web → UI http://localhost:3000 · API docs http://localhost:8000/docs
make import                    # scan ./assets → ffprobe metadata (+ optional assets/broll_database.json seed)
make doctor                    # keys / ffmpeg / dirs check
make generate TEMPLATE=story_v1 TOPIC="Why I stopped answering Slack in the morning"
# ✓ storage/projects/proj_xxx/final.mp4
```

The web UI at **http://localhost:3000** covers everything: Projects, Generate, per-project timeline with scene-level controls, B-roll library (upload with AI autocomplete, usable-range trimmer, enrich), Templates editor, System status, and the AI Lab.

## B-roll library

- Put clips in `assets/<persona>/<category>/name.mp4` — every clip belongs to one persona, and only that persona's projects can use it (or upload them one by one in the UI with **Add video**, choosing the persona — AI autocomplete fills description/tags/action/location/shot/mood from sampled frames).
- `make import` reads technical metadata with ffprobe; semantic metadata comes from `assets/broll_database.json` if present (id/file/description/tags/shot), otherwise heuristics + **Enrich with AI**.
- Clips must be **approved** to be selectable (seeded clips are approved; uploaded clips default to whatever you choose).
- The scene planner is library-aware: it only plans visuals your footage can cover; the ranker receives the whole catalog when it is small (≤60 clips).
- Selection score = relevance × quality × freshness (recently used clips are de-prioritised); the start offset is random inside each clip’s usable range so repeats don’t look identical.

## CLI (`docker compose run --rm api clipfactory …`, alias `ttcf`)

| command | what |
|---|---|
| `generate --template story_v1 --topic "…" [--duration 18] [--plan-only]` | full pipeline |
| `templates` · `doctor` | list templates · environment check |
| `assets import [--approve-unseeded]` · `assets enrich [--overwrite]` · `assets list` · `assets search typing desk close` · `assets set asset_001 --quality 0.9 --tags a,b` | asset library |
| `projects create/list/show/generate` · `projects regenerate-script|change-assets|render|approve|retry ID` · `projects suggest ID SCENE` · `projects set-asset ID SCENE ASSET_ID` | project controls |
| `batch configs/batch_30.json` | batch generation with a review template per video |

## Configuration (no code changes needed)

- **Personas live in the database** and are created with a short wizard (name → place & age → free-text description → AI drafts the rest → you review) and edited in the UI (**Personas** page: identity name/age/location/background, audience, content pillars, tone, things to avoid, tools, product-mention policy, closing style, voice settings, measured speech rate). `configs/personas/*.json` are only seeds — they are inserted on first start if the table is empty, and the shipped ones are examples. Projects and B-roll are scoped per persona: the sidebar switcher selects the active persona; Generate lets you pick one per video. `DEFAULT_PERSONA` is the fallback for the CLI and legacy imports. `clipfactory assets migrate-personas --to <id>` moves a pre-persona `assets/<category>/` library under `assets/<id>/`.
- **Caption font & position** — System → *Captions* sets the font (any `.ttf`/`.otf` in `fonts/`, uploadable from the UI, plus system fonts), size, weight and vertical position of captions and of the big text overlays for every render; a project's **Captions** button overrides them for that project only (applied on the next render). Five OFL fonts are bundled in `fonts/` (Anton, Bebas Neue, Montserrat, Oswald, Poppins).
- `configs/templates/*.json` — video structures (sections + weights, duration, shot length, overlays, closing rule, caption style, music category). Editable in the UI (Templates).
- `configs/captions/*.json` — caption style (font, size, colours, safe zones, chunking, animation).
- `storage/music/<category>_NN.mp3` — optional royalty-free music; mixed at −20 dB with ducking under the voice.

## Privacy, costs and content

- **Your data**: everything runs locally. The only outbound traffic is to the AI providers you configure (prompts, scripts, clip descriptions, sampled frames of uploaded B-roll for AI autocomplete, keyframe images for video generation). Nothing is sent to the ClipFactory authors; there is no telemetry.
- **Costs**: every generation calls paid APIs. Rough per-video costs: content factory ≈ $0.05–0.20 (LLM + voice); AI Lab ≈ $1–15 depending on the video model and length — the New-video dialog shows an estimate (list prices; retries/re-dos are extra). Watch your provider dashboards.
- **Generated content**: the license puts no restrictions on your output, but provider terms do (OpenAI, Google, ElevenLabs, fal.ai, ByteDance/MiniMax/Kuaishou via fal). Some models watermark output (e.g. Google SynthID). You are responsible for what you publish — ClipFactory never posts automatically and has no TikTok/Instagram/YouTube integration.

## Development

```bash
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest   # renderer tests need ffmpeg with libass → `make test` runs them in Docker
cd frontend && npm install && npm run dev    # Vite on :3000 proxying /api → http://localhost:8000
```
Tests use fake providers and synthetic clips (no keys). See [CONTRIBUTING.md](CONTRIBUTING.md).

## Layout

```
backend/app/   api/ (FastAPI routers) · assets/ (import, selector, catalog, enrich, frames) · content/ (script, planner, assignment)
               captions/ · renderer/ (ffmpeg, filters, audio, qc) · voice/ (elevenlabs, alignment, normalize) · llm/ (providers, prompts)
               projects/ (service, jobs) · lab/ (AI Lab: models, providers, service, pricing, api) · config/ · schemas/ · models/
frontend/src/  pages/ (Projects, Generate, Project, Assets, Templates, System, Lab, LabVideo) · components/ · lib/
configs/       personas · templates · captions · batch_30.json
storage/       voices · renders · projects/<id>/ · lab/<id>/ · temp · thumbs · music   (gitignored)
assets/        your B-roll (+ optional broll_database.json)                           (gitignored)
```
