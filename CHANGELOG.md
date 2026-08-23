# Changelog

All notable changes are documented here. Format: Keep a Changelog · SemVer.

## [Unreleased]
### Added
- **Delivery to the phones**: per-persona **Inbox** link + QR (Personas → Inbox; token-protected, phone-friendly page listing approved videos/slideshows with save links, zip and post caption; LAN IP or Tailscale address set once in Settings) and a **Telegram bot per persona** (bot token + chat id in the persona's Delivery section, with a test button; Settings can hold an optional fallback bot) that sends the video — or the slides + zip — automatically on Approve, plus a *Telegram* button on the project page. API `/personas/{id}/inbox-link[/rotate]`, `/personas/{id}/inbox-qr.png`, `/inbox/{persona}/…?key=`, `POST /projects/{id}/send-telegram`.
- **Slideshow** template (TikTok photo mode — a photo carousel, not a video): the LLM writes 5-10 slides (hook → one idea per slide → twist) plus a post caption, photos are picked automatically from the persona's new **Photos** library (B-roll → Photos; JPG/PNG/WebP import & upload with AI autocomplete), and each slide is rendered as a 1080×1920 JPG with the text burned in (+ zip). The project page shows the slide gallery with downloads; *Change assets* swaps photos, *Render again* re-renders the images. Assets now have `kind` (video | image); photos never enter B-roll selection.
### Changed
- AI Lab storyboard is **content-driven**: the planner decides the shots from the idea (how many, each shot's length within the model's clip range, hard cut vs continuous camera), then start/end keyframes per shot, then animation per shot with its own length — instead of a fixed grid of equal segments. Continuous shots reuse the previous end frame; cuts get a fresh start frame. Change length re-plans the storyboard; clones copy the storyboard when the clip lengths fit the new model.
### Added
- **Trends** tab: paste a TikTok / Reels / Shorts URL → the video is fetched (yt-dlp), transcribed (OpenAI), sampled and reverse-engineered by the LLM for the active persona — hook, structure timeline, pacing, visuals, captions, audio, why it works, persona-specific tips, remix hooks, **Generate a video from this** (one-off project that uses the trend's structure inline — no template saved) and a **template proposal** that opens in the template editor for review and creation. API `/trends/*`; `VideoProject.template_override` (inline TemplateConfig) + `template_override` on `POST /projects`.
### Fixed
- AI B-roll with a persona photo: OpenAI's safety system refused the previous identity prompt for real photos; the start frame now asks to *place the person from the reference image into the described scene* (face/hair kept, photo background not reused), retries with a plainer prompt, and falls back to fal.ai nano-banana image editing when a FAL key is set.

## [0.2.0] — 2026-08-22
### Added
- **AI B-roll** module: describe a shot (or open it from the shot list with *Create with AI* — everything prefilled), pick a video model (fal.ai Seedance/MiniMax/Kling, Omni, Veo) and length, optionally keep the persona's real face (identity-preserving high-quality start frame + face-lock motion prompt), generate → the clip is normalized to 1080×1920 and added to the persona's library as an approved, tagged asset assigned to that shot. Persona photo upload/replace/remove; cost estimate; job list with retry/delete. API `/ai-broll/*`.
- Plug-and-play first run: `docker compose up` works without `.env`; a **Setup** page asks for the provider keys (OpenAI, ElevenLabs with voice picker, optional Google / fal.ai), tests the connections and stores them in the database (overriding `.env`); the app redirects to Setup until the required providers are configured; Settings page to change them later; offline dry-run mode with fake providers. API `GET/PUT /settings/providers`, `POST /settings/providers/test`; `/system` reports `setup_required`.
### Changed
- Open-source hygiene: example persona seed `indie_maker` (anonymized) replaces the author's personal persona in the repo; personal library files (`assets/broll_database.json`, `rename_map.csv`, `_rejected/`) are no longer tracked; complete `.env.example`; README first-run walkthrough; license/maintainer/security contact.
### Added
- Per-persona **B-roll shot list**: AI plans what to film (shots grouped by folder with counts summing to a target, default 100), the B-roll page shows coverage % from the uploaded library, the list with done/missing shots, clip ↔ shot matching (AI on upload / on demand, manual in the clip editor), regenerate with a new target or guidance; personas created by the wizard get their list automatically. API `GET/POST /personas/{id}/shotlist[/generate|/match]`, `Asset.shotlist_item_id`.
- Batch generation from the web UI (PRD §51): choose how many videos, templates (PRD mix), length, AI-picked topics (persona pillars, excluding used topics) or your own list; runs in the background, Projects page shows batch progress, stop/resume, and filters projects by batch. API `POST/GET /batches`, `/batches/{id}`, `/cancel`, `/resume`.
### Fixed
- Caption size consistency: wrapping and the shrink safety net now measure real glyph widths with the selected font (Pillow/FreeType) instead of character counts, so narrow fonts are no longer shrunk and chunks keep one size; the UI preview converts ASS line-height sizes to em (OS/2 win metrics, like libass) so it matches the render.
### Added
- Caption font & position settings: global (System → Captions) and per project (Captions button), live 9:16 preview with safe zones, font list from `fonts/` + system fonts, font upload; bundled OFL fonts (Anton, Bebas Neue, Montserrat, Oswald, Poppins).
- Persona wizard: New persona = name → country/city/age (language auto from country) → free-text description → AI drafts the full profile (`POST /personas/draft`) → review & create; id and list name are system-generated.
- Multi-persona: personas stored in the database with a UI editor (Personas page), per-persona projects and B-roll (`assets/<persona>/<category>/`), persona switcher in the sidebar, persona choice on Generate and on B-roll upload, `?persona=` API filters, `clipfactory personas list|seed` and `clipfactory assets migrate-personas --to <id>`.
### Changed
- `configs/personas/*.json` are now seeds only (inserted when missing; legacy rows without a voice block are repaired from the seed).

## [0.1.0] — 2026-08-22
### Added
- Content factory: topic + template → script (OpenAI) → voice (ElevenLabs, real duration as master clock) → library-aware scene plan → B-roll selection (relevance × quality × freshness) → validated Video JSON → ASS captions with safe zones → 2-stage FFmpeg render → QC; versioned artifacts; regenerate-script / change-assets / render-again / scene override / retry / approve.
- CLI (`clipfactory`, alias `ttcf`) and REST API; web UI (React + Vite + Tailwind + shadcn): Projects, Generate, Project timeline (filmstrip synced to the player), B-roll library (single-clip upload with AI autocomplete from sampled frames, usable-range trimmer, AI enrich, delete), Templates editor, System.
- AI Lab (isolated module): prompt → storyboard → chained keyframes (OpenAI images) → per-segment animation with a per-video model (Gemini Omni, Veo 3.1, fal.ai: Seedance 2.0/2.5, MiniMax H3, Kling 3.0) → 9:16 MP4; activity log, retry, per-segment redo/edit, change length, clone for A/B, cost estimate.
- Docker Compose (db + api + web), configs for personas/templates/captions, docs (architecture, providers).
