# Security

ClipFactory runs locally and talks only to the AI providers you configure. Still, it stores provider API keys (`.env`) and processes files you upload.

## Reporting a vulnerability
Please **do not** open a public issue for security problems. Use GitHub's private vulnerability reporting on this repository, or DM the maintainer on X/Twitter: [@feyzili](https://twitter.com/feyzili). Include steps to reproduce and the affected version/commit. We aim to acknowledge within 72 hours.

## Scope / notes
- Keys come from the Setup page (stored in the `app_settings` table of the local Postgres volume, plain text) or from `.env`; they are never logged and the UI only shows the last 4 characters. Anyone with access to the database volume or the API port can read them — keep both local.
- Inbox links (`/inbox/<persona>?key=…`) are bearer links: anyone holding the link can view and download that persona's finished videos — share them only with the phone that needs them and rotate the link from the Personas page if it leaks. Keep the base URL on a private network (LAN / Tailscale).
- The API has **no authentication** — it is meant to run on your machine/LAN. Do not expose ports 8000/3000 to the internet without a reverse proxy with auth.
- Uploaded clips and generated media stay under `assets/` and `storage/`; sampled frames/images are sent to the AI providers only for the features you trigger (AI autocomplete, AI Lab).
- Dependencies: Python via `backend/requirements.lock.txt`, Node via `frontend/package-lock.json`.
