"""Character-level alignment → word timings."""
from __future__ import annotations

from app.schemas.pipeline import WordTiming


def chars_to_words(characters: list[str], starts: list[float], ends: list[float]) -> list[WordTiming]:
    words: list[WordTiming] = []
    buf, w_start, w_end = "", None, None
    for ch, s, e in zip(characters, starts, ends):
        if ch.isspace():
            if buf:
                words.append(WordTiming(word=buf, start=round(w_start, 3), end=round(w_end, 3)))
                buf, w_start, w_end = "", None, None
            continue
        if not buf:
            w_start = s
        buf += ch
        w_end = e
    if buf:
        words.append(WordTiming(word=buf, start=round(w_start, 3), end=round(w_end, 3)))
    # guarantee monotonic, non-zero durations
    fixed: list[WordTiming] = []
    for w in words:
        if fixed and w.start < fixed[-1].end:
            w.start = fixed[-1].end
        if w.end <= w.start:
            w.end = round(w.start + 0.05, 3)
        fixed.append(w)
    return fixed


def synthetic_words(text: str, total_duration: float) -> list[WordTiming]:
    """Evenly spread word timings (used by the fake provider / fallback when alignment is missing)."""
    tokens = [t for t in text.split() if t]
    if not tokens:
        return []
    # weight by character length so long words get more time
    weights = [max(2, len(t)) for t in tokens]
    total_w = sum(weights)
    words, t = [], 0.0
    for tok, w in zip(tokens, weights):
        dur = total_duration * w / total_w
        words.append(WordTiming(word=tok, start=round(t, 3), end=round(t + dur * 0.9, 3)))
        t += dur
    return words
