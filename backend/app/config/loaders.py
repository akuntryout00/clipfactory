"""Load and validate JSON configs (personas, templates, caption styles)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.config.settings import get_settings
from app.schemas.configs import CaptionStyleConfig, PersonaConfig, TemplateConfig

CONFIGS_DIR: Path = get_settings().configs_dir

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _substitute_env(text: str) -> str:
    """Replace ${VAR} with environment values (empty string if unset)."""
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), text)


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"config not found: {path}")
    return _substitute_env(path.read_text(encoding="utf-8"))


def load_persona(persona_id: str, configs_dir: Path | None = None) -> PersonaConfig:
    base = configs_dir or CONFIGS_DIR
    raw = _read(base / "personas" / f"{persona_id}.json")
    persona = PersonaConfig.model_validate_json(raw)
    if not persona.voice.voice_id:
        # fall back to settings-level voice id (env ELEVENLABS_VOICE_ID)
        persona.voice.voice_id = get_settings().elevenlabs_voice_id or ""
    return persona


def load_template(template_id: str, configs_dir: Path | None = None) -> TemplateConfig:
    base = configs_dir or CONFIGS_DIR
    return TemplateConfig.model_validate_json(_read(base / "templates" / f"{template_id}.json"))


def list_templates(configs_dir: Path | None = None) -> list[TemplateConfig]:
    base = configs_dir or CONFIGS_DIR
    out = []
    for p in sorted((base / "templates").glob("*.json")):
        out.append(TemplateConfig.model_validate_json(_read(p)))
    return out


def list_personas(configs_dir: Path | None = None) -> list[PersonaConfig]:
    base = configs_dir or CONFIGS_DIR
    return [load_persona(p.stem, base) for p in sorted((base / "personas").glob("*.json"))]


def load_caption_style(style_id: str, configs_dir: Path | None = None) -> CaptionStyleConfig:
    base = configs_dir or CONFIGS_DIR
    return CaptionStyleConfig.model_validate_json(_read(base / "captions" / f"{style_id}.json"))


def load_json(path: Path) -> dict:
    return json.loads(_read(path))
