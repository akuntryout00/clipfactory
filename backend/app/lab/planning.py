"""Duration → segment plan. Each segment is one AI-animated clip between two keyframes (4–8 s)."""
from __future__ import annotations

import math

MIN_SEG, MAX_SEG = 4, 8


def segment_plan(target_duration: float) -> tuple[int, int]:
    """Return (n_segments, seconds_per_segment) covering the target with the fewest 4–8 s clips."""
    n = max(2, math.ceil(target_duration / MAX_SEG))
    seg = int(round(target_duration / n))
    seg = max(MIN_SEG, min(MAX_SEG, seg))
    return n, seg
