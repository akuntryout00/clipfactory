# Changelog

All notable changes are documented here. Format: Keep a Changelog · SemVer.

## [Unreleased]

## [0.1.0] — 2026-08-22
### Added
- Content factory: topic + template → script (OpenAI) → voice (ElevenLabs, real duration as master clock) → library-aware scene plan → B-roll selection (relevance × quality × freshness) → validated Video JSON → ASS captions with safe zones → 2-stage FFmpeg render → QC; versioned artifacts; regenerate-script / change-assets / render-again / scene override / retry / approve.
- CLI (`clipfactory`, alias `ttcf`) and REST API; web UI (React + Vite + Tailwind + shadcn): Projects, Generate, Project timeline (filmstrip synced to the player), B-roll library (single-clip upload with AI autocomplete from sampled frames, usable-range trimmer, AI enrich, delete), Templates editor, System.
- AI Lab (isolated module): prompt → storyboard → chained keyframes (OpenAI images) → per-segment animation with a per-video model (Gemini Omni, Veo 3.1, fal.ai: Seedance 2.0/2.5, MiniMax H3, Kling 3.0) → 9:16 MP4; activity log, retry, per-segment redo/edit, change length, clone for A/B, cost estimate.
- Docker Compose (db + api + web), configs for personas/templates/captions, docs (architecture, providers).
