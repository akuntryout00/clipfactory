"""Voice provider abstraction."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.schemas.configs import VoiceConfig
from app.schemas.pipeline import VoiceResult


class VoiceProvider(Protocol):
    name: str

    def synthesize(self, *, text: str, voice: VoiceConfig, out_path: Path) -> VoiceResult: ...


def get_voice_provider(provider: str | None = None) -> VoiceProvider:
    from app.config.settings import get_settings

    name = (provider or get_settings().voice_provider).lower()
    if name == "fake":
        from app.voice.fake import FakeVoice

        return FakeVoice()
    if name == "elevenlabs":
        from app.voice.elevenlabs import ElevenLabsVoice

        return ElevenLabsVoice()
    raise ValueError(f"unknown voice provider: {name}")
