"""Inbox: a token-protected, phone-friendly view of a persona's finished projects (no app login needed)."""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.models import AppSetting

KEY = "inbox_tokens"


def _row(session: Session) -> AppSetting:
    row = session.get(AppSetting, KEY)
    if row is None:
        row = AppSetting(key=KEY, value={})
        session.add(row)
        session.commit()
    return row


def token_for(session: Session, persona_id: str, *, rotate: bool = False) -> str:
    row = _row(session)
    tokens = dict(row.value or {})
    if rotate or not tokens.get(persona_id):
        tokens[persona_id] = secrets.token_urlsafe(18)
        row.value = tokens
        session.commit()
    return tokens[persona_id]


def check_token(session: Session, persona_id: str, token: str | None) -> bool:
    row = session.get(AppSetting, KEY)
    return bool(token) and bool(row) and secrets.compare_digest(str((row.value or {}).get(persona_id) or ""), str(token))
