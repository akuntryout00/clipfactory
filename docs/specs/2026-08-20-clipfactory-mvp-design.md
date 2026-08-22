# ClipFactory MVP — Design (as built)

Date: 2026-08-20 · Source: `prd.md` · Status: implemented (CLI + API), UI intentionally deferred

## Decisions
| Topic | Decision | Why |
|---|---|---|
| LLM | OpenAI (`chat.completions.parse` structured outputs) behind `LLMProvider` protocol; `fake` provider for tests | user has OpenAI key; PRD demands provider-agnostic business logic |
| Voice | ElevenLabs `convert_with_timestamps` → mp3 + char alignment → word timings; `fake` provider (tone + synthetic timings) | PRD §14: real duration + alignment is the master clock |
| UI | none (CLI + REST) | user decision; PRD §54 says validate Topic→MP4 in terminal first |
| Music | supported (−20 dB + sidechain ducking), library empty | user decision |
| DB | PostgreSQL in compose, SQLAlchemy 2.0; SQLite for tests | PRD §26 |
| Jobs | in-process thread pool (1 job per project) | single-user MVP; upgrade path: separate worker container |
| Render | two-stage FFmpeg (per-scene intermediates → concat+ass+audio) | debuggable, deterministic, scene clips can be inspected |

## Pipeline contract
`Script → Voice(duration, words) → plan_scenes(LLM word ranges) → normalize_plan (snap/merge/split/cap) → assign_assets (filter → LLM rank → unique → segment) → VideoJSON(validated) → captions → render → QC`.
Every stage persists `*_vN` artifacts; controls only re-run downstream stages:
* regenerate-script: script, voice, plan, render (all new versions)
* change-assets: plan (same cut, previous assets excluded) + render
* render-again: plan (same assets, new seed) + render
* scene override: plan (one asset pinned, same seed) + render
* retry: resume FAILED project from failed stage

## Video JSON (v1.0)
`persona, template, topic, voiceover{text,audio,duration}, scenes[{order,start,end,asset_id,asset_file,asset_start,text,section}], caption_style, music, captions[{start,end,text,emphasis_index}], seed`. Validation: contiguous scenes from 0, sequential order, end>start.

## Safe zones & captions
Captions: bottom-center anchor at 72 % height (above the 18 % bottom reserve), max 4 words / 2 lines / 16 chars per line, emphasised longest non-stopword in yellow, 120 ms pop. Overlays: top-center at 36 %, 1–3 per video, max 14 chars/line, fades. Margins left 5 % / right 12 %.

## Open items / post-MVP
Music library, AI-assisted semantic tagging on import (currently heuristic + seed JSON), Next.js UI, R2/S3 storage, embeddings when the library grows.
