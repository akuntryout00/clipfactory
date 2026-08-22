# Changelog

All notable changes are documented here. Format: Keep a Changelog · SemVer.

## [Unreleased]
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
