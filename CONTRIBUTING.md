# Contributing to ClipFactory

Thanks for helping! This project is source-available under the Elastic License 2.0 (see LICENSE) — contributions are welcome under the same terms.

## Ground rules
- **Tests first.** Every behaviour change comes with a test (backend: `pytest`; frontend: `tsc -b` must pass, add component tests when you touch logic). Fake providers (`LLM_PROVIDER=fake`, `VOICE_PROVIDER=fake`, `LAB_*_PROVIDER=fake`) let the whole pipeline run offline.
- **No secrets, no personal footage.** `.env`, `assets/`, `storage/` are git-ignored — keep it that way. Never commit API keys (pre-commit + gitleaks-style scan recommended).
- **Config over code.** Personas, templates, caption styles live in `configs/`; provider/model choices in `.env`. If a behaviour can be a config knob, make it one.
- **Providers are plugins.** New models go behind the protocols in `app/llm/base.py`, `app/voice/base.py`, `app/lab/providers.py` (see `docs/PROVIDERS.md`).
- Keep PRs focused; describe the user-visible change and how you verified it (commands, screenshots for UI).

## Development setup
```bash
git clone … && cd clipfactory
cp .env.example .env                      # fakes work without keys: LLM_PROVIDER=fake VOICE_PROVIDER=fake LAB_*_PROVIDER=fake
# backend
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q
# full suite incl. ffmpeg/libass renders
cd .. && make test
# frontend
cd frontend && npm install && npm run dev   # http://localhost:3000 → proxies /api to http://localhost:8000
# everything in docker
make up
```
Lint/format: `cd backend && .venv/bin/ruff check . && .venv/bin/ruff format .`; `cd frontend && npm run lint`. `pre-commit install` wires these to git hooks.

## Branching & releases
- Work on feature branches, open a PR against `main` (`main` is protected; CI will be added).
- Semantic versioning; keep `CHANGELOG.md` updated under *Unreleased*.

## Reporting issues
Use the issue templates. Include your OS, Docker version, provider/model, and the relevant lines from `docker compose logs api` or the project/lab activity log (strip keys).
