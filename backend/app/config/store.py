"""Provider settings entered in the web UI (first-run setup), stored in the `app_settings` table and overlaid on the environment.

Resolution order: values saved in the UI (DB) > process environment > .env file > code defaults. The overlay works by exporting the
DB values into os.environ and clearing the cached Settings object, so every `get_settings()` caller (providers, lab, CLI) sees them.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models import AppSetting

SETTINGS_KEY = "providers"

# field → (env var, is_secret)
FIELDS: dict[str, tuple[str, bool]] = {
    "llm_provider": ("LLM_PROVIDER", False),
    "openai_api_key": ("OPENAI_API_KEY", True),
    "openai_model": ("OPENAI_MODEL", False),
    "voice_provider": ("VOICE_PROVIDER", False),
    "elevenlabs_api_key": ("ELEVENLABS_API_KEY", True),
    "elevenlabs_voice_id": ("ELEVENLABS_VOICE_ID", False),
    "google_api_key": ("GOOGLE_API_KEY", True),
    "google_video_model": ("GOOGLE_VIDEO_MODEL", False),
    "fal_key": ("FAL_KEY", True),
    "lab_video_provider": ("LAB_VIDEO_PROVIDER", False),
    "openai_image_model": ("OPENAI_IMAGE_MODEL", False),
}
_applied: set[str] = set()  # env vars we exported, so we can undo when a value is cleared


def load(session: Session) -> dict[str, str]:
    row = session.get(AppSetting, SETTINGS_KEY)
    return {k: v for k, v in (row.value or {}).items() if k in FIELDS and v not in (None, "")} if row else {}


def save(session: Session, updates: dict[str, Any]) -> dict[str, str]:
    """Merge: missing keys unchanged, empty string / None clears the key. Returns the stored dict and applies it to the env."""
    current = load(session)
    for k, v in updates.items():
        if k not in FIELDS:
            continue
        if v in (None, ""):
            current.pop(k, None)
        else:
            current[k] = str(v).strip()
    row = session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY, value={})
        session.add(row)
    row.value = dict(current)
    session.commit()
    apply(current)
    return current


def apply(values: dict[str, str]) -> None:
    """Export stored values to the environment (overriding .env) and refresh the cached settings."""
    global _applied
    wanted = {FIELDS[k][0]: v for k, v in values.items() if k in FIELDS}
    for env in _applied - set(wanted):
        os.environ.pop(env, None)
    for env, v in wanted.items():
        os.environ[env] = v
    _applied = set(wanted)
    get_settings.cache_clear()


def apply_from_db(session: Session) -> None:
    apply(load(session))


def _mask(v: str | None) -> str | None:
    if not v:
        return None
    return ("•" * 8 + v[-4:]) if len(v) > 8 else "•" * len(v)


def describe(session: Session) -> dict:
    """What the UI shows: per field set/source/masked value; plus readiness."""
    s = get_settings()
    db = load(session)
    out: dict[str, Any] = {"fields": {}}
    for k, (_env, secret) in FIELDS.items():
        val = getattr(s, k, None)
        out["fields"][k] = {
            "set": bool(val),
            "source": "ui" if k in db else ("env" if val else None),
            "value": (_mask(val) if secret else val) if val else None,
            "secret": secret,
        }
    out.update(status(s))
    return out


def status(s=None) -> dict:
    s = s or get_settings()
    missing = []
    if s.llm_provider != "fake" and not s.openai_api_key:
        missing.append("openai_api_key")
    if s.voice_provider != "fake" and not s.elevenlabs_api_key:
        missing.append("elevenlabs_api_key")
    return {
        "configured": not missing,
        "setup_required": bool(missing),
        "missing": missing,
        "llm_provider": s.llm_provider,
        "voice_provider": s.voice_provider,
        "lab_ready": bool(s.google_api_key or s.fal_key),
    }


# ---------------------------------------------------------------- connection tests


def test_provider(name: str, values: dict[str, str] | None = None) -> dict:
    """Cheap live check with the given (unsaved) values, falling back to the active settings. Never raises."""
    s = get_settings()
    v = values or {}

    def pick(field: str):
        return v[field] if field in v else getattr(s, field, None)

    try:
        if name == "openai":
            from openai import OpenAI

            key = pick("openai_api_key")
            if not key:
                return {"ok": False, "message": "no API key"}
            model = v.get("openai_model") or s.openai_model
            OpenAI(api_key=key).models.retrieve(model)
            return {"ok": True, "message": f"OpenAI OK · model {model} available"}
        if name == "elevenlabs":
            from elevenlabs.client import ElevenLabs

            key = pick("elevenlabs_api_key")
            if not key:
                return {"ok": False, "message": "no API key"}
            res = ElevenLabs(api_key=key).voices.get_all()
            voices = [{"id": x.voice_id, "name": x.name, "labels": getattr(x, "labels", None) or {}} for x in (res.voices or [])]
            return {"ok": True, "message": f"ElevenLabs OK · {len(voices)} voices", "voices": voices}
        if name == "google":
            from google import genai

            key = pick("google_api_key")
            if not key:
                return {"ok": False, "message": "no API key"}
            client = genai.Client(api_key=key)
            next(iter(client.models.list(config={"page_size": 1})), None)
            return {"ok": True, "message": "Google AI OK"}
        if name == "fal":
            import httpx

            key = pick("fal_key")
            if not key:
                return {"ok": False, "message": "no API key"}
            r = httpx.get("https://rest.alpha.fal.ai/", headers={"Authorization": f"Key {key}"}, timeout=10)
            if r.status_code in (401, 403):
                return {"ok": False, "message": f"fal.ai rejected the key ({r.status_code})"}
            return {"ok": True, "message": "fal.ai key accepted"}
        return {"ok": False, "message": f"unknown provider {name}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)[:300]}
