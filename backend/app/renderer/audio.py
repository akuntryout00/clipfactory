"""Audio graph: voice loudness normalisation, optional music bed with ducking (PRD §18, §20)."""
from __future__ import annotations


def build_audio_graph(has_music: bool, voice_idx: int, music_idx: int | None, music_db: float = -20.0,
                      total_duration: float = 0.0) -> tuple[str, str]:
    """Return (filter_complex_string, output_label) for the audio chain.

    voice → loudnorm → [v]
    music → loop/trim → volume(music_db) → sidechain-ducked by voice → [m]
    amix(v, m) → [aout]
    """
    parts = [f"[{voice_idx}:a]aresample=44100,loudnorm=I=-16:TP=-1.5:LRA=11,apad=pad_dur=2[v]"]
    if not has_music or music_idx is None:
        parts.append(f"[v]atrim=0:{total_duration:.3f},asetpts=N/SR/TB[aout]")
        return ";".join(parts), "[aout]"
    parts.append(
        f"[{music_idx}:a]aresample=44100,aloop=loop=-1:size=2e9,atrim=0:{total_duration:.3f},"
        f"volume={music_db}dB,afade=t=out:st={max(total_duration - 1.2, 0):.3f}:d=1.2[mraw]"
    )
    parts.append("[v]asplit=2[v1][vsc]")
    parts.append("[mraw][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=400[m]")
    parts.append(f"[v1][m]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,atrim=0:{total_duration:.3f},asetpts=N/SR/TB[aout]")
    return ";".join(parts), "[aout]"
