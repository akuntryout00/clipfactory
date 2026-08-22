# Security

ClipFactory runs locally and talks only to the AI providers you configure. Still, it stores provider API keys (`.env`) and processes files you upload.

## Reporting a vulnerability
Please **do not** open a public issue for security problems. Use GitHub's private vulnerability reporting on this repository, or DM the maintainer on X/Twitter: [@feyzili](https://twitter.com/feyzili). Include steps to reproduce and the affected version/commit. We aim to acknowledge within 72 hours.

## Scope / notes
- Keys are read from `.env` and never logged; the System page only shows whether a key is set.
- The API has **no authentication** — it is meant to run on your machine/LAN. Do not expose ports 8000/3000 to the internet without a reverse proxy with auth.
- Uploaded clips and generated media stay under `assets/` and `storage/`; sampled frames/images are sent to the AI providers only for the features you trigger (AI autocomplete, AI Lab).
- Dependencies: Python via `backend/requirements.lock.txt`, Node via `frontend/package-lock.json`.
