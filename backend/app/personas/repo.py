"""Personas live in the database (table `personas`); JSON files under configs/personas are only seeds/examples."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.loaders import list_personas as list_config_personas
from app.models import Persona
from app.schemas.configs import PersonaConfig


def _to_config(row: Persona) -> PersonaConfig:
    data = dict(row.config or {})
    data.setdefault("id", row.id)
    data.setdefault("name", row.name)
    return PersonaConfig.model_validate(data)


def get_persona(session: Session, persona_id: str) -> PersonaConfig:
    row = session.get(Persona, persona_id)
    if row is None:
        raise KeyError(f"persona not found: {persona_id}")
    return _to_config(row)


def list_personas(session: Session) -> list[PersonaConfig]:
    return [_to_config(r) for r in session.execute(select(Persona).order_by(Persona.id)).scalars()]


def upsert_persona(session: Session, cfg: PersonaConfig) -> PersonaConfig:
    row = session.get(Persona, cfg.id)
    if row is None:
        row = Persona(id=cfg.id, name=cfg.name, config={})
        session.add(row)
    row.name = cfg.name
    row.config = cfg.model_dump()
    session.commit()
    return cfg


def delete_persona(session: Session, persona_id: str) -> None:
    row = session.get(Persona, persona_id)
    if row is None:
        raise KeyError(f"persona not found: {persona_id}")
    session.delete(row)
    session.commit()


def seed_personas_from_configs(session: Session, configs_dir: Path | None = None) -> int:
    """Insert personas from configs/personas/*.json that are not in the DB yet (never overwrites DB edits).

    Rows written by older versions (config mirror without the voice block) fail validation; those are
    repaired from the JSON file so the persona stays usable.
    """
    n = 0
    for cfg in list_config_personas(configs_dir):
        row = session.get(Persona, cfg.id)
        if row is None:
            session.add(Persona(id=cfg.id, name=cfg.name, config=cfg.model_dump()))
            n += 1
            continue
        try:
            _to_config(row)
        except ValidationError:
            row.name = cfg.name
            row.config = cfg.model_dump()
            n += 1
    session.commit()
    return n


def persona_or_config(session: Session, persona_id: str, configs_dir: Path | None = None) -> PersonaConfig:
    """DB first, then JSON configs (tests / first run before seeding). Raises FileNotFoundError if neither has it."""
    try:
        return get_persona(session, persona_id)
    except KeyError:
        from app.config.loaders import load_persona

        return load_persona(persona_id, configs_dir)  # raises FileNotFoundError
