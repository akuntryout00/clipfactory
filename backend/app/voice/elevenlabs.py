"""ElevenLabs TTS with character timestamps → mp3 + word alignment + real duration (PRD §14)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from app.assets.metadata import ffprobe_json
from app.config.settings import get_settings
from app.schemas.configs import VoiceConfig
from app.schemas.pipeline import VoiceResult
from app.voice.alignment import chars_to_words, synthetic_words


class ElevenLabsVoice:
    name = "elevenlabs"

    def __init__(self, api_key: str | None = None):
        from elevenlabs.client import ElevenLabs

        key = api_key or get_settings().elevenlabs_api_key
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        self._client = ElevenLabs(api_key=key)

    def synthesize(self, *, text: str, voice: VoiceConfig, out_path: Path) -> VoiceResult:
        from elevenlabs.types import VoiceSettings

        voice_id = voice.voice_id or get_settings().elevenlabs_voice_id
        if not voice_id:
            raise RuntimeError("ELEVENLABS_VOICE_ID is not set (persona voice_id empty)")
        settings = VoiceSettings(stability=voice.stability, similarity_boost=voice.similarity_boost,
                                 style=voice.style, use_speaker_boost=True, speed=voice.speed)
        resp = self._client.text_to_speech.convert_with_timestamps(
            voice_id, text=text, model_id=voice.model_id, output_format="mp3_44100_128", voice_settings=settings,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(resp.audio_base_64))
        alignment = resp.alignment or resp.normalized_alignment
        if alignment and alignment.characters:
            words = chars_to_words(alignment.characters, alignment.character_start_times_seconds, alignment.character_end_times_seconds)
        else:
            words = []
        duration = _audio_duration(out_path)
        if not words:
            words = synthetic_words(text, duration)
        align_path = out_path.with_suffix(".alignment.json")
        align_path.write_text(json.dumps({
            "words": [w.model_dump() for w in words],
            "raw": alignment.model_dump() if alignment else None,
        }))
        return VoiceResult(audio_path=str(out_path), duration=duration, words=words, provider=self.name, alignment_path=str(align_path))


def _audio_duration(path: Path) -> float:
    data = ffprobe_json(path)
    return round(float(data.get("format", {}).get("duration") or 0.0), 3)
