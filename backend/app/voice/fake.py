"""Offline voice provider: renders a quiet tone track of the estimated length + synthetic word timings."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.config.settings import get_settings
from app.schemas.configs import VoiceConfig
from app.schemas.pipeline import VoiceResult
from app.voice.alignment import synthetic_words

WORDS_PER_SECOND = 2.5


class FakeVoice:
    name = "fake"

    def synthesize(self, *, text: str, voice: VoiceConfig, out_path: Path) -> VoiceResult:
        n_words = len(text.split())
        duration = round(max(1.0, n_words / (WORDS_PER_SECOND * voice.speed)), 2)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # a soft 220 Hz beep every second so the mix is audible in tests / dry runs
        subprocess.run(
            [
                get_settings().ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=220:sample_rate=44100:duration={duration}",
                "-af",
                "volume=0.15",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                str(out_path),
            ],
            check=True,
        )
        words = synthetic_words(text, duration)
        align_path = out_path.with_suffix(".alignment.json")
        align_path.write_text(json.dumps([w.model_dump() for w in words]))
        return VoiceResult(audio_path=str(out_path), duration=duration, words=words, provider=self.name, alignment_path=str(align_path))
